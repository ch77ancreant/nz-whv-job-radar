"""Phase 2 fixture-to-CLI checks with isolated storage and no external calls."""

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from nz_job_radar import cli, pipeline
from nz_job_radar.journal import Journal
from nz_job_radar.pipeline import Report, collect_fixture, process_items, read_fixture
from nz_job_radar.profiles import load_profiles

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles"
FIXTURE = ROOT / "tests/fixtures/phase2/seek-synthetic.json"
CAFE = "auckland-cafe-service"
SKI = "nz-ski-fields"
EXPECTED_LABELS = {
    "991000001": "likely_suitable",
    "991000002": "likely_incompatible",
    "991000003": "likely_incompatible",
    "991000004": "likely_incompatible",
    "991000005": "needs_confirmation",
    "991000006": "needs_confirmation",
    "991000007": "needs_confirmation",
    "991000008": "needs_confirmation",
    "991000009": "needs_confirmation",
    "991000010": "likely_suitable",
    "991000011": "likely_suitable",
    "991000012": "needs_confirmation",
}
ALL_COUNTS = {"likely_suitable": 3, "needs_confirmation": 6, "likely_incompatible": 3}


class FixtureDate(date):
    @classmethod
    def today(cls) -> "FixtureDate":
        return cls(2026, 9, 23)


