"""Real CLI-to-HTTP-to-SQLite flows; only HTTP transports and clocks are synthetic."""

import json
import logging
import sqlite3
from collections import deque
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from nz_job_radar import cli, delivery, journal, pipeline, settings, store
from nz_job_radar.apify import ACTOR_ID, DEFAULT_BUILD, ApifyClient
from nz_job_radar.profiles import load_profiles
from nz_job_radar.telegram import TelegramClient

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles"
FIXTURE = ROOT / "tests/fixtures/phase2/seek-synthetic.json"
CAFE = "auckland-cafe-service"
SKI = "nz-ski-fields"
APIFY_TOKEN = "synthetic_phase4_apify_token_never_real"
TELEGRAM_TOKEN = "123456789:" + "SyntheticPhaseFourTokenOnly_" * 2
CHAT_ID = "-1001234567890"


class Clock:
    def __init__(self):
        self.moment = datetime(2026, 9, 23, 12, tzinfo=UTC)
        self.elapsed = 0.0
        self.sleeps = []

    def advance(self, seconds):
        self.elapsed += seconds
        self.moment += timedelta(seconds=seconds)

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.advance(seconds)


class OfflineWorld:
    def __init__(self, tmp_path, capsys, caplog):
        self.root = tmp_path
        self.state = tmp_path / "state"
        self.env_file = tmp_path / "synthetic-settings.env"
        self.env_file.write_text(
            "SOURCE_ACCESS_CONFIRMED=true\n"
            f"APIFY_API_TOKEN={APIFY_TOKEN}\n"
            "APIFY_MAX_CHARGE_USD=0.05\n"
            "APIFY_DAILY_BUDGET_USD=1.00\n"
            "APIFY_TIMEOUT_SECONDS=120\n"
            f"TELEGRAM_BOT_TOKEN={TELEGRAM_TOKEN}\n"
            f"TELEGRAM_CHAT_ID={CHAT_ID}\n",
            encoding="utf-8",
        )
        self.capsys = capsys
        self.caplog = caplog
        self.clock = Clock()
        self.items = json.loads(FIXTURE.read_text(encoding="utf-8"))["items"]
        self.page_size = 6
        self.start_failure = None
        self.poll_status = "SUCCEEDED"
        self.failed_offset = None
        self.telegram_outcomes = deque()
        self.apify_requests = []
        self.telegram_requests = []
        self.actor_inputs = []
        self.runs = {}
        self.outputs = []
        self.http_clients = []

    @property
    def starts(self):
        return sum(request.method == "POST" for request in self.apify_requests)

    @property
    def run_id(self):
        return f"OfflineRun{len(self.runs)}"

    def args(self, profile=CAFE, *, command="run", notify=True):
        args = [
            command,
            "--profiles-dir",
            str(PROFILES),
            "--profile",
            profile,
            "--live",
            "--state-dir",
            str(self.state),
            "--env-file",
            str(self.env_file),
            "--format",
            "json",
        ]
        if command == "resume":
            args += ["--run-id", self.run_id]
        if notify:
            args += ["--notify"]
        return args

    def deliver_args(self):
        return [
            "deliver",
            "--send",
            "--profiles-dir",
            str(PROFILES),
            "--state-dir",
            str(self.state),
            "--env-file",
            str(self.env_file),
            "--format",
            "json",
        ]

    def invoke(self, args, *, expected=0):
        result = cli.main(args)
        captured = self.capsys.readouterr()
        self.outputs.append(captured.out + captured.err)
        assert result == expected, captured.out + captured.err
        return json.loads(captured.out) if captured.out else None

    def rows(self, table):
        assert table in {"runs", "jobs", "job_versions", "outbox", "outbox_attempts"}
        with sqlite3.connect(self.state / "runs.sqlite3") as connection:
            connection.row_factory = sqlite3.Row
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not exists:
                return []
            return [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]

    def _run_payload(self, run_id, status):
        number = run_id.removeprefix("OfflineRun")
        return {
            "data": {
                "id": run_id,
                "actId": ACTOR_ID,
                "status": status,
                "defaultDatasetId": f"OfflineData{number}",
                "usageTotalUsd": "0.012",
                "chargedEventCounts": {"apify-default-dataset-item": len(self.runs[run_id])},
            }
        }

    def apify_transport(self, request):
        self.apify_requests.append(request)
        assert request.url.host == "api.apify.com"
        assert request.headers["Authorization"] == "Bearer " + APIFY_TOKEN
        assert APIFY_TOKEN not in str(request.url)
        if request.method == "POST":
            assert request.url.path == f"/v2/actors/{ACTOR_ID}/runs"
            assert request.url.params["build"] == DEFAULT_BUILD
            assert request.url.params["timeout"] == "120"
            assert request.url.params["maxTotalChargeUsd"] == "0.05"
            self.actor_inputs.append(json.loads(request.content))
            if self.start_failure == "timeout":
                raise httpx.ReadTimeout(APIFY_TOKEN + " " + TELEGRAM_TOKEN, request=request)
            if self.start_failure is not None:
                return httpx.Response(
                    self.start_failure,
                    json={"error": {"message": APIFY_TOKEN + " " + TELEGRAM_TOKEN}},
                )
            run_id = f"OfflineRun{len(self.runs) + 1}"
            self.runs[run_id] = json.loads(json.dumps(self.items))
            return httpx.Response(201, json=self._run_payload(run_id, "RUNNING"))
        if request.url.path.startswith("/v2/actor-runs/"):
            run_id = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json=self._run_payload(run_id, self.poll_status))
        assert request.url.path.startswith("/v2/datasets/OfflineData")
        number = request.url.path.split("/")[-2].removeprefix("OfflineData")
        items = self.runs[f"OfflineRun{number}"]
        offset = int(request.url.params["offset"])
        assert request.url.params["limit"] == "100"
        assert request.url.params["desc"] == "false"
        if offset == self.failed_offset:
            return httpx.Response(
                403, json={"error": {"message": APIFY_TOKEN + " " + TELEGRAM_TOKEN}}
            )
        page = items[offset : offset + self.page_size]
        return httpx.Response(
            200,
            json=page,
            headers={
                "X-Apify-Pagination-Offset": str(offset),
                "X-Apify-Pagination-Count": str(len(page)),
                "X-Apify-Pagination-Limit": "100",
                "X-Apify-Pagination-Total": str(len(items)),
            },
        )

    def telegram_transport(self, request):
        self.telegram_requests.append(request)
        assert request.method == "POST"
        assert request.url.host == "api.telegram.org"
        assert request.url.path == "/bot" + TELEGRAM_TOKEN + "/sendMessage"
        payload = json.loads(request.content)
        assert payload["chat_id"] == int(CHAT_ID)
        assert payload["link_preview_options"] == {"is_disabled": True}
        assert "parse_mode" not in payload
        assert "僅供初步篩選" in payload["text"]
        # A separate connection must see the committed claim before HTTP can begin.
        assert self.rows("jobs")
        assert any(
            row["status"] == "sending" and row["text"] == payload["text"]
            for row in self.rows("outbox")
        )
        outcome = self.telegram_outcomes.popleft() if self.telegram_outcomes else "success"
        if outcome == "read_timeout":
            raise httpx.ReadTimeout(TELEGRAM_TOKEN + " " + APIFY_TOKEN, request=request)
        if outcome == "connect_error":
            raise httpx.ConnectError(TELEGRAM_TOKEN + " " + APIFY_TOKEN, request=request)
        if outcome == "invalid_json":
            return httpx.Response(200, content=(TELEGRAM_TOKEN + " " + APIFY_TOKEN).encode())
        if outcome in {"429", "403", "500"}:
            status = int(outcome)
            body = {
                "ok": False,
                "error_code": status,
                "description": TELEGRAM_TOKEN + " " + APIFY_TOKEN,
            }
            if status == 429:
                body["parameters"] = {"retry_after": 60}
            return httpx.Response(status, json=body)
        assert outcome == "success"
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": 5000 + len(self.telegram_requests),
                    "chat": {"id": int(CHAT_ID)},
                },
            },
        )

    def assert_no_secret_leak(self):
        text = "\n".join(self.outputs) + self.caplog.text
        database = self.state / "runs.sqlite3"
        if database.exists():
            with sqlite3.connect(database) as connection:
                text += "\n".join(connection.iterdump())
        for secret in (APIFY_TOKEN, TELEGRAM_TOKEN, CHAT_ID):
            assert secret not in text


