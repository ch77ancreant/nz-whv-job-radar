"""CLI persistence and notification integration without real secrets or network."""

import json
import sqlite3
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from nz_job_radar import cli, delivery, pipeline
from nz_job_radar.apify import RunInfo
from nz_job_radar.journal import Journal
from nz_job_radar.pipeline import Report, fingerprint, process_items, read_fixture
from nz_job_radar.profiles import load_profiles
from nz_job_radar.settings import LiveSettings
from nz_job_radar.telegram import TelegramError

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles"
FIXTURE = ROOT / "tests/fixtures/phase2/seek-synthetic.json"
CAFE = "auckland-cafe-service"
SKI = "nz-ski-fields"
CHAT_ID = "-1001234567890"
CAFE_NOTICE_IDS = {
    "991000001",
    "991000005",
    "991000006",
    "991000007",
    "991000008",
    "991000009",
    "991000010",
}


class FixtureDate(date):
    @classmethod
    def today(cls) -> "FixtureDate":
        return cls(2026, 9, 23)


class FixtureDateTime(datetime):
    @classmethod
    def now(cls, tz=None) -> "FixtureDateTime":
        return cls(2026, 9, 23, 12, 0, tzinfo=tz)


@pytest.fixture(autouse=True)
def offline_guards(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("This integration test must not load real settings or create network clients")

    for name in ("load_live_settings", "load_telegram_settings", "ApifyClient", "TelegramClient"):
        monkeypatch.setattr(cli, name, forbidden, raising=False)
    monkeypatch.setattr(pipeline, "date", FixtureDate)
    monkeypatch.setattr(delivery, "datetime", FixtureDateTime)
    monkeypatch.setattr(delivery.time, "sleep", lambda _: None)
    monkeypatch.chdir(tmp_path)


def run_args(
    tmp_path: Path,
    profile_id: str = CAFE,
    *,
    fixture: Path = FIXTURE,
    output: str = "json",
) -> list[str]:
    return [
        "run",
        "--profiles-dir",
        str(PROFILES),
        "--profile",
        profile_id,
        "--fixture",
        str(fixture),
        "--state-dir",
        str(tmp_path / "state"),
        "--format",
        output,
    ]


def invoke_json(args: list[str], capsys, *, exit_code: int = 0):
    assert cli.main(args) == exit_code
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def outbox_args(tmp_path: Path) -> list[str]:
    return ["outbox", "--state-dir", str(tmp_path / "state"), "--format", "json"]


def job_count(tmp_path: Path) -> int:
    with sqlite3.connect(tmp_path / "state/runs.sqlite3") as connection:
        return connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


def write_single_fixture(tmp_path: Path) -> tuple[Path, dict]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["items"] = payload["items"][:1]
    path = tmp_path / "single-synthetic.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, payload


def install_live_mocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    items: list[dict[str, object]] | None = None,
):
    """Keep real collection processing/storage/dispatch while replacing remote boundaries."""
    items = read_fixture(FIXTURE)[:1] if items is None else items
    state = SimpleNamespace(calls=[], outcomes=[], runs=0, client_closed=0)
    settings = LiveSettings("synthetic-apify-token", Decimal("0.05"), Decimal("0.50"), 120)
    telegram_settings = SimpleNamespace(
        token="123456789:synthetic_telegram_token_for_tests", chat_id=CHAT_ID
    )
    monkeypatch.setattr(cli, "load_live_settings", lambda _: settings)
    monkeypatch.setattr(cli, "load_telegram_settings", lambda _: telegram_settings)

    class NoApifyCalls:
        def __init__(self, token):
            assert token == settings.token

        def close(self):
            pass

    def collect_without_upstream(profile, live_settings, journal, client, **kwargs):
        state.runs += 1
        attempt = journal.reserve(
            profile.id,
            fingerprint(profile),
            live_settings.max_charge_usd,
            live_settings.daily_budget_usd,
        )
        run = RunInfo(
            f"SyntheticRun{state.runs}",
            "SUCCEEDED",
            "SyntheticDataset",
            Decimal("0"),
            None,
            None,
            len(items),
        )
        journal.observe(attempt.id, run)
        report = Report(
            profile.id,
            "live",
            attempt.id,
            run_id=run.id,
            dataset_id=run.dataset_id,
            usage_usd="0",
            assessed_at="2026-09-23",
        )
        process_items(report, items, profile)
        journal.finish(attempt.id, report.summary(), complete=True)
        return report

    class FakeTelegramClient:
        def __init__(self, token):
            assert token == telegram_settings.token

        def send(self, chat_id, text):
            assert chat_id == CHAT_ID
            assert job_count(tmp_path) == len(items)
            with sqlite3.connect(tmp_path / "state/runs.sqlite3") as connection:
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM outbox WHERE text=? AND status='sending'", (text,)
                    ).fetchone()[0]
                    == 1
                )
            state.calls.append((chat_id, text))
            outcome = state.outcomes.pop(0) if state.outcomes else 1000 + len(state.calls)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        def close(self):
            state.client_closed += 1

    monkeypatch.setattr(cli, "ApifyClient", NoApifyCalls)
    monkeypatch.setattr(cli, "collect_live", collect_without_upstream)
    monkeypatch.setattr(cli, "TelegramClient", FakeTelegramClient)
    return state


