"""Offline orchestration checks: no paid starts, including simulated live runs."""

import json
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from nz_job_radar.apify import ApifyClient, ApifyError, DatasetPage, RunInfo
from nz_job_radar.journal import Journal, JournalError
from nz_job_radar.pipeline import (
    CollectionError,
    Report,
    collect_fixture,
    collect_live,
    fingerprint,
    process_items,
    read_fixture,
)
from nz_job_radar.profiles import load_profiles
from nz_job_radar.settings import LiveSettings
from nz_job_radar.whv import RULES_CHECKED_AT

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/phase1/seek-synthetic.json"


def run_info(status="SUCCEEDED", dataset_id="DataOne", usage="0.012"):
    return RunInfo("RunOne", status, dataset_id, Decimal(usage), None, None, 1)


def raw_job(number=1):
    return {
        "seekJobId": str(number),
        "canonicalUrl": f"https://nz.seek.com/job/{number}",
        "title": "Cafe Assistant",
        "company": "Fictional Cafe",
        "location": "Auckland",
        "locationCountry": "NZ",
        "description": "Entirely synthetic cafe assistant position.",
    }


class StubClient:
    def __init__(self, start=None, reads=(), pages=()):
        self.start = start or run_info()
        self.reads = list(reads)
        self.pages = list(pages)
        self.starts = 0
        self.read_ids = []
        self.offsets = []

    def start_run(self, actor_input, **kwargs):
        self.starts += 1
        self.actor_input = actor_input
        self.start_options = kwargs
        if isinstance(self.start, BaseException):
            raise self.start
        return self.start

    def get_run(self, run_id):
        self.read_ids.append(run_id)
        value = self.reads.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def get_dataset_page(self, dataset_id, *, offset, limit):
        assert dataset_id == "DataOne"
        assert limit == 100
        self.offsets.append(offset)
        value = self.pages.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


@pytest.fixture
def context(tmp_path):
    profile = load_profiles(ROOT / "profiles")["auckland-cafe-service"]
    journal = Journal(tmp_path / "runs.sqlite3")
    settings = LiveSettings("fake-token", Decimal("0.05"), Decimal("0.50"), 120)
    yield profile, settings, journal
    journal.close()


def collect(context, client, **kwargs):
    profile, settings, journal = context
    return collect_live(
        profile, settings, journal, client, sleep=lambda _: None, progress=lambda _: None, **kwargs
    )


def test_process_items_counts_rejections_invalid_and_duplicate(context):
    profile, _, _ = context
    report = Report(profile.id, "fixture", "local")
    process_items(report, read_fixture(FIXTURE) + [raw_job(), raw_job(), {}], profile)
    assert report.fetched == 11
    assert len(report.matched) == 3
    assert len(report.excluded) == 6
    assert report.invalid_count == 1
    assert report.duplicate_count == 1
    assert "invalid_items_skipped" in report.warnings
    assert report.summary()["whv"] == "assessed_phase_2"


def test_canonical_identity_keeps_distinct_seek_jobs_with_same_actor_id(context):
    profile, _, _ = context
    items = [raw_job(101), raw_job(102)]
    for item in items:
        item.pop("seekJobId")
        item["jobId"] = "same-provider-fallback"
    report = Report(profile.id, "fixture", "canonical-review", assessed_at=RULES_CHECKED_AT)
    process_items(report, items, profile)
    assert report.fetched == 2
    assert report.duplicate_count == 0
    assert {job.source_job_id for job in report.matched} == {"101", "102"}
    assert set(report.whv_assessments) == report.notification_candidates == {"101", "102"}