@pytest.fixture
def world(tmp_path, monkeypatch, capsys, caplog):
    instance = OfflineWorld(tmp_path, capsys, caplog)
    clock = instance.clock

    class FrozenDate(date):
        @classmethod
        def today(cls):
            return clock.moment.date()

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.moment.astimezone(tz) if tz else clock.moment.replace(tzinfo=None)

    def apify_client(token):
        client = httpx.Client(
            transport=httpx.MockTransport(instance.apify_transport), trust_env=False
        )
        instance.http_clients.append(client)
        return ApifyClient(token, client=client, sleep=clock.sleep, request_interval=0)

    def telegram_client(token):
        return TelegramClient(token, transport=httpx.MockTransport(instance.telegram_transport))

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "ApifyClient", apify_client)
    monkeypatch.setattr(cli, "TelegramClient", telegram_client)
    # Real parsers read only this test's file, never workstation environment variables.
    monkeypatch.setattr(
        cli, "load_live_settings", lambda path: settings.load_live_settings(path, environ={})
    )
    monkeypatch.setattr(
        cli,
        "load_telegram_settings",
        lambda path: settings.load_telegram_settings(path, environ={}),
    )
    monkeypatch.setattr(pipeline, "date", FrozenDate)
    monkeypatch.setattr(pipeline, "time", SimpleNamespace(monotonic=lambda: clock.elapsed))
    monkeypatch.setitem(pipeline.collect_live.__kwdefaults__, "sleep", clock.sleep)
    monkeypatch.setattr(delivery, "time", SimpleNamespace(sleep=clock.sleep))
    for module in (delivery, journal, store):
        monkeypatch.setattr(module, "datetime", FrozenDateTime)
    caplog.set_level(logging.DEBUG)
    assert cli.collect_live is pipeline.collect_live
    try:
        yield instance
    finally:
        for client in instance.http_clients:
            client.close()
        instance.assert_no_secret_leak()