def live_args(tmp_path: Path, profile_id: str = CAFE) -> list[str]:
    args = run_args(tmp_path, profile_id)
    offset = args.index("--fixture")
    args[offset : offset + 2] = ["--live"]
    return args + ["--notify"]


def deliver_args(tmp_path: Path, outbox_id: str) -> list[str]:
    return [
        "deliver",
        "--send",
        "--profiles-dir",
        str(PROFILES),
        "--state-dir",
        str(tmp_path / "state"),
        "--outbox-id",
        outbox_id,
        "--format",
        "json",
    ]


def resolve_args(tmp_path: Path, outbox_id: str, action: str) -> list[str]:
    return [
        "resolve-notification",
        "--state-dir",
        str(tmp_path / "state"),
        "--id",
        outbox_id,
        "--action",
        action,
        "--format",
        "json",
    ]


def test_fixture_default_persists_all_jobs_without_telegram_or_live_settings(
    tmp_path: Path, capsys
) -> None:
    payload = invoke_json(run_args(tmp_path), capsys)
    notices = payload["notifications"]
    assert notices["mode"] == "not_requested"
    assert notices["persisted"] == 12
    assert notices["new_jobs"] == 12
    assert notices["changed_jobs"] == 0
    assert notices["queued"] == 0
    assert notices["messages"] == []
    assert payload["summary"]["telegram"] == "not_requested"
    assert payload["summary"]["persistence"] == {
        "persisted": 12,
        "new_jobs": 12,
        "changed_jobs": 0,
    }
    assert len(payload["jobs"]) == 10
    assert {
        job["source_job_id"] for job in payload["jobs"] if not job["notification_eligible"]
    } == {
        "991000002",
        "991000003",
        "991000004",
    }
    assert job_count(tmp_path) == 12
    assert invoke_json(outbox_args(tmp_path), capsys) == []


def test_identical_rerun_keeps_one_job_and_version_without_queueing(tmp_path: Path, capsys) -> None:
    first = invoke_json(run_args(tmp_path), capsys)
    second = invoke_json(run_args(tmp_path), capsys)
    assert first["notifications"]["new_jobs"] == 12
    assert second["notifications"]["new_jobs"] == 0
    assert second["notifications"]["changed_jobs"] == 0
    assert job_count(tmp_path) == 12
    with sqlite3.connect(tmp_path / "state/runs.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM job_versions").fetchone()[0] == 12
    assert invoke_json(outbox_args(tmp_path), capsys) == []