def test_canonical_identity_merges_keyword_duplicates_and_keeps_maps_aligned(context):
    profile, _, _ = context
    items = [raw_job(101), raw_job(101)]
    for index, item in enumerate(items):
        item.pop("seekJobId")
        item["jobId"] = f"provider-fallback-{index}"
    report = Report(profile.id, "fixture", "canonical-review", assessed_at=RULES_CHECKED_AT)
    process_items(report, items, profile)
    assert report.fetched == 2
    assert report.duplicate_count == 1
    assert [job.source_job_id for job in report.matched] == ["101"]
    assert set(report.whv_assessments) == report.notification_candidates == {"101"}


@pytest.mark.parametrize(
    "profile_id,matched,excluded,pending",
    [("auckland-cafe-service", 2, 6, 0), ("nz-ski-fields", 2, 5, 1)],
)
def test_fixture_flow(context, profile_id, matched, excluded, pending):
    _, _, journal = context
    profile = load_profiles(ROOT / "profiles")[profile_id]
    report = collect_fixture(profile, FIXTURE, journal)
    assert (len(report.matched), len(report.excluded), len(report.pending)) == (
        matched,
        excluded,
        pending,
    )
    assert report.usage_usd == "0"
    assert journal.get(report.attempt_id).state == "COMPLETE"
    assert report.summary()["search_coverage"] == "synthetic"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"items": []},
        {"fixtureKind": "synthetic_phase1_dataset", "items": [None]},
        {"fixtureKind": [], "items": []},
        {"fixtureKind": {}, "items": []},
    ],
)
def test_fixture_rejects_unsafe_or_wrong_format(tmp_path, payload):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CollectionError, match="synthetic"):
        read_fixture(path)


def test_fixture_missing_or_malformed_does_not_reserve(context, tmp_path):
    profile, _, journal = context
    with pytest.raises(CollectionError):
        collect_fixture(profile, tmp_path / "missing.json", journal)
    assert journal.list_runs() == []