@pytest.fixture(autouse=True)
def offline_guards(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("Phase 2 fixture integration must not read live settings or create a client")

    monkeypatch.setattr(cli, "load_live_settings", forbidden)
    monkeypatch.setattr(cli, "ApifyClient", forbidden)
    monkeypatch.setattr(pipeline, "date", FixtureDate)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def journal(tmp_path: Path) -> Iterator[Journal]:
    instance = Journal(tmp_path / "phase2.sqlite3")
    try:
        yield instance
    finally:
        instance.close()


def run_args(tmp_path: Path, profile_id: str, output: str = "json") -> list[str]:
    return [
        "run",
        "--profiles-dir",
        str(PROFILES),
        "--profile",
        profile_id,
        "--fixture",
        str(FIXTURE),
        "--state-dir",
        str(tmp_path / "state"),
        "--format",
        output,
    ]


@pytest.mark.parametrize(
    "profile_id,matched,counts,policy",
    [
        (
            CAFE,
            10,
            {"likely_suitable": 2, "needs_confirmation": 5, "likely_incompatible": 3},
            {"eligible": 7, "suppressed": 3},
        ),
        (
            SKI,
            2,
            {"likely_suitable": 1, "needs_confirmation": 1, "likely_incompatible": 0},
            {"eligible": 2, "suppressed": 0},
        ),
    ],
)
def test_fixture_assesses_every_unique_job_but_counts_matched_separately(
    journal: Journal, profile_id: str, matched: int, counts: dict, policy: dict
) -> None:
    profile = load_profiles(PROFILES)[profile_id]
    report = collect_fixture(profile, FIXTURE, journal)
    summary = report.summary()
    assert report.fetched == 12
    assert len(report.matched) == matched
    assert len(report.excluded) == 12 - matched
    assert not report.pending
    assert report.invalid_count == report.duplicate_count == 0
    assert {key: value.label for key, value in report.whv_assessments.items()} == EXPECTED_LABELS
    assert report.whv_assessments["991000010"].score == 70
    assert summary["whv"] == "assessed_phase_2"
    assert summary["whv_counts"] == counts
    assert summary["whv_all_counts"] == ALL_COUNTS
    assert summary["notification_policy"] == policy
    assert summary["telegram"] == "not_requested"
    assert summary["whv_rules"]["assessed_at"] == "2026-09-23"
    assert summary["whv_rules"]["stale"] is False
    assert journal.get(report.attempt_id).state == "COMPLETE"


def test_invalid_and_duplicate_items_do_not_inflate_whv_counts() -> None:
    profile = load_profiles(PROFILES)[CAFE]
    items = read_fixture(FIXTURE)
    report = Report(profile.id, "fixture", "synthetic-attempt", assessed_at="2026-09-23")
    process_items(report, items + [items[0], {}], profile)
    assert report.fetched == 14
    assert report.duplicate_count == 1
    assert report.invalid_count == 1
    assert len(report.whv_assessments) == 12
    assert report.summary()["whv_all_counts"] == ALL_COUNTS
    assert report.summary()["notification_policy"] == {"eligible": 7, "suppressed": 3}


@pytest.mark.parametrize(
    "labels,expected_ids",
    [
        (("likely_suitable",), {"991000001", "991000010"}),
        (("likely_incompatible",), {"991000002", "991000003", "991000004"}),
        ((), set()),
    ],
)
def test_notification_labels_change_only_policy_not_listing_or_assessment(
    journal: Journal, labels: tuple[str, ...], expected_ids: set[str]
) -> None:
    profile = replace(load_profiles(PROFILES)[CAFE], notification_labels=labels)
    report = collect_fixture(profile, FIXTURE, journal)
    payload = cli.report_payload(report, show_excluded=True)
    jobs = {job["source_job_id"]: job for job in payload["jobs"]}
    assert set(jobs) == {f"991000{number:03}" for number in range(1, 11)}
    assert {key for key, job in jobs.items() if job["notification_eligible"]} == expected_ids
    assert {key: value.label for key, value in report.whv_assessments.items()} == EXPECTED_LABELS
    assert report.summary()["notification_policy"] == {
        "eligible": len(expected_ids),
        "suppressed": 10 - len(expected_ids),
    }
    assert all(row["notification_eligible"] is False for row in payload["excluded"])


def test_profile_pending_and_excluded_have_whv_evidence_but_no_notification(
    journal: Journal,
) -> None:
    profile = replace(load_profiles(PROFILES)[CAFE], employers=("Fictional Harbour Cafe",))
    report = collect_fixture(profile, FIXTURE, journal)
    payload = cli.report_payload(report, show_excluded=True)
    assert [job["source_job_id"] for job in payload["jobs"]] == ["991000001"]
    pending = payload["needs_profile_confirmation"]
    assert len(pending) == 1
    assert pending[0]["job"]["source_job_id"] == "991000009"
    assert pending[0]["reasons"] == ["employer_unknown"]
    assert pending[0]["whv"]["label"] == "needs_confirmation"
    for row in payload["excluded"] + pending:
        assert row["whv"]["label"] == EXPECTED_LABELS[row["job"]["source_job_id"]]
        assert row["notification_eligible"] is False
    assert report.summary()["notification_policy"] == {"eligible": 1, "suppressed": 0}
    assert report.summary()["whv_all_counts"] == ALL_COUNTS


def test_cli_json_preserves_red_jobs_and_adds_assessment_to_flat_jobs(
    tmp_path: Path, capsys
) -> None:
    assert cli.main(run_args(tmp_path, CAFE) + ["--show-excluded"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    jobs = {job["source_job_id"]: job for job in payload["jobs"]}
    assert len(jobs) == 10
    for job_id, job in jobs.items():
        assert "job" not in job
        assert job["title"]
        assert job["source_url"] == f"https://nz.seek.com/job/{job_id}"
        assert job["whv"]["label"] == EXPECTED_LABELS[job_id]
        assert job["notification_eligible"] is (EXPECTED_LABELS[job_id] != "likely_incompatible")
        for evidence in job["whv"]["evidence"]:
            source_text = job[evidence["field"]]
            assert isinstance(source_text, str)
            assert evidence["quote"] and evidence["quote"] in source_text
    for job_id in ("991000002", "991000003", "991000004"):
        assert jobs[job_id]["whv"]["evidence"]
    assert len(payload["excluded"]) == 2
    assert all(row["whv"] and not row["notification_eligible"] for row in payload["excluded"])
    assert payload["summary"]["whv_counts"] == {
        "likely_suitable": 2,
        "needs_confirmation": 5,
        "likely_incompatible": 3,
    }
    assert "僅供初步篩選" in payload["disclaimer"]


def test_cli_text_shows_labels_evidence_and_unsent_policy_counts(tmp_path: Path, capsys) -> None:
    assert cli.main(run_args(tmp_path, CAFE, "text")) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    output = captured.out
    for number in range(1, 11):
        assert f"https://nz.seek.com/job/991000{number:03}" in output
    assert "likely_suitable" in output
    assert "needs_confirmation" in output
    assert "likely_incompatible" in output
    assert "permanent position" in output
    assert "2026-01-01" in output
    assert "2026-03-01" in output
    assert "通知政策候選 7 | 政策排除 3" in output
    assert "未建立通知佇列／未發送" in output
    assert "Telegram：not_requested" in output
    assert "僅供初步篩選" in output


def test_sqlite_retains_aggregate_summary_without_jobs_or_individual_evidence(
    journal: Journal,
) -> None:
    profile = load_profiles(PROFILES)[CAFE]
    report = collect_fixture(profile, FIXTURE, journal)
    rows = journal.list_runs()
    assert len(rows) == 1
    assert rows[0]["summary"] == report.summary()
    assert rows[0]["summary"]["whv_all_counts"] == ALL_COUNTS
    assert rows[0]["summary"]["notification_policy"] == {"eligible": 7, "suppressed": 3}
    tables = {
        row[0]
        for row in journal.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert tables == {"runs"}
    raw = journal.connection.execute(
        "SELECT summary_json FROM runs WHERE id=?", (report.attempt_id,)
    ).fetchone()[0]
    for forbidden in (
        "991000001",
        "Fictional Harbour Cafe",
        "Working holiday visa holders welcome.",
        '"jobs"',
        '"evidence"',
        '"description"',
        '"whv_assessments"',
    ):
        assert forbidden not in raw


def test_runs_command_retains_phase2_counts_without_serializing_job_evidence(
    tmp_path: Path, capsys
) -> None:
    assert cli.main(run_args(tmp_path, SKI)) == 0
    run_payload = json.loads(capsys.readouterr().out)
    assert cli.main(["runs", "--state-dir", str(tmp_path / "state"), "--format", "json"]) == 0
    captured = capsys.readouterr()
    rows = json.loads(captured.out)
    assert len(rows) == 1
    assert rows[0]["summary"] == run_payload["summary"]
    assert rows[0]["summary"]["matched"] == 2
    assert rows[0]["summary"]["whv_counts"] == {
        "likely_suitable": 1,
        "needs_confirmation": 1,
        "likely_incompatible": 0,
    }
    assert "991000011" not in captured.out
    assert '"evidence"' not in captured.out