def test_relevance_profiles_reuse_jobs_and_keep_separate_results(tmp_path: Path, capsys) -> None:
    cafe = invoke_json(run_args(tmp_path, CAFE), capsys)
    ski = invoke_json(run_args(tmp_path, SKI), capsys)
    assert cafe["summary"]["matched"] == 10
    assert ski["summary"]["matched"] == 2
    assert ski["notifications"]["new_jobs"] == 0
    assert ski["notifications"]["changed_jobs"] == 0
    assert job_count(tmp_path) == 12
    assert invoke_json(outbox_args(tmp_path), capsys) == []


@pytest.mark.parametrize("chat_args", [[], ["--chat-id", CHAT_ID]])
def test_dry_run_repeats_the_same_preview_without_creating_outbox(
    tmp_path: Path, capsys, chat_args: list[str]
) -> None:
    args = run_args(tmp_path) + ["--dry-run"] + chat_args
    first = invoke_json(args, capsys)
    assert invoke_json(outbox_args(tmp_path), capsys) == []
    second = invoke_json(args, capsys)
    assert invoke_json(outbox_args(tmp_path), capsys) == []
    for payload in (first, second):
        assert payload["summary"]["telegram"] == "dry_run"
        assert payload["notifications"]["mode"] == "dry_run"
        assert payload["notifications"]["queued"] == 0
        messages = payload["notifications"]["messages"]
        assert {notice["job_id"] for notice in messages} == CAFE_NOTICE_IDS
        assert all(notice["outbox_id"] is None for notice in messages)
        assert all(notice["text"] and "僅供初步篩選" in notice["text"] for notice in messages)
    assert first["notifications"]["messages"] == second["notifications"]["messages"]
    assert second["notifications"]["new_jobs"] == 0
    assert second["notifications"]["changed_jobs"] == 0
    assert job_count(tmp_path) == 12


def test_dry_run_ignores_explicit_env_path_and_preserves_red_jobs(tmp_path: Path, capsys) -> None:
    path = tmp_path / "must-not-be-read.env"
    args = run_args(tmp_path) + ["--dry-run", "--env-file", str(path)]
    payload = invoke_json(args, capsys)
    assert len(payload["jobs"]) == 10
    assert len(payload["notifications"]["messages"]) == 7
    assert "991000002" not in {notice["job_id"] for notice in payload["notifications"]["messages"]}
    assert not path.exists()


def test_fixture_notify_rejected_before_settings_or_local_files(tmp_path: Path, capsys) -> None:
    args = run_args(tmp_path, fixture=tmp_path / "nonexistent-fixture.json") + ["--notify"]
    assert cli.main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err
    assert not (tmp_path / "state").exists()