@pytest.mark.parametrize("profile_id,matched,sends", [(CAFE, 10, 7), (SKI, 2, 2)])
def test_actual_yaml_profile_through_both_http_clients_resume_and_rerun(
    world, profile_id, matched, sends
):
    profile = load_profiles(PROFILES)[profile_id]
    first = world.invoke(world.args(profile_id))
    assert first["summary"]["matched"] == matched
    assert first["summary"]["fetched"] == 12
    assert first["summary"]["dataset_complete"] is True
    assert first["notifications"]["delivery"]["sent"] == sends
    assert world.starts == 1
    actor = world.actor_inputs[0]
    assert json.loads(actor["query"]) == list(profile.keywords)
    assert actor["country"] == "NZ"
    locations = (
        [actor["location"]] if len(profile.locations) == 1 else json.loads(actor["location"])
    )
    assert locations == list(profile.locations)
    assert actor["maxResults"] == profile.max_results
    assert actor["maxPages"] == profile.max_pages
    assert actor["includeDetails"] is True
    assert actor["incrementalMode"] is False
    assert actor["includeApplicantInsights"] is False
    assert len(world.rows("jobs")) == len(world.rows("job_versions")) == 12
    resumed = world.invoke(world.args(profile_id, command="resume"))
    assert world.starts == 1
    assert resumed["notifications"]["queued"] == 0
    assert resumed["notifications"]["delivery"]["sent"] == 0
    rerun = world.invoke(world.args(profile_id))
    assert world.starts == 2
    assert rerun["notifications"]["new_jobs"] == 0
    assert rerun["notifications"]["changed_jobs"] == 0
    assert rerun["notifications"]["deduplicated"] == sends
    assert len(world.telegram_requests) == sends
    assert all(row["status"] == "sent" for row in world.rows("outbox"))


@pytest.mark.parametrize(
    "failure,state,code",
    [
        (401, "START_REJECTED", "access_denied"),
        (403, "START_REJECTED", "access_denied"),
        (400, "START_REJECTED", "http_error"),
        (429, "START_REJECTED", "rate_limited"),
        (408, "START_UNKNOWN", "start_unknown"),
        ("timeout", "START_UNKNOWN", "start_unknown"),
    ],
)
def test_source_start_failures_never_retry_paid_post_or_send_telegram(world, failure, state, code):
    world.start_failure = failure
    assert world.invoke(world.args(), expected=2) is None
    assert world.starts == 1
    assert world.telegram_requests == []
    row = world.rows("runs")[0]
    assert row["state"] == state
    assert row["error_code"] == code
    assert world.rows("jobs") == []
    assert world.rows("outbox") == []
    if state == "START_UNKNOWN":
        assert world.invoke(world.args(), expected=2) is None
        assert world.starts == 1


