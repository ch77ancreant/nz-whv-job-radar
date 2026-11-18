"""Deliver only committed outbox rows, with finite retries and no ambiguous replay."""

import time
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any

from nz_job_radar.pipeline import fingerprint
from nz_job_radar.profiles import Profile
from nz_job_radar.store import JobStore
from nz_job_radar.telegram import TelegramClient, TelegramError

MAX_ATTEMPTS = 3


def _current_profile(row: dict[str, Any], profiles: Mapping[str, Profile]) -> bool:
    for match in row["eligible_profiles"]:
        profile = profiles.get(match["profile_id"])
        if profile and profile.enabled and fingerprint(profile) == match["fingerprint"]:
            return True
    return False


def _rules_current(row: dict[str, Any]) -> bool:
    try:
        checked_at = date.fromisoformat(row["rules_checked_at"])
    except (ValueError, TypeError, KeyError):
        return False
    return 0 <= (datetime.now(UTC).date() - checked_at).days <= 90


def dispatch(
    store: JobStore,
    client: TelegramClient,
    chat_id: str,
    profiles: Mapping[str, Profile],
    *,
    limit: int = 20,
    outbox_ids: list[str] | None = None,
    job_ids: set[str] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, int]:
    """Bound one manual dispatch; 429 defers the chat, unknown outcomes stop the batch."""
    if not 1 <= limit <= 100:
        raise ValueError("Delivery limit must be 1..100")
    sleep = sleep or time.sleep
    store.recover_stale_sending()
    counters = dict.fromkeys(
        ("sent", "retryable", "failed", "delivery_unknown", "skipped", "remaining"), 0
    )
    rows = store.list_outbox(mode="live", chat_id=chat_id, limit=10000)
    if outbox_ids is not None:
        rows = [row for row in rows if row["id"] in outbox_ids]
    if job_ids is not None:
        rows = [row for row in rows if row["job_id"] in job_ids]
    stop_batch = False
    considered = 0
    for row in rows:
        if row["status"] not in {"pending", "retryable"}:
            continue
        if considered >= limit or stop_batch:
            break
        considered += 1
        if not _current_profile(row, profiles) or not _rules_current(row):
            counters["skipped"] += 1
            continue
        for _ in range(MAX_ATTEMPTS):
            # Re-check persisted eligibility/version within claim's transaction as well.
            claimed = store.claim(row["id"], chat_id, max_attempts=MAX_ATTEMPTS)
            if claimed is None:
                break
            try:
                if _ == 0:
                    # Pace even the first message so adjacent CLI invocations under
                    # the destination lock cannot burst past the same-chat limit.
                    sleep(3.1 if chat_id.startswith("-") else 1.1)
                message_id = client.send(chat_id, claimed["text"])
            except TelegramError as error:
                status = error.outcome
                attempts = claimed["attempts"]
                if status == "retryable" and attempts >= MAX_ATTEMPTS:
                    status = "failed"
                delay = error.retry_after if error.retry_after is not None else 2 ** (attempts - 1)
                store.finish(row["id"], status=status, error_code=error.code, retry_after=delay)
                if status == "retryable" and error.retry_after is None:
                    sleep(min(delay, 2))
                    continue
                counters[status] += 1
                # Do not flood the destination or compound uncertain delivery after an outage.
                stop_batch = status == "delivery_unknown" or error.retry_after is not None
                break
            except BaseException:
                # Includes user interruption between request start and response processing.
                # If even this write fails, stale sending is recovered as unknown next time.
                store.finish(row["id"], status="delivery_unknown", error_code="interrupted_send")
                raise
            else:
                # If commit fails, the row remains sending; NEVER retry the HTTP request.
                store.finish(row["id"], status="sent", message_id=message_id)
                counters["sent"] += 1
                break
    outstanding = store.list_outbox(mode="live", chat_id=chat_id, limit=10000)
    if outbox_ids is not None:
        outstanding = [row for row in outstanding if row["id"] in outbox_ids]
    if job_ids is not None:
        outstanding = [row for row in outstanding if row["job_id"] in job_ids]
    counters["remaining"] = sum(
        row["status"] in {"pending", "retryable", "sending", "failed", "delivery_unknown"}
        for row in outstanding
    )
    return counters