def test_dry_run_and_notify_are_mutually_exclusive(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(run_args(tmp_path) + ["--dry-run", "--notify"])
    assert caught.value.code == 2
    assert "--dry-run" in capsys.readouterr().err
    assert not (tmp_path / "state").exists()


def test_important_change_updates_version_but_formatting_and_listing_time_do_not(
    tmp_path: Path, capsys
) -> None:
    fixture, data = write_single_fixture(tmp_path)
    first = invoke_json(run_args(tmp_path, fixture=fixture), capsys)
    assert first["notifications"]["new_jobs"] == 1
    data["items"][0]["title"] = "  Cafe   Assistant  "
    data["items"][0]["postedDate"] = "2026-09-22T10:00:00Z"
    fixture.write_text(json.dumps(data), encoding="utf-8")
    same = invoke_json(run_args(tmp_path, fixture=fixture), capsys)
    assert same["notifications"]["new_jobs"] == 0
    assert same["notifications"]["changed_jobs"] == 0
    data["items"][0]["salaryText"] = "$30 per hour"
    fixture.write_text(json.dumps(data), encoding="utf-8")
    changed = invoke_json(run_args(tmp_path, fixture=fixture), capsys)
    assert changed["notifications"]["new_jobs"] == 0
    assert changed["notifications"]["changed_jobs"] == 1
    assert job_count(tmp_path) == 1
    with sqlite3.connect(tmp_path / "state/runs.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM job_versions").fetchone()[0] == 2


def test_additive_store_keeps_old_run_summary_unchanged(tmp_path: Path, capsys) -> None:
    journal = Journal(tmp_path / "state/runs.sqlite3")
    legacy_summary = {"matched": 4, "whv": "not_implemented_phase_2"}
    try:
        attempt = journal.fixture("legacy-profile", "legacy-fingerprint")
        journal.finish(attempt.id, legacy_summary, complete=True)
    finally:
        journal.close()
    invoke_json(run_args(tmp_path), capsys)
    rows = invoke_json(["runs", "--state-dir", str(tmp_path / "state"), "--format", "json"], capsys)
    legacy = next(row for row in rows if row["id"] == attempt.id)
    assert legacy["summary"] == legacy_summary
    assert legacy["profile_id"] == "legacy-profile"
    assert legacy["state"] == "COMPLETE"
    assert len(rows) == 2
    assert job_count(tmp_path) == 12


def test_label_configuration_changes_preview_without_deleting_jobs(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    profiles = load_profiles(PROFILES)
    profiles[CAFE] = replace(profiles[CAFE], notification_labels=("likely_suitable",))
    monkeypatch.setattr(cli, "load_profiles", lambda _: profiles)
    payload = invoke_json(run_args(tmp_path) + ["--dry-run"], capsys)
    assert len(payload["jobs"]) == 10
    assert {notice["job_id"] for notice in payload["notifications"]["messages"]} == {
        "991000001",
        "991000010",
    }
    assert job_count(tmp_path) == 12
    assert invoke_json(outbox_args(tmp_path), capsys) == []


def test_live_notify_commits_before_send_and_deduplicates_rerun_and_other_profile(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = install_live_mocks(tmp_path, monkeypatch)
    profiles = load_profiles(PROFILES)
    alias = replace(profiles[CAFE], id="another-cafe-profile", name="Another Cafe Profile")
    profiles[alias.id] = alias
    monkeypatch.setattr(cli, "load_profiles", lambda _: profiles)
    first = invoke_json(live_args(tmp_path), capsys)
    assert first["notifications"]["mode"] == "send"
    assert first["notifications"]["queued"] == 1
    assert first["notifications"]["delivery"]["sent"] == 1
    assert first["summary"]["telegram"] == "send"
    assert len(state.calls) == 1
    for profile_id in (CAFE, alias.id):
        replay = invoke_json(live_args(tmp_path, profile_id), capsys)
        assert replay["notifications"]["queued"] == 0
        assert replay["notifications"]["deduplicated"] == 1
        assert replay["notifications"]["delivery"]["sent"] == 0
        assert replay["notifications"]["new_jobs"] == 0
        assert len(state.calls) == 1
    rows = invoke_json(outbox_args(tmp_path), capsys)
    assert len(rows) == 1
    assert rows[0]["status"] == "sent"
    assert rows[0]["text"] == state.calls[0][1]
    assert "synthetic_telegram_token" not in json.dumps(rows)
    assert job_count(tmp_path) == 1


@pytest.mark.parametrize("outcome", ["failed", "retryable", "delivery_unknown"])
def test_unsuccessful_send_retains_job_version_and_recovery_record(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    state = install_live_mocks(tmp_path, monkeypatch)
    state.outcomes.append(
        TelegramError(
            "synthetic_failure",
            "Synthetic test failure",
            outcome=outcome,
            retry_after=0 if outcome == "retryable" else None,
        )
    )
    payload = invoke_json(live_args(tmp_path), capsys, exit_code=2)
    assert payload["notifications"]["delivery"][outcome] == 1
    assert payload["notifications"]["delivery"]["sent"] == 0
    assert payload["notifications"]["persisted"] == 1
    assert payload["jobs"][0]["source_job_id"] == "991000001"
    assert len(state.calls) == 1
    rows = invoke_json(outbox_args(tmp_path), capsys)
    assert len(rows) == 1
    assert rows[0]["status"] == outcome
    assert rows[0]["text"] == state.calls[0][1]
    assert job_count(tmp_path) == 1
    with sqlite3.connect(tmp_path / "state/runs.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM job_versions").fetchone()[0] == 1


def test_dry_run_does_not_consume_existing_retryable_outbox(tmp_path: Path, capsys, monkeypatch):
    state = install_live_mocks(tmp_path, monkeypatch)
    state.outcomes.append(
        TelegramError("rate_limited", "Synthetic limit", outcome="retryable", retry_after=0)
    )
    invoke_json(live_args(tmp_path), capsys, exit_code=2)
    before = invoke_json(outbox_args(tmp_path), capsys)
    args = live_args(tmp_path)
    args[args.index("--notify")] = "--dry-run"
    args += ["--chat-id", CHAT_ID]
    invoke_json(args, capsys)
    after = invoke_json(outbox_args(tmp_path), capsys)
    assert before == after
    assert len(state.calls) == 1
    assert after[0]["status"] == "retryable"


def test_deliver_retries_only_existing_outbox_without_upstream_collection(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = install_live_mocks(tmp_path, monkeypatch)
    state.outcomes.append(
        TelegramError("rate_limited", "Synthetic limit", outcome="retryable", retry_after=0)
    )
    invoke_json(live_args(tmp_path), capsys, exit_code=2)
    row = invoke_json(outbox_args(tmp_path), capsys)[0]

    def no_upstream(*args, **kwargs):
        pytest.fail("deliver must not load Apify settings or collect another dataset")

    monkeypatch.setattr(cli, "load_live_settings", no_upstream)
    monkeypatch.setattr(cli, "collect_live", no_upstream)
    monkeypatch.setattr(cli, "ApifyClient", no_upstream)
    result = invoke_json(deliver_args(tmp_path, row["id"]), capsys)
    assert result["sent"] == 1
    assert result["remaining"] == 0
    assert len(state.calls) == 2
    assert state.runs == 1
    rows = invoke_json(outbox_args(tmp_path), capsys)
    assert len(rows) == 1
    assert rows[0]["status"] == "sent"
    assert rows[0]["attempts"] == 2
    assert job_count(tmp_path) == 1


def test_delivery_unknown_is_not_retried_without_explicit_duplicate_risk_acknowledgement(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = install_live_mocks(tmp_path, monkeypatch)
    state.outcomes.append(
        TelegramError("delivery_unknown", "Synthetic lost response", outcome="delivery_unknown")
    )
    invoke_json(live_args(tmp_path), capsys, exit_code=2)
    row = invoke_json(outbox_args(tmp_path), capsys)[0]
    result = invoke_json(deliver_args(tmp_path, row["id"]), capsys, exit_code=2)
    assert result["sent"] == 0
    assert len(state.calls) == 1
    assert cli.main(resolve_args(tmp_path, row["id"], "retry")) == 2
    rejected = capsys.readouterr()
    assert rejected.out == ""
    assert "--acknowledge-duplicate-risk" in rejected.err
    unchanged = invoke_json(outbox_args(tmp_path), capsys)[0]
    assert unchanged["status"] == "delivery_unknown"
    assert unchanged["attempts"] == 1
    resolved = invoke_json(
        resolve_args(tmp_path, row["id"], "retry") + ["--acknowledge-duplicate-risk"], capsys
    )
    assert resolved["status"] in {"pending", "retryable"}
    assert len(state.calls) == 1
    delivered = invoke_json(deliver_args(tmp_path, row["id"]), capsys)
    assert delivered["sent"] == 1
    assert len(state.calls) == 2
    assert state.runs == 1


@pytest.mark.parametrize("action,expected_status", [("sent", "sent"), ("skip", "dismissed")])
def test_manual_resolution_records_decision_without_sending(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch, action: str, expected_status: str
) -> None:
    state = install_live_mocks(tmp_path, monkeypatch)
    state.outcomes.append(
        TelegramError("delivery_unknown", "Synthetic lost response", outcome="delivery_unknown")
    )
    invoke_json(live_args(tmp_path), capsys, exit_code=2)
    row = invoke_json(outbox_args(tmp_path), capsys)[0]

    def no_send(*args, **kwargs):
        pytest.fail("Manual resolution must not load credentials or create Telegram clients")

    monkeypatch.setattr(cli, "load_telegram_settings", no_send)
    monkeypatch.setattr(cli, "TelegramClient", no_send)
    args = resolve_args(tmp_path, row["id"], action)
    if action == "sent":
        args += ["--message-id", "4567"]
    resolved = invoke_json(args, capsys)
    assert resolved["status"] == expected_status
    assert len(state.calls) == 1
    assert job_count(tmp_path) == 1


def test_retry_after_defers_other_pending_messages_for_the_same_chat(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    items = read_fixture(FIXTURE)
    state = install_live_mocks(tmp_path, monkeypatch, items=[items[0], items[9]])
    state.outcomes.append(
        TelegramError("rate_limited", "Synthetic limit", outcome="retryable", retry_after=60)
    )
    first = invoke_json(live_args(tmp_path), capsys, exit_code=2)
    assert first["notifications"]["queued"] == 2
    assert len(state.calls) == 1
    rows = invoke_json(outbox_args(tmp_path), capsys)
    assert {row["status"] for row in rows} == {"pending", "retryable"}
    args = deliver_args(tmp_path, rows[0]["id"])
    offset = args.index("--outbox-id")
    del args[offset : offset + 2]
    result = invoke_json(args, capsys, exit_code=2)
    assert result["sent"] == 0
    assert result["remaining"] == 2
    assert len(state.calls) == 1


def test_changed_profile_configuration_blocks_existing_notification_before_send(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = install_live_mocks(tmp_path, monkeypatch)
    state.outcomes.append(
        TelegramError("rate_limited", "Synthetic limit", outcome="retryable", retry_after=0)
    )
    invoke_json(live_args(tmp_path), capsys, exit_code=2)
    row = invoke_json(outbox_args(tmp_path), capsys)[0]
    profiles = load_profiles(PROFILES)
    profiles[CAFE] = replace(profiles[CAFE], notification_labels=())
    monkeypatch.setattr(cli, "load_profiles", lambda _: profiles)
    result = invoke_json(deliver_args(tmp_path, row["id"]), capsys, exit_code=2)
    assert result["sent"] == 0
    assert result["skipped"] == 1
    assert result["remaining"] == 1
    assert len(state.calls) == 1
    after = invoke_json(outbox_args(tmp_path), capsys)[0]
    assert after["status"] == "retryable"
    assert after["attempts"] == 1


def test_explicit_outbox_id_for_another_destination_fails_before_client_creation(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = install_live_mocks(tmp_path, monkeypatch)
    state.outcomes.append(
        TelegramError("rate_limited", "Synthetic limit", outcome="retryable", retry_after=0)
    )
    invoke_json(live_args(tmp_path), capsys, exit_code=2)
    row = invoke_json(outbox_args(tmp_path), capsys)[0]
    monkeypatch.setattr(
        cli,
        "load_telegram_settings",
        lambda _: SimpleNamespace(
            token="123456789:synthetic_telegram_token_for_tests", chat_id="1234567890"
        ),
    )

    def forbidden(*args, **kwargs):
        pytest.fail("A destination mismatch must be rejected before creating a Telegram client")

    monkeypatch.setattr(cli, "TelegramClient", forbidden)
    assert cli.main(deliver_args(tmp_path, row["id"])) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "目的 Chat" in captured.err
    assert "未發送" in captured.err
    assert len(state.calls) == 1
    after = invoke_json(outbox_args(tmp_path), capsys)[0]
    assert after["status"] == "retryable"
    assert after["attempts"] == 1
