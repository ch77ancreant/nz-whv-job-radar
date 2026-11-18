"""The local spend guard is conservative even after rejected or failed starts."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from nz_job_radar.apify import RunInfo
from nz_job_radar.journal import Journal, JournalError


@pytest.fixture
def journal(tmp_path: Path) -> Iterator[Journal]:
    instance = Journal(tmp_path / "isolated-runs.sqlite3")
    try:
        yield instance
    finally:
        instance.close()


def succeeded_run(run_id: str = "SyntheticRun", usage: str = "0.012") -> RunInfo:
    return RunInfo(
        id=run_id,
        status="SUCCEEDED",
        dataset_id="SyntheticDataset",
        usage_usd=Decimal(usage),
        started_at="2026-09-23T00:00:00Z",
        finished_at="2026-09-23T00:00:10Z",
        charged_item_count=1,
    )


def test_reservation_persists_before_external_call(journal: Journal) -> None:
    attempt = journal.reserve("cafe", "profile-fingerprint", Decimal("0.05"), Decimal("0.50"))
    saved = journal.get(attempt.id)
    assert saved.mode == "live"
    assert saved.state == "STARTING"
    assert saved.run_id is None
    assert saved.reserved_usd == Decimal("0.05")
    assert saved.fingerprint == "profile-fingerprint"


@pytest.mark.parametrize(
    "state", ["STARTING", "START_UNKNOWN", "RUNNING", "WAIT_TIMEOUT", "READ_FAILED", "PARTIAL"]
)
def test_unresolved_same_profile_blocks_another_start(journal: Journal, state: str) -> None:
    attempt = journal.reserve("cafe", "original", Decimal("0.05"), Decimal("0.50"))
    journal.state(attempt.id, state)
    with pytest.raises(JournalError, match="未解決"):
        journal.reserve("cafe", "changed", Decimal("0.05"), Decimal("0.50"))
    assert len(journal.list_runs()) == 1
    # A rejected transaction must not leave the connection in a transaction.
    other = journal.reserve("ski", "other", Decimal("0.05"), Decimal("0.50"))
    assert other.profile_id == "ski"


@pytest.mark.parametrize("state", ["COMPLETE", "REMOTE_FAILED", "START_REJECTED"])
def test_terminal_attempt_allows_same_profile_if_budget_remains(
    journal: Journal, state: str
) -> None:
    original = journal.reserve("cafe", "one", Decimal("0.05"), Decimal("0.50"))
    journal.state(original.id, state)
    next_attempt = journal.reserve("cafe", "two", Decimal("0.05"), Decimal("0.50"))
    assert next_attempt.id != original.id


@pytest.mark.parametrize("state", ["REMOTE_FAILED", "START_REJECTED", "COMPLETE"])
def test_failed_rejected_or_completed_attempt_does_not_refund_reservation(
    journal: Journal, state: str
) -> None:
    attempt = journal.reserve("cafe", "one", Decimal("0.05"), Decimal("0.05"))
    journal.state(attempt.id, state)
    with pytest.raises(JournalError, match="日預算"):
        journal.reserve("cafe", "two", Decimal("0.01"), Decimal("0.05"))
    assert journal.get(attempt.id).reserved_usd == Decimal("0.05")


def test_daily_budget_is_shared_across_profiles(journal: Journal) -> None:
    journal.reserve("cafe", "one", Decimal("0.03"), Decimal("0.05"))
    journal.reserve("ski", "two", Decimal("0.02"), Decimal("0.05"))
    with pytest.raises(JournalError, match="日預算"):
        journal.reserve("third", "three", Decimal("0.01"), Decimal("0.05"))
    assert len(journal.list_runs()) == 2


def test_recorded_usage_above_reservation_counts_toward_budget(journal: Journal) -> None:
    attempt = journal.reserve("cafe", "one", Decimal("0.05"), Decimal("0.10"))
    journal.observe(attempt.id, succeeded_run(usage="0.08"))
    journal.finish(attempt.id, {"fetched": 1}, complete=True)
    with pytest.raises(JournalError, match="日預算"):
        journal.reserve("ski", "two", Decimal("0.03"), Decimal("0.10"))
    journal.reserve("ski", "two", Decimal("0.02"), Decimal("0.10"))


def test_lower_observed_usage_does_not_release_reserved_budget(journal: Journal) -> None:
    attempt = journal.reserve("cafe", "one", Decimal("0.05"), Decimal("0.05"))
    journal.observe(attempt.id, succeeded_run(usage="0.012"))
    journal.finish(attempt.id, {"fetched": 1}, complete=True)
    with pytest.raises(JournalError, match="日預算"):
        journal.reserve("ski", "two", Decimal("0.01"), Decimal("0.05"))


def test_lower_later_usage_cannot_release_previously_observed_spend(journal: Journal) -> None:
    attempt = journal.reserve("cafe", "one", Decimal("0.05"), Decimal("0.10"))
    journal.observe(attempt.id, succeeded_run(usage="0.09"))
    journal.observe(attempt.id, succeeded_run(usage="0.01"))
    journal.finish(attempt.id, {"fetched": 1}, complete=True)
    assert journal.list_runs()[0]["usage_usd"] == "0.09"
    with pytest.raises(JournalError, match="日預算"):
        journal.reserve("ski", "two", Decimal("0.05"), Decimal("0.10"))
    assert len(journal.list_runs()) == 1


@pytest.mark.parametrize(
    "earlier,later,expected",
    [
        ("9", "10", "10"),
        ("10", "9", "10"),
        ("0.010000000000000001", "0.010000000000000000", "0.010000000000000001"),
    ],
)
def test_observed_usage_compares_exact_decimals(
    journal: Journal, earlier: str, later: str, expected: str
) -> None:
    attempt = journal.reserve("cafe", "one", Decimal("0.05"), Decimal("0.10"))
    journal.observe(attempt.id, succeeded_run(usage=earlier))
    journal.observe(attempt.id, succeeded_run(usage=later))
    assert Decimal(journal.list_runs()[0]["usage_usd"]) == Decimal(expected)


def test_missing_usage_stays_unknown_or_preserves_prior_observation(journal: Journal) -> None:
    attempt = journal.reserve("cafe", "one", Decimal("0.05"), Decimal("0.10"))
    unknown = replace(succeeded_run(), usage_usd=None)
    journal.observe(attempt.id, unknown)
    assert journal.list_runs()[0]["usage_usd"] is None
    journal.observe(attempt.id, succeeded_run(usage="0.09"))
    journal.observe(attempt.id, unknown)
    assert journal.list_runs()[0]["usage_usd"] == "0.09"


def test_concurrent_observations_preserve_usage_high_water_after_reopen(tmp_path: Path) -> None:
    path = tmp_path / "cost-high-water.sqlite3"
    initial = Journal(path)
    attempt = initial.reserve("cafe", "one", Decimal("0.05"), Decimal("0.10"))
    initial.close()

    def observe(usage: str) -> None:
        observer = Journal(path)
        try:
            observer.observe(attempt.id, succeeded_run(usage=usage))
        finally:
            observer.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(observe, ("0.09", "0.01")))
    reopened = Journal(path)
    try:
        assert reopened.list_runs()[0]["usage_usd"] == "0.09"
        with pytest.raises(JournalError):
            reopened.observe("missing", succeeded_run())
        assert not reopened.connection.in_transaction
    finally:
        reopened.close()


def test_fixture_does_not_spend_live_budget_or_block_same_profile(journal: Journal) -> None:
    fixture = journal.fixture("cafe", "fixture-one")
    assert fixture.mode == "fixture"
    assert fixture.reserved_usd == Decimal("0")
    # Even an unfinished fixture cannot prevent a live attempt.
    live = journal.reserve("cafe", "live-one", Decimal("0.05"), Decimal("0.05"))
    another_fixture = journal.fixture("cafe", "fixture-two")
    journal.finish(another_fixture.id, {"fetched": 0}, complete=True)
    assert journal.get(live.id).state == "STARTING"
    assert len(journal.list_runs()) == 3


def test_run_mapping_survives_close_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "resume.sqlite3"
    first = Journal(path)
    try:
        attempt = first.reserve("cafe", "fingerprint", Decimal("0.05"), Decimal("0.50"))
        first.observe(attempt.id, succeeded_run())
        first.state(attempt.id, "READ_FAILED", "transport_error")
    finally:
        first.close()
    reopened = Journal(path)
    try:
        found = reopened.by_run("SyntheticRun")
        assert found.id == attempt.id
        assert found.dataset_id == "SyntheticDataset"
        assert found.state == "READ_FAILED"
        assert found.fingerprint == "fingerprint"
        rows = reopened.list_runs()
        assert rows[0]["usage_usd"] == "0.012"
        assert rows[0]["emitted_items"] == 1
        assert rows[0]["error_code"] == "transport_error"
    finally:
        reopened.close()


def test_partial_and_complete_are_distinct(journal: Journal) -> None:
    attempt = journal.fixture("cafe", "fingerprint")
    journal.finish(attempt.id, {"dataset_complete": False}, complete=False)
    assert journal.get(attempt.id).state == "PARTIAL"
    journal.finish(attempt.id, {"dataset_complete": True}, complete=True)
    assert journal.get(attempt.id).state == "COMPLETE"


def test_successful_resume_clears_previous_error(journal: Journal) -> None:
    attempt = journal.reserve("cafe", "one", Decimal("0.05"), Decimal("0.50"))
    journal.state(attempt.id, "READ_FAILED", "transport_error")
    journal.observe(attempt.id, succeeded_run())
    journal.finish(
        attempt.id, {"fetched": 1, "dataset_complete": True, "error_code": None}, complete=True
    )
    row = journal.list_runs()[0]
    assert row["state"] == "COMPLETE"
    assert row["error_code"] is None
    assert row["summary"]["error_code"] is None


def test_partial_download_saves_current_error(journal: Journal) -> None:
    attempt = journal.reserve("cafe", "one", Decimal("0.05"), Decimal("0.50"))
    journal.state(attempt.id, "READ_FAILED", "previous_error")
    summary = {
        "fetched": 100,
        "matched": 60,
        "excluded": 40,
        "dataset_complete": False,
        "error_code": "pagination_incomplete",
        "search_limits": {"max_results": 100, "max_pages": 2},
    }
    journal.finish(attempt.id, summary, complete=False)
    row = journal.list_runs()[0]
    assert row["state"] == "PARTIAL"
    assert row["error_code"] == "pagination_incomplete"
    assert row["summary"] == summary
    assert "summary_json" not in row


def test_unfinished_run_has_no_summary(journal: Journal) -> None:
    journal.reserve("cafe", "one", Decimal("0.05"), Decimal("0.50"))
    assert journal.list_runs()[0]["summary"] is None


def test_summary_omits_raw_jobs_and_unexpected_fields(journal: Journal) -> None:
    attempt = journal.fixture("cafe", "one")
    journal.finish(
        attempt.id,
        {
            "fetched": 1,
            "matched": 1,
            "jobs": [{"description": "private-job-content"}],
            "token": "synthetic-secret-must-not-store",
        },
        complete=True,
    )
    row = journal.list_runs()[0]
    assert row["summary"] == {"fetched": 1, "matched": 1}
    raw = journal.connection.execute(
        "SELECT summary_json FROM runs WHERE id=?", (attempt.id,)
    ).fetchone()[0]
    assert "private-job-content" not in raw
    assert "synthetic-secret-must-not-store" not in raw


@pytest.mark.parametrize("raw_summary", ["invalid-json-secret", "[1, 2]", "null"])
def test_corrupt_summary_has_safe_error(journal: Journal, raw_summary: str) -> None:
    attempt = journal.fixture("cafe", "one")
    with journal.connection:
        journal.connection.execute(
            "UPDATE runs SET summary_json=? WHERE id=?", (raw_summary, attempt.id)
        )
    with pytest.raises(JournalError) as error:
        journal.list_runs()
    assert raw_summary not in str(error.value)


def test_budget_uses_utc_start_day(journal: Journal, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Journal, "_time", staticmethod(lambda: "2026-09-23T23:59:59+00:00"))
    first = journal.reserve("cafe", "one", Decimal("0.05"), Decimal("0.05"))
    journal.state(first.id, "COMPLETE")
    monkeypatch.setattr(Journal, "_time", staticmethod(lambda: "2026-09-24T00:00:01+00:00"))
    second = journal.reserve("cafe", "two", Decimal("0.05"), Decimal("0.05"))
    assert second.id != first.id


def test_two_connections_share_unresolved_start_guard(tmp_path: Path) -> None:
    path = tmp_path / "shared.sqlite3"
    first = Journal(path)
    second = Journal(path)
    try:
        first.reserve("cafe", "one", Decimal("0.05"), Decimal("0.50"))
        with pytest.raises(JournalError, match="未解決"):
            second.reserve("cafe", "two", Decimal("0.05"), Decimal("0.50"))
        assert len(second.list_runs()) == 1
    finally:
        first.close()
        second.close()


def test_unknown_identifiers_are_rejected(journal: Journal) -> None:
    with pytest.raises(JournalError):
        journal.get("nonexistent-attempt")
    with pytest.raises(JournalError, match="--attempt-id"):
        journal.by_run("NonexistentRun")