@pytest.mark.parametrize("remote_status", ["FAILED", "ABORTED", "TIMED-OUT"])
def test_terminal_actor_failure_is_not_an_empty_success_or_notification(world, remote_status):
    world.poll_status = remote_status
    assert world.invoke(world.args(), expected=2) is None
    assert world.starts == 1
    assert world.rows("runs")[0]["state"] == "REMOTE_FAILED"
    assert world.rows("jobs") == []
    assert world.telegram_requests == []
    assert not any("/datasets/" in request.url.path for request in world.apify_requests)


def test_local_poll_timeout_resumes_existing_remote_run_without_new_post(world):
    world.items = world.items[:1]
    world.poll_status = "RUNNING"
    assert world.invoke(world.args() + ["--wait-seconds", "1"], expected=2) is None
    assert world.rows("runs")[0]["state"] == "WAIT_TIMEOUT"
    assert world.telegram_requests == []
    world.poll_status = "SUCCEEDED"
    resumed = world.invoke(world.args(command="resume"))
    assert world.starts == 1
    assert resumed["notifications"]["delivery"]["sent"] == 1
    assert world.rows("runs")[0]["state"] == "COMPLETE"


def test_legitimate_empty_dataset_completes_without_notifications(world):
    world.items = []
    payload = world.invoke(world.args())
    assert payload["summary"]["fetched"] == 0
    assert payload["summary"]["dataset_complete"] is True
    assert payload["summary"]["error_code"] is None
    assert world.rows("runs")[0]["state"] == "COMPLETE"
    assert world.telegram_requests == []


def test_dataset_access_failure_is_partial_even_with_zero_downloaded_rows(world):
    world.failed_offset = 0
    payload = world.invoke(world.args(), expected=2)
    assert payload["summary"]["fetched"] == 0
    assert payload["summary"]["dataset_complete"] is False
    assert payload["summary"]["error_code"] == "access_denied"
    assert world.rows("runs")[0]["state"] == "PARTIAL"
    assert world.telegram_requests == []


def test_partial_page_is_retained_and_resume_sends_only_previously_missing_jobs(world):
    world.failed_offset = 6
    partial = world.invoke(world.args(), expected=2)
    assert partial["summary"]["fetched"] == 6
    assert partial["summary"]["dataset_complete"] is False
    assert partial["notifications"]["delivery"]["sent"] == 3
    assert len(world.rows("jobs")) == 6
    first_texts = {json.loads(request.content)["text"] for request in world.telegram_requests}
    world.failed_offset = None
    resumed = world.invoke(world.args(command="resume"))
    assert world.starts == 1
    assert resumed["summary"]["fetched"] == 12
    assert resumed["summary"]["dataset_complete"] is True
    assert resumed["notifications"]["new_jobs"] == 6
    assert resumed["notifications"]["deduplicated"] == 3
    assert resumed["notifications"]["delivery"]["sent"] == 4
    assert len(world.rows("jobs")) == 12
    assert len(world.telegram_requests) == 7
    remaining_texts = {
        json.loads(request.content)["text"] for request in world.telegram_requests[3:]
    }
    assert not first_texts & remaining_texts
    offsets = [
        int(request.url.params["offset"])
        for request in world.apify_requests
        if "/datasets/" in request.url.path
    ]
    assert offsets == [0, 6, 0, 6]


def test_real_telegram_429_honors_cooldown_across_resume_and_deliver(world):
    world.items = [world.items[0], world.items[9]]
    world.telegram_outcomes.append("429")
    first = world.invoke(world.args(), expected=2)
    assert first["notifications"]["delivery"]["retryable"] == 1
    assert len(world.telegram_requests) == 1
    world.invoke(world.args(command="resume"), expected=2)
    blocked = world.invoke(world.deliver_args(), expected=2)
    assert blocked["sent"] == 0
    assert len(world.telegram_requests) == 1
    assert world.starts == 1
    world.clock.advance(61)
    delivered = world.invoke(world.deliver_args())
    assert delivered["sent"] == 2
    assert delivered["remaining"] == 0
    assert len(world.telegram_requests) == 3
    assert world.starts == 1
    assert all(row["status"] == "sent" for row in world.rows("outbox"))