def test_simulated_live_http_end_to_end(context):
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["incrementalMode"] is False
            assert isinstance(body["query"], str)
            assert request.url.params["maxTotalChargeUsd"] == "0.05"
            return httpx.Response(201, json={"data": {"id": "RunOne", "status": "RUNNING"}})
        if request.url.path == "/v2/actor-runs/RunOne":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": "RunOne",
                        "status": "SUCCEEDED",
                        "defaultDatasetId": "DataOne",
                        "usageTotalUsd": 0.012,
                        "chargedEventCounts": {"apify-default-dataset-item": 1},
                    }
                },
            )
        assert request.url.path == "/v2/datasets/DataOne/items"
        return httpx.Response(200, json=[raw_job()], headers={"X-Apify-Pagination-Total": "1"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = ApifyClient("fake-token", client=http, request_interval=0)
        report = collect(context, client)
    assert [request.method for request in requests] == ["POST", "GET", "GET"]
    assert report.run_id == "RunOne"
    assert report.dataset_id == "DataOne"
    assert report.usage_usd == "0.012"
    assert report.charged_items == 1
    assert len(report.matched) == 1
    assert context[2].get(report.attempt_id).state == "COMPLETE"


def test_zero_dataset_is_a_real_success(context):
    client = StubClient(pages=[DatasetPage([], 0, 0)])
    report = collect(context, client)
    assert report.fetched == 0
    assert report.dataset_complete
    assert report.error_code is None
    assert context[2].get(report.attempt_id).state == "COMPLETE"


def test_downloads_all_pages_even_above_configured_search_cap(context):
    first = [raw_job(index) for index in range(1, 101)]
    last = [raw_job(101)]
    client = StubClient(pages=[DatasetPage(first, 0, 101), DatasetPage(last, 100, 101)])
    report = collect(context, client)
    assert client.offsets == [0, 100]
    assert report.fetched == 101
    assert len(report.matched) == 101
    assert "search_result_cap_possible" in report.warnings


def test_download_without_total_ends_on_short_page(context):
    first = [raw_job(index) for index in range(1, 101)]
    client = StubClient(pages=[DatasetPage(first, 0, None), DatasetPage([], 100, None)])
    report = collect(context, client)
    assert report.dataset_complete
    assert client.offsets == [0, 100]


@pytest.mark.parametrize(
    "page,code",
    [
        (DatasetPage([], 1, 0), "pagination_invalid"),
        (DatasetPage([], 0, 2), "pagination_incomplete"),
        (DatasetPage([raw_job()], 0, 0), "pagination_invalid"),
    ],
)
def test_bad_pagination_is_partial_not_empty_success(context, page, code):
    report = collect(context, StubClient(pages=[page]))
    assert not report.dataset_complete
    assert report.error_code == code
    assert report.fetched == 0
    row = context[2].list_runs()[0]
    assert row["state"] == "PARTIAL"
    assert row["error_code"] == code


def test_changed_total_preserves_only_verified_page(context):
    first = [raw_job(index) for index in range(1, 101)]
    report = collect(
        context,
        StubClient(pages=[DatasetPage(first, 0, 101), DatasetPage([raw_job(101)], 100, 102)]),
    )
    assert report.fetched == 100
    assert report.error_code == "pagination_changed"
    assert not report.dataset_complete


def test_missing_dataset_records_partial_with_reason(context):
    report = collect(context, StubClient(start=run_info(dataset_id=None)))
    assert not report.dataset_complete
    assert report.error_code == "missing_dataset"
    row = context[2].list_runs()[0]
    assert row["state"] == "PARTIAL"
    assert row["error_code"] == "missing_dataset"
    assert row["api_status"] == "SUCCEEDED"


def test_partial_download_then_resume_uses_get_only_and_clears_error(context):
    first = [raw_job(index) for index in range(1, 101)]
    client = StubClient(
        pages=[DatasetPage(first, 0, 101), ApifyError("transport_error", "Safe fixture error")]
    )
    report = collect(context, client)
    assert report.fetched == 100
    assert not report.dataset_complete
    assert context[2].list_runs()[0]["error_code"] == "transport_error"
    with pytest.raises(JournalError):
        collect(context, StubClient())
    resumed = StubClient(
        reads=[run_info()],
        pages=[DatasetPage(first, 0, 101), DatasetPage([raw_job(101)], 100, 101)],
    )
    report = collect(context, resumed, resume_run_id="RunOne")
    assert resumed.starts == 0
    assert resumed.read_ids == ["RunOne"]
    assert report.fetched == 101
    assert report.dataset_complete
    assert context[2].list_runs()[0]["error_code"] is None


@pytest.mark.parametrize("status", ["FAILED", "ABORTED", "TIMED-OUT"])
def test_remote_failure_is_not_successful_zero(context, status):
    with pytest.raises(CollectionError) as caught:
        collect(context, StubClient(start=run_info(status)))
    assert caught.value.code == "actor_failed"
    assert context[2].list_runs()[0]["state"] == "REMOTE_FAILED"


def test_wait_timeout_keeps_known_run_and_blocks_restarting(context):
    with pytest.raises(CollectionError) as caught:
        collect(context, StubClient(start=run_info("RUNNING")), wait_seconds=0)
    assert caught.value.code == "wait_timeout"
    assert context[2].by_run("RunOne").state == "WAIT_TIMEOUT"
    second = StubClient()
    with pytest.raises(JournalError):
        collect(context, second)
    assert second.starts == 0


def test_poll_failure_can_resume_without_new_post(context):
    with pytest.raises(ApifyError):
        collect(
            context,
            StubClient(
                start=run_info("RUNNING"),
                reads=[ApifyError("transport_error", "Safe fixture error")],
            ),
        )
    assert context[2].by_run("RunOne").state == "READ_FAILED"
    resumed = StubClient(reads=[run_info()], pages=[DatasetPage([], 0, 0)])
    collect(context, resumed, resume_run_id="RunOne")
    assert resumed.starts == 0
    assert context[2].list_runs()[0]["error_code"] is None


def test_start_unknown_blocks_new_start_then_allows_manual_binding(context):
    client = StubClient(start=ApifyError("start_unknown", "Safe fixture error"))
    with pytest.raises(ApifyError):
        collect(context, client)
    attempt_id = context[2].list_runs()[0]["id"]
    assert context[2].get(attempt_id).state == "START_UNKNOWN"
    with pytest.raises(JournalError):
        collect(context, client)
    assert client.starts == 1
    with pytest.raises(JournalError):
        collect(context, StubClient(), resume_run_id="RunOne")
    resumed = StubClient(reads=[run_info()], pages=[DatasetPage([], 0, 0)])
    collect(context, resumed, resume_run_id="RunOne", attempt_id=attempt_id)
    assert resumed.starts == 0
    assert context[2].by_run("RunOne").id == attempt_id


def test_definite_start_rejection_retains_budget(context):
    with pytest.raises(ApifyError):
        collect(context, StubClient(start=ApifyError("access_denied", "Safe fixture error")))
    row = context[2].list_runs()[0]
    assert row["state"] == "START_REJECTED"
    assert row["reserved_usd"] == "0.05"


def test_resume_rejects_changed_profile_and_different_run(context):
    report = collect(context, StubClient(pages=[DatasetPage([], 0, 0)]))
    profile, settings, journal = context
    modified = replace(profile, keywords=("new keyword",))
    with pytest.raises(JournalError, match="Profile"):
        collect((modified, settings, journal), StubClient(), resume_run_id="RunOne")
    with pytest.raises(JournalError, match="run"):
        collect(context, StubClient(), resume_run_id="OtherRun", attempt_id=report.attempt_id)
    assert fingerprint(profile) != fingerprint(modified)


def test_invalid_item_is_visible_and_not_recorded_complete(context):
    report = collect(context, StubClient(pages=[DatasetPage([{}], 0, 1)]))
    assert report.dataset_complete
    assert report.invalid_count == 1
    assert context[2].get(report.attempt_id).state == "PARTIAL"


def test_cost_cap_warning_is_not_claim_of_complete_coverage(context):
    report = collect(
        context, StubClient(start=run_info(usage="0.05"), pages=[DatasetPage([], 0, 0)])
    )
    assert "charge_cap_possible" in report.warnings
    assert report.summary()["search_coverage"] == "bounded_not_verified"


def test_run_identifier_is_reported_before_journal_write(context, monkeypatch):
    progress = []
    profile, settings, journal = context

    def failed_write(*args):
        raise OSError("simulated disk error")

    monkeypatch.setattr(journal, "observe", failed_write)
    with pytest.raises(OSError):
        collect_live(profile, settings, journal, StubClient(), progress=progress.append)
    assert "RunOne" in progress[-1]


@pytest.mark.parametrize("age,stale", [(90, False), (91, True)])
def test_rule_freshness_warning_even_when_no_jobs(context, age, stale):
    profile, _, _ = context
    today = date.fromisoformat(RULES_CHECKED_AT) + timedelta(days=age)
    report = Report(profile.id, "fixture", "local", assessed_at=today.isoformat())
    process_items(report, [], profile)
    assert report.summary()["whv_rules"]["stale"] is stale
    assert ("whv_rules_stale" in report.warnings) is stale
    assert sum(report.summary()["whv_counts"].values()) == 0


def test_stale_rules_keep_report_and_assessment_metadata_consistent(context):
    profile, _, _ = context
    report = Report(profile.id, "fixture", "local", assessed_at="2027-01-01")
    raw = raw_job()
    raw["description"] = (
        "Temporary fixed-term contract for two months. Working holiday visa holders welcome."
    )
    process_items(report, [raw], profile)
    result = report.whv_assessments["1"]
    assert result.label == "needs_confirmation"
    assert result.rules_stale
    assert result.assessed_at == report.summary()["whv_rules"]["assessed_at"]
    assert report.warnings.count("whv_rules_stale") == 1
