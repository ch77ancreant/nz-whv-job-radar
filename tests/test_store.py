"""Offline SQLite state transitions, isolation and retry safety."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from nz_job_radar import store as store_module
from nz_job_radar.jobs import Job, MatchDecision
from nz_job_radar.journal import Journal
from nz_job_radar.pipeline import Report
from nz_job_radar.store import (
    JobStore,
    StoreError,
    canonical_chat_id,
    destination_key,
    important_version,
)
from nz_job_radar.whv import Evidence, assess_job

CHAT = "-1000012345678"
CHECKED = date(2026, 9, 23)


def job(number="101", **changes):
    item = Job(
        source_job_id=str(number),
        source_url=f"https://nz.seek.com/job/{number}",
        title="Cafe Assistant",
        employer="Fictional Cafe",
        location="Auckland",
        country="NZ",
        employment_type="Contract/Temp",
        salary="$25/hour",
        posted_at="2026-09-01",
        closes_at="2026-09-30",
        description="Temporary contract for two months. WHV holders welcome.",
    )
    return replace(item, **changes)


def report(
    *items, mode="live", profile="cafe", eligible=True, status="matched", attempt="attempt-1"
):
    result = Report(profile, mode, attempt, assessed_at=CHECKED.isoformat())
    for item in items or (job(),):
        result.whv_assessments[item.source_job_id] = assess_job(item, today=CHECKED)
        if status == "matched":
            result.matched.append(item)
        elif status == "excluded":
            result.excluded.append((item, MatchDecision("excluded", ("test_exclusion",))))
        else:
            result.pending.append(
                (item, MatchDecision("needs_confirmation", ("employer_unknown",)))
            )
        if eligible and status == "matched":
            result.notification_candidates.add(item.source_job_id)
    return result


@pytest.fixture
def database(tmp_path):
    clock = [datetime(2026, 9, 23, 0, 0, tzinfo=UTC)]
    store = JobStore(tmp_path / "runs.sqlite3", now=lambda: clock[0])
    yield store, clock
    store.close()


def record(store, value=None, **options):
    return store.record(value or report(), profile_fingerprint="fingerprint-1", **options)


def queued(store, value=None, chat=CHAT):
    plan = record(store, value, chat_id=chat, enqueue=True)
    return plan.messages[0].outbox_id


def test_additive_schema_preserves_existing_run_and_summary(tmp_path):
    path = tmp_path / "runs.sqlite3"
    journal = Journal(path)
    attempt = journal.fixture("old-profile", "old-fingerprint")
    journal.finish(attempt.id, {"profile_id": "old-profile", "matched": 2}, complete=True)
    before = journal.list_runs()
    store = JobStore(path)
    record(store)
    assert journal.list_runs() == before
    store.close()
    second = JobStore(path)
    assert second.connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
    second.close()
    journal.close()


def test_persists_all_valid_jobs_and_only_bounded_evidence(database):
    store, _ = database
    extra = "Unrelated full body marker. " * 300
    first = job(description="Temporary contract for two months. WHV holders welcome. " + extra)
    value = report(first)
    excluded, pending = job("102"), job("103")
    value.excluded.append((excluded, MatchDecision("excluded", ("location_mismatch",))))
    value.pending.append((pending, MatchDecision("needs_confirmation", ("employer_unknown",))))
    value.whv_assessments.update(
        {item.source_job_id: assess_job(item, today=CHECKED) for item in (excluded, pending)}
    )
    plan = record(store, value)
    assert (plan.persisted, plan.new_jobs, plan.queued, plan.messages) == (3, 3, 0, ())
    rows = store.connection.execute("SELECT * FROM job_versions").fetchall()
    assert len(rows) == 3
    for row in rows:
        assert "description" not in json.loads(row["snapshot_json"])
        assert len(row["description_hash"]) == 64
        assert extra not in row["assessment_json"]
    assert store.list_outbox() == []


def test_repeat_and_cross_profile_deduplicate_canonical_seek_id(database):
    store, _ = database
    first = record(store, report(job(source_job_id="actor-fallback-a")), chat_id=CHAT, enqueue=True)
    second = record(
        store,
        report(job(source_job_id="actor-fallback-b"), profile="second"),
        chat_id=CHAT,
        enqueue=True,
    )
    assert first.new_jobs == first.queued == 1
    assert second.new_jobs == second.changed_jobs == second.queued == 0
    assert second.deduplicated == 1
    assert store.connection.execute("SELECT job_id FROM jobs").fetchone()[0] == "101"
    row = store.list_outbox()[0]
    assert [item["profile_id"] for item in row["eligible_profiles"]] == ["cafe", "second"]
    assert row["destination_key"] == destination_key(CHAT)
    assert row["rules_checked_at"] == "2026-09-23"


def test_formatting_posted_closes_evidence_and_checked_dates_do_not_change_version(database):
    store, _ = database
    base = job()
    first = record(store, report(base))
    cosmetic = replace(
        base,
        title=" CAFE   assistant ",
        employer="FICTIONAL CAFE",
        posted_at="2026-09-20",
        closes_at="2026-10-30",
        description="<p>TEMPORARY contract for two months.</p>\n<div>WHV holders welcome.</div>",
    )
    value = report(cosmetic)
    value.whv_assessments["101"] = replace(
        report(base).whv_assessments["101"],
        rules_checked_at="2026-09-24",
        assessed_at="2026-09-24",
        evidence=(Evidence("description", "different layout"),),
        reasons=("presentation_only",),
        score=89,
    )
    second = record(store, value)
    assert first.new_jobs == 1
    assert second.changed_jobs == 0
    assert store.connection.execute("SELECT count(*) FROM job_versions").fetchone()[0] == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"salary": "$26/hour"},
        {"location": "Wellington"},
        {"employer": "Other Employer"},
        {"title": "Cafe Assistant!"},
        {"employment_type": "Casual"},
        {"description": "Temporary contract for two months. No WHV holders welcome."},
    ],
)
def test_meaningful_content_changes_make_versions(database, changes):
    store, _ = database
    record(store)
    plan = record(store, report(job(**changes)))
    assert plan.changed_jobs == 1
    assert store.connection.execute("SELECT count(*) FROM job_versions").fetchone()[0] == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"label": "needs_confirmation"},
        {"rule_version": "tw-whv-2.0"},
        {"rules_stale": True},
    ],
)
def test_semantic_rule_changes_make_versions(changes):
    item = job()
    assessment = assess_job(item, today=CHECKED)
    assert important_version(item, assessment) != important_version(
        item, replace(assessment, **changes)
    )


def test_preview_is_repeatable_and_does_not_consume_next_send(database):
    store, _ = database
    first = record(store, preview=True, chat_id=CHAT)
    second = record(store, preview=True, chat_id=CHAT)
    assert first.messages == second.messages
    assert len(first.messages) == 1
    assert first.queued == second.queued == 0
    assert store.list_outbox() == []
    send = record(store, enqueue=True, chat_id=CHAT)
    assert send.queued == 1
    assert record(store, preview=True, chat_id=CHAT).deduplicated == 1


def test_fixture_preview_and_live_keys_are_isolated(database):
    store, _ = database
    synthetic = record(store, report(mode="fixture"), preview=True)
    assert synthetic.new_jobs == 1 and synthetic.messages
    actual = record(store, enqueue=True, chat_id=CHAT)
    assert actual.new_jobs == 1 and actual.queued == 1
    assert store.connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 2
    assert store.connection.execute("SELECT count(*) FROM profile_matches").fetchone()[0] == 2
    assert store.list_outbox(mode="fixture") == []
    with pytest.raises(StoreError):
        record(store, report(mode="fixture"), enqueue=True, chat_id=CHAT)


@pytest.mark.parametrize("chat", ["0", "-0", "@channel", "preview", "123:secret", "1.5", "", "1 2"])
def test_invalid_destinations_are_rejected(chat):
    with pytest.raises(StoreError):
        destination_key(chat)


def test_destination_canonicalization_and_payload_privacy(database):
    store, _ = database
    assert canonical_chat_id(" -000123 ") == "-123"
    assert destination_key(" -000123 ") == destination_key("-123")
    first = record(store, chat_id=" -000123 ", enqueue=True)
    assert record(store, chat_id="-123", enqueue=True).deduplicated == 1
    assert record(store, chat_id="-456", enqueue=True).messages[0].kind == "new"
    payload = json.dumps(store.get(first.messages[0].outbox_id))
    assert "-000123" not in payload and '"chat_id"' not in payload


def test_claim_is_atomic_and_destination_and_eligibility_checked(database):
    store, _ = database
    identifier = queued(store)
    with pytest.raises(StoreError):
        store.claim(identifier, "-123")
    row = store.claim(identifier, CHAT)
    assert row["status"] == "sending" and row["attempts"] == 1
    assert store.claim(identifier, CHAT) is None
    assert store.get(identifier)["attempt_history"][0]["status"] == "sending"


def test_sent_version_deduplicates_and_new_version_is_update(database):
    store, _ = database
    identifier = queued(store)
    store.claim(identifier, CHAT)
    store.finish(identifier, status="sent", message_id=27)
    assert record(store, chat_id=CHAT, enqueue=True).deduplicated == 1
    updated = record(store, report(job(salary="$26/hour")), chat_id=CHAT, enqueue=True)
    assert updated.queued == updated.changed_jobs == 1
    assert updated.messages[0].kind == "update"
    assert store.get(identifier)["status"] == "sent"
    assert store.claim(identifier, CHAT) is None


def test_retry_budget_delay_and_explicit_reset_preserve_history(database):
    store, clock = database
    identifier = queued(store)
    store.claim(identifier, CHAT, max_attempts=2)
    store.finish(identifier, status="retryable", error_code="rate_limited", retry_after=60)
    assert store.claim(identifier, CHAT, max_attempts=2) is None
    clock[0] += timedelta(seconds=60)
    assert store.claim(identifier, CHAT, max_attempts=2)["attempts"] == 2
    store.finish(identifier, status="retryable", error_code="http_503")
    assert store.get(identifier)["status"] == "failed"
    assert store.claim(identifier, CHAT) is None
    assert record(store, enqueue=True, chat_id=CHAT).deduplicated == 1
    store.resolve(identifier, action="retry")
    assert store.get(identifier)["attempts"] == 0
    assert store.claim(identifier, CHAT)["attempts"] == 1
    history = store.get(identifier)["attempt_history"]
    assert [item["event"] for item in history] == ["send", "send", "resolution", "send"]
    assert history[-1]["budget_generation"] == 1


def test_unknown_blocks_all_new_versions_until_explicit_resolution(database):
    store, _ = database
    identifier = queued(store)
    store.claim(identifier, CHAT)
    store.finish(identifier, status="delivery_unknown", error_code="delivery_unknown")
    assert store.claim(identifier, CHAT) is None
    newer = report(job(salary="$26/hour"))
    held = record(store, newer, enqueue=True, chat_id=CHAT)
    assert held.held == 1 and held.queued == 0
    assert record(store, newer, preview=True, chat_id=CHAT).held == 1
    assert store.get(identifier)["status"] == "delivery_unknown"
    with pytest.raises(StoreError):
        store.resolve(identifier, action="retry")
    store.resolve(identifier, action="skip")
    after = record(store, newer, enqueue=True, chat_id=CHAT)
    assert after.queued == 1 and after.messages[0].kind == "new"


def test_unknown_manual_sent_requires_message_and_makes_next_notice_update(database):
    store, _ = database
    identifier = queued(store)
    store.claim(identifier, CHAT)
    store.finish(identifier, status="delivery_unknown")
    with pytest.raises(StoreError):
        store.resolve(identifier, action="sent")
    store.resolve(identifier, action="sent", message_id=99)
    assert store.get(identifier)["message_id"] == 99
    updated = record(store, report(job(salary="$26/hour")), enqueue=True, chat_id=CHAT)
    assert updated.messages[0].kind == "update"


@pytest.mark.parametrize("old_state", ["pending", "retryable", "failed"])
def test_new_versions_supersede_unsent_states(old_state, database):
    store, _ = database
    identifier = queued(store)
    if old_state != "pending":
        store.claim(identifier, CHAT)
        store.finish(identifier, status=old_state)
    record(store, report(job(salary="$26/hour")))
    assert store.get(identifier)["status"] == "superseded"
    assert store.claim(identifier, CHAT) is None


def test_preview_never_relabels_outbox_but_stale_version_cannot_be_claimed(database):
    store, _ = database
    identifier = queued(store)
    before = store.get(identifier)
    plan = record(store, report(job(salary="$26/hour")), preview=True, chat_id=CHAT)
    assert len(plan.messages) == 1
    after = store.get(identifier)
    assert after["status"] == before["status"] == "pending"
    assert after["attempts"] == 0
    assert after["eligible_profiles"] == []
    assert store.claim(identifier, CHAT) is None


def test_exclusion_considers_other_current_profile_matches(database):
    store, _ = database
    identifier = queued(store)
    record(store, report(profile="other"))
    record(store, report(status="excluded"))
    assert store.get(identifier)["eligible_profiles"] == [
        {"profile_id": "other", "fingerprint": "fingerprint-1"}
    ]
    record(store, report(profile="other", status="excluded"))
    assert store.get(identifier)["eligible_profiles"] == []
    assert store.claim(identifier, CHAT) is None


def test_missing_jobs_are_not_marked_closed(database):
    store, _ = database
    identifier = queued(store)
    empty = Report("cafe", "live", "empty")
    record(store, empty)
    assert store.get(identifier)["eligible_profiles"]
    assert store.get(identifier)["status"] == "pending"


def test_stale_sending_recovery_never_steals_fresh_claim(database):
    store, clock = database
    old = queued(store)
    store.claim(old, CHAT)
    clock[0] += timedelta(seconds=301)
    fresh = queued(store, report(job("102")))
    store.claim(fresh, CHAT)
    assert store.recover_stale_sending() == 1
    assert store.get(old)["status"] == "delivery_unknown"
    assert store.get(fresh)["status"] == "sending"
    assert store.get(old)["attempt_history"][0]["error_code"] == "stale_sending"
    assert store.recover_stale_sending() == 0
    with pytest.raises(StoreError):
        store.resolve(fresh, action="skip")


def test_transition_validation_and_sanitized_errors(database):
    store, _ = database
    identifier = queued(store)
    with pytest.raises(StoreError):
        store.finish(identifier, status="sent", message_id=1)
    store.claim(identifier, CHAT)
    with pytest.raises(StoreError):
        store.finish(identifier, status="pending")
    with pytest.raises(StoreError):
        store.finish(identifier, status="sent", message_id=True)
    store.finish(
        identifier, status="failed", error_code="https://api.telegram.org/botSECRET/sendMessage"
    )
    assert store.get(identifier)["error_code"] == "notification_error"
    assert "SECRET" not in json.dumps(store.get(identifier))


def test_transaction_rolls_back_jobs_matches_and_outbox_on_render_failure(database, monkeypatch):
    store, _ = database
    original = store_module.render_notification

    def fail_second(item, assessment, **options):
        if item.source_job_id == "102":
            raise RuntimeError("simulated render failure")
        return original(item, assessment, **options)

    monkeypatch.setattr(store_module, "render_notification", fail_second)
    with pytest.raises(RuntimeError):
        record(store, report(job(), job("102")), enqueue=True, chat_id=CHAT)
    for table in ("jobs", "job_versions", "profile_matches", "outbox"):
        assert store.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_two_connections_cannot_enqueue_or_claim_same_version_twice(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    seed = JobStore(path)
    seed.close()

    def enqueue(profile):
        store = JobStore(path)
        try:
            return record(store, report(profile=profile), enqueue=True, chat_id=CHAT)
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        plans = list(pool.map(enqueue, ("a", "b")))
    assert sum(plan.queued for plan in plans) == 1
    assert sum(plan.deduplicated for plan in plans) == 1
    identifier = next(plan.messages[0].outbox_id for plan in plans if plan.messages)

    def claim(_):
        store = JobStore(path)
        try:
            return store.claim(identifier, CHAT)
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, (1, 2)))
    assert sum(result is not None for result in claims) == 1


def test_outbox_listing_prioritizes_due_work_and_filters_destination(database):
    store, _ = database
    old = queued(store)
    store.claim(old, CHAT)
    store.finish(old, status="sent", message_id=1)
    due = queued(store, report(job("102")))
    queued(store, report(job("103")), chat="-999")
    assert store.list_outbox(chat_id=CHAT, limit=1)[0]["id"] == due
    assert len(store.list_outbox(chat_id=CHAT, limit=10000)) == 2


def test_inconsistent_duplicate_or_missing_assessment_rejects_report(database):
    store, _ = database
    value = report(job(), job(source_job_id="fallback", salary="$26/hour"))
    with pytest.raises(StoreError):
        record(store, value)
    missing = report()
    missing.whv_assessments.clear()
    with pytest.raises(StoreError):
        record(store, missing)
    assert store.connection.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0


def test_foreign_key_and_mode_constraints_are_enforced(database):
    store, _ = database
    identifier = queued(store)
    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("UPDATE outbox SET mode='fixture' WHERE id=?", (identifier,))
    assert store.get(identifier)["mode"] == "live"


def test_reserved_preview_destination_is_only_available_for_preview(database):
    store, _ = database
    plan = record(store, chat_id="preview", preview=True)
    assert plan.messages and store.list_outbox() == []
    with pytest.raises(StoreError):
        record(store, chat_id="preview", enqueue=True)
    with pytest.raises(StoreError):
        record(store, chat_id="preview")


def test_excluded_current_profile_does_not_enqueue_old_other_profile_match(database):
    store, _ = database
    record(store, report(profile="other"))
    result = record(store, report(status="excluded"), chat_id=CHAT, enqueue=True)
    assert result.queued == 0 and result.messages == ()
    assert store.list_outbox() == []


def test_returning_unsent_version_can_reactivate_without_duplicate_row(database):
    store, _ = database
    first = queued(store)
    second = queued(store, report(job(salary="$26/hour")))
    assert store.get(first)["status"] == "superseded"
    before = dict(store.connection.execute("SELECT * FROM outbox WHERE id=?", (first,)).fetchone())
    preview = record(store, preview=True, chat_id=CHAT)
    assert preview.messages[0].outbox_id == first
    assert preview.queued == 0
    assert (
        dict(store.connection.execute("SELECT * FROM outbox WHERE id=?", (first,)).fetchone())
        == before
    )
    restored = record(store, enqueue=True, chat_id=CHAT)
    assert restored.queued == 1 and restored.messages[0].outbox_id == first
    assert store.get(first)["status"] == "pending"
    assert store.get(second)["status"] == "superseded"
    assert len(store.list_outbox()) == 2


@pytest.mark.parametrize("status", ["pending", "retryable"])
def test_preview_existing_pending_message_is_exact_and_does_not_mutate_outbox(database, status):
    store, _ = database
    identifier = queued(store)
    if status == "retryable":
        store.claim(identifier, CHAT)
        store.finish(identifier, status="retryable", retry_after=30)
    before = dict(
        store.connection.execute("SELECT * FROM outbox WHERE id=?", (identifier,)).fetchone()
    )
    altered_display = report(job(title="CAFE ASSISTANT"))
    preview = record(store, altered_display, chat_id=CHAT, preview=True)
    assert preview.messages[0].text == before["text"]
    assert preview.messages[0].outbox_id == identifier
    assert preview.deduplicated == 1
    assert preview.held == int(status == "retryable")
    assert (
        dict(store.connection.execute("SELECT * FROM outbox WHERE id=?", (identifier,)).fetchone())
        == before
    )


@pytest.mark.parametrize("chat", [str(2**52), str(-(2**52))])
def test_destination_matches_telegram_significant_bit_limit(chat):
    with pytest.raises(StoreError):
        canonical_chat_id(chat)
    assert canonical_chat_id("+00123") == "123"


def test_chat_cooldown_blocks_other_jobs_new_records_and_manual_retries(database):
    store, clock = database
    first = queued(store)
    other = queued(store, report(job("102")))
    separate_chat = queued(store, report(job("103")), chat="-123")
    store.claim(first, CHAT, max_attempts=1)
    store.finish(first, status="retryable", error_code="rate_limited", retry_after=60)
    assert store.get(first)["status"] == "failed"
    assert store.claim(other, CHAT) is None
    assert (
        store.get(other)["destination_not_before"] == (clock[0] + timedelta(seconds=60)).isoformat()
    )
    third = queued(store, report(job("104")))
    assert store.claim(third, CHAT) is None
    store.resolve(first, action="retry")
    assert store.claim(first, CHAT) is None
    assert store.claim(separate_chat, "-123") is not None
    clock[0] += timedelta(seconds=60)
    assert store.claim(other, CHAT) is not None


def test_chat_cooldown_survives_reopening_and_supports_telegram_seven_days(tmp_path):
    path = tmp_path / "cooldown.sqlite3"
    now = datetime(2026, 9, 23, tzinfo=UTC)
    store = JobStore(path, now=lambda: now)
    first = queued(store)
    other = queued(store, report(job("102")))
    store.claim(first, CHAT)
    store.finish(first, status="retryable", error_code="rate_limited", retry_after=604800)
    store.close()
    reopened = JobStore(path, now=lambda: now + timedelta(days=1))
    assert reopened.claim(other, CHAT) is None
    assert reopened.get(other)["destination_not_before"] == (now + timedelta(days=7)).isoformat()
    reopened.close()


@pytest.mark.parametrize("status", ["pending", "retryable"])
def test_new_rules_audit_refreshes_unsent_message_without_new_version_or_retry_reset(
    database, status
):
    store, clock = database
    old = report()
    old.whv_assessments["101"] = replace(old.whv_assessments["101"], rules_checked_at="2026-08-01")
    identifier = queued(store, old)
    if status == "retryable":
        store.claim(identifier, CHAT)
        store.finish(identifier, status="retryable", error_code="rate_limited", retry_after=60)
    before = dict(
        store.connection.execute("SELECT * FROM outbox WHERE id=?", (identifier,)).fetchone()
    )
    current = report()
    preview = record(store, current, preview=True, chat_id=CHAT)
    assert "2026-09-23" in preview.messages[0].text
    assert (
        dict(store.connection.execute("SELECT * FROM outbox WHERE id=?", (identifier,)).fetchone())
        == before
    )
    clock[0] += timedelta(seconds=1)
    updated = record(store, current, enqueue=True, chat_id=CHAT)
    assert updated.queued == updated.changed_jobs == 0
    assert updated.deduplicated == 1
    after = store.get(identifier)
    assert after["rules_checked_at"] == "2026-09-23"
    assert after["text"] == preview.messages[0].text
    for key in ("attempts", "max_attempts", "budget_generation", "next_attempt_at", "status"):
        assert after[key] == before[key]
    assert store.connection.execute("SELECT count(*) FROM job_versions").fetchone()[0] == 1


@pytest.mark.parametrize("status", ["sent", "delivery_unknown", "failed", "dismissed"])
def test_rules_recheck_never_refreshes_terminal_or_uncertain_message(database, status):
    store, _ = database
    old = report()
    old.whv_assessments["101"] = replace(old.whv_assessments["101"], rules_checked_at="2026-08-01")
    identifier = queued(store, old)
    store.claim(identifier, CHAT)
    if status == "sent":
        store.finish(identifier, status="sent", message_id=17)
    else:
        store.finish(identifier, status="delivery_unknown" if status == "dismissed" else status)
        if status == "dismissed":
            store.resolve(identifier, action="skip")
    before = dict(
        store.connection.execute("SELECT * FROM outbox WHERE id=?", (identifier,)).fetchone()
    )
    record(store, enqueue=True, chat_id=CHAT)
    after = dict(
        store.connection.execute("SELECT * FROM outbox WHERE id=?", (identifier,)).fetchone()
    )
    assert after == before