@pytest.mark.parametrize("outcome", ["read_timeout", "500", "invalid_json"])
def test_ambiguous_telegram_http_outcomes_survive_resume_without_blind_replay(world, outcome):
    world.items = world.items[:1]
    world.telegram_outcomes.append(outcome)
    first = world.invoke(world.args(), expected=2)
    assert first["notifications"]["delivery"]["delivery_unknown"] == 1
    assert world.rows("outbox")[0]["status"] == "delivery_unknown"
    assert len(world.rows("jobs")) == 1
    world.invoke(world.args(command="resume"), expected=2)
    result = world.invoke(world.deliver_args(), expected=2)
    assert result["sent"] == 0
    assert len(world.telegram_requests) == 1
    assert world.starts == 1


def test_important_content_change_sends_one_update_then_deduplicates_resume(world):
    world.items = world.items[:1]
    first = world.invoke(world.args())
    assert first["notifications"]["messages"][0]["kind"] == "new"
    world.items[0]["salaryText"] = "$30 per hour"
    changed = world.invoke(world.args())
    assert changed["notifications"]["changed_jobs"] == 1
    assert changed["notifications"]["messages"][0]["kind"] == "update"
    assert changed["notifications"]["delivery"]["sent"] == 1
    assert len(world.rows("jobs")) == 1
    assert len(world.rows("job_versions")) == 2
    assert {row["kind"] for row in world.rows("outbox")} == {"new", "update"}
    resumed = world.invoke(world.args(command="resume"))
    assert resumed["notifications"]["queued"] == 0
    assert world.starts == 2
    assert len(world.telegram_requests) == 2


def test_explicit_telegram_access_rejection_keeps_jobs_and_failed_outbox(world):
    world.items = world.items[:1]
    world.telegram_outcomes.append("403")
    payload = world.invoke(world.args(), expected=2)
    assert payload["notifications"]["delivery"]["failed"] == 1
    assert world.rows("outbox")[0]["status"] == "failed"
    assert world.rows("outbox")[0]["error_code"] == "access_denied"
    assert len(world.rows("jobs")) == len(world.rows("job_versions")) == 1
    world.invoke(world.deliver_args(), expected=2)
    assert len(world.telegram_requests) == 1


def test_definite_connect_failures_use_bounded_retry_and_actual_http_success(world):
    world.items = world.items[:1]
    world.telegram_outcomes.extend(["connect_error", "connect_error", "success"])
    payload = world.invoke(world.args())
    assert payload["notifications"]["delivery"]["sent"] == 1
    assert len(world.telegram_requests) == 3
    assert world.rows("outbox")[0]["attempts"] == 3
    assert len(world.rows("outbox_attempts")) == 3
    assert 1 in world.clock.sleeps and 2 in world.clock.sleeps


def test_source_permission_gate_prevents_all_http_and_database_creation(world):
    text = world.env_file.read_text(encoding="utf-8")
    world.env_file.write_text(
        text.replace("SOURCE_ACCESS_CONFIRMED=true", "SOURCE_ACCESS_CONFIRMED=false"),
        encoding="utf-8",
    )
    assert world.invoke(world.args(), expected=2) is None
    assert world.apify_requests == []
    assert world.telegram_requests == []
    assert not world.state.exists()


def test_explicit_notify_limit_caps_actual_http_posts_and_keeps_remainder_pending(world):
    payload = world.invoke(world.args() + ["--notify-limit", "3"], expected=2)
    assert payload["summary"]["dataset_complete"] is True
    assert payload["notifications"]["queued"] == 7
    assert payload["notifications"]["delivery"]["sent"] == 3
    assert payload["notifications"]["delivery"]["remaining"] == 4
    assert len(world.telegram_requests) == 3
    assert len(world.rows("jobs")) == 12
    statuses = [row["status"] for row in world.rows("outbox")]
    assert statuses.count("sent") == 3
    assert statuses.count("pending") == 4
    assert world.starts == 1
