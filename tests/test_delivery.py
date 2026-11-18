"""Dispatcher state transitions with no HTTP, wall-clock waits, or credentials."""

import sqlite3
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from test_cli import PROFILES

from nz_job_radar import delivery
from nz_job_radar.pipeline import fingerprint
from nz_job_radar.profiles import load_profiles
from nz_job_radar.telegram import TelegramError


class FakeStore:
    def __init__(self, rows):
        self.rows = {row["id"]: row for row in rows}
        self.finishes = []

    def recover_stale_sending(self):
        return 0

    def list_outbox(self, **kwargs):
        return [deepcopy(row) for row in self.rows.values()]

    def claim(self, identifier, chat_id, *, max_attempts):
        row = self.rows[identifier]
        if row["status"] not in {"pending", "retryable"} or row["attempts"] >= max_attempts:
            return None
        row["attempts"] += 1
        row["status"] = "sending"
        return deepcopy(row)

    def finish(self, identifier, *, status, **kwargs):
        self.rows[identifier]["status"] = status
        self.finishes.append((identifier, status, kwargs))


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []

    def send(self, chat_id, text):
        self.calls.append((chat_id, text))
        outcome = next(self.outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest.fixture
def profiles():
    return load_profiles(PROFILES)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 23, tzinfo=UTC)

    monkeypatch.setattr(delivery, "datetime", Clock)
    monkeypatch.setattr(delivery.time, "sleep", lambda _: None)


def row(profiles, identifier="one"):
    profile = profiles["auckland-cafe-service"]
    return {
        "id": identifier,
        "job_id": "991000001",
        "status": "pending",
        "attempts": 0,
        "text": "Synthetic notification",
        "rules_checked_at": "2026-09-23",
        "eligible_profiles": [{"profile_id": profile.id, "fingerprint": fingerprint(profile)}],
    }


def test_success_is_committed_after_send(profiles):
    store = FakeStore([row(profiles)])
    client = FakeClient([73])
    result = delivery.dispatch(store, client, "123", profiles)
    assert result["sent"] == 1 and result["remaining"] == 0
    assert store.finishes == [("one", "sent", {"message_id": 73})]


def test_pre_send_retries_stop_after_three_attempts(profiles):
    store = FakeStore([row(profiles)])
    client = FakeClient(
        [TelegramError("connection", "synthetic", outcome="retryable") for _ in range(3)]
    )
    sleeps = []
    result = delivery.dispatch(store, client, "123", profiles, sleep=sleeps.append)
    assert sleeps == [1.1, 1, 2]
    assert len(client.calls) == 3
    assert result["failed"] == 1 and result["remaining"] == 1
    assert store.rows["one"]["attempts"] == 3
    delivery.dispatch(store, client, "123", profiles)
    assert len(client.calls) == 3


def test_rate_limit_defers_whole_destination_without_sleep(profiles):
    store = FakeStore([row(profiles), row(profiles, "two")])
    client = FakeClient(
        [TelegramError("rate_limit", "synthetic", outcome="retryable", retry_after=100)]
    )
    sleeps = []
    result = delivery.dispatch(store, client, "123", profiles, sleep=sleeps.append)
    assert sleeps == [1.1]
    assert len(client.calls) == 1
    assert result["retryable"] == 1 and result["remaining"] == 2
    assert store.rows["two"]["status"] == "pending"
    assert store.finishes[0][2]["retry_after"] == 100


def test_unknown_delivery_stops_batch_and_is_not_replayed(profiles):
    store = FakeStore([row(profiles), row(profiles, "two")])
    client = FakeClient([TelegramError("read_timeout", "synthetic", outcome="delivery_unknown")])
    result = delivery.dispatch(store, client, "123", profiles)
    assert len(client.calls) == 1
    assert result["delivery_unknown"] == 1 and result["remaining"] == 2
    assert store.rows["one"]["status"] == "delivery_unknown"


@pytest.mark.parametrize(
    "change", ["changed_profile", "missing_profile", "stale_rules", "future_rules"]
)
def test_unconfirmed_snapshot_is_not_sent(profiles, change):
    queued = row(profiles)
    if change == "changed_profile":
        queued["eligible_profiles"][0]["fingerprint"] = "outdated"
    if change == "missing_profile":
        queued["eligible_profiles"] = []
    if change == "stale_rules":
        queued["rules_checked_at"] = "2026-01-01"
    if change == "future_rules":
        queued["rules_checked_at"] = "2027-01-01"
    client = FakeClient([])
    result = delivery.dispatch(FakeStore([queued]), client, "123", profiles)
    assert client.calls == []
    assert result["skipped"] == 1 and result["remaining"] == 1


def test_interrupt_preserves_unknown_before_exiting(profiles):
    store = FakeStore([row(profiles)])
    client = FakeClient([KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        delivery.dispatch(store, client, "123", profiles)
    assert store.rows["one"]["status"] == "delivery_unknown"


def test_dispatch_respects_explicit_batch_scope(profiles):
    one, two = row(profiles), row(profiles, "two")
    two["job_id"] = "991000002"
    store = FakeStore([one, two])
    result = delivery.dispatch(store, FakeClient([10]), "123", profiles, job_ids={"991000002"})
    assert result["sent"] == 1 and result["remaining"] == 0
    assert store.rows["one"]["status"] == "pending"


def test_failure_to_commit_success_never_replays_http(profiles):
    class FailingCommitStore(FakeStore):
        def finish(self, identifier, *, status, **kwargs):
            if status == "sent":
                raise sqlite3.OperationalError("synthetic commit failure")
            super().finish(identifier, status=status, **kwargs)

    store = FailingCommitStore([row(profiles)])
    client = FakeClient([73])
    with pytest.raises(sqlite3.OperationalError):
        delivery.dispatch(store, client, "123", profiles)
    assert len(client.calls) == 1
    assert store.rows["one"]["status"] == "sending"
    result = delivery.dispatch(store, client, "123", profiles)
    assert len(client.calls) == 1 and result["remaining"] == 1
