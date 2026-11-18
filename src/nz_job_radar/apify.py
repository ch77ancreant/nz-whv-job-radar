"""Small, bounded Apify client. Starting a paid run is never retried.

This module does not read credentials, decide source permission, poll runs, or
send notifications. Its caller must enforce those policies before starting.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from .profiles import Profile


ACTOR_ID = "5BAoYcBhwvPuMtd0K"
DEFAULT_BUILD = "0.4.57"
API_ORIGIN = "https://api.apify.com"
_ID = re.compile(r"[A-Za-z0-9]{1,64}\Z")
_BUILD = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
_RUN_STATUSES = frozenset(
    {"READY", "RUNNING", "SUCCEEDED", "FAILED", "TIMING-OUT", "TIMED-OUT", "ABORTING", "ABORTED"}
)
_MAX_RETRY_DELAY_SECONDS = 30.0


class ApifyError(Exception):
    """An error with a stable code and a safe, locally authored message."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class RunInfo:
    id: str
    status: str
    dataset_id: str | None
    usage_usd: Decimal | None
    started_at: str | None
    finished_at: str | None
    charged_item_count: int | None


@dataclass(frozen=True)
class DatasetPage:
    items: list[dict[str, object]]
    offset: int
    total: int | None


def build_actor_input(profile: Profile) -> dict[str, object]:
    """Encode multiple searches as strings, as required by the pinned Actor."""
    if profile.country != "NZ":
        raise ApifyError("invalid_input", "Only New Zealand profiles are supported.")
    locations = profile.locations
    return {
        "query": json.dumps(list(profile.keywords), ensure_ascii=False),
        "country": "NZ",
        "location": locations[0] if len(locations) == 1 else json.dumps(list(locations)),
        "maxResults": profile.max_results,
        "maxPages": profile.max_pages,
        "sortMode": "date",
        "includeDetails": True,
        "includeApplicantInsights": False,
        "descriptionFormat": "text",
        "compact": False,
        "incrementalMode": False,
        "skipReposts": False,
    }


def _valid_id(value: object) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ApifyError("invalid_id", "The run or dataset ID is invalid.")
    return value


def _schema_error() -> ApifyError:
    return ApifyError(
        "invalid_response", "Apify returned an unexpected response; no empty result was assumed."
    )


def _optional_timestamp(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _schema_error()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise _schema_error() from None
    if parsed.tzinfo is None:
        raise _schema_error()
    return value


def _parse_run(payload: object) -> RunInfo:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise _schema_error()
    data = payload["data"]
    try:
        run_id = _valid_id(data.get("id"))
        dataset_id = data.get("defaultDatasetId")
        if dataset_id is not None:
            dataset_id = _valid_id(dataset_id)
    except ApifyError:
        raise _schema_error() from None
    status = data.get("status")
    if not isinstance(status, str) or status not in _RUN_STATUSES:
        raise _schema_error()
    if "actId" in data and data["actId"] != ACTOR_ID:
        raise _schema_error()

    raw_usage = data.get("usageTotalUsd")
    usage = None
    if raw_usage is not None:
        if isinstance(raw_usage, bool) or not isinstance(raw_usage, (int, float, str)):
            raise _schema_error()
        try:
            usage = Decimal(str(raw_usage))
        except InvalidOperation:
            raise _schema_error() from None
        if not usage.is_finite() or usage < 0:
            raise _schema_error()

    item_count = None
    charges = data.get("chargedEventCounts")
    if charges is not None:
        if not isinstance(charges, dict):
            raise _schema_error()
        item_count = charges.get("apify-default-dataset-item")
        if item_count is not None and (type(item_count) is not int or item_count < 0):
            raise _schema_error()
    return RunInfo(
        id=run_id,
        status=status,
        dataset_id=dataset_id,
        usage_usd=usage,
        started_at=_optional_timestamp(data.get("startedAt")),
        finished_at=_optional_timestamp(data.get("finishedAt")),
        charged_item_count=item_count,
    )


def _json_response(response: httpx.Response) -> Any:
    try:
        return response.json()
    except (ValueError, UnicodeError):
        raise _schema_error() from None


def _pagination_integer(response: httpx.Response, name: str) -> int | None:
    raw = response.headers.get(f"X-Apify-Pagination-{name}")
    if raw is None:
        return None
    if not raw.isascii() or not raw.isdigit() or len(raw) > 18:
        raise _schema_error()
    return int(raw)


class ApifyClient:
    """Fixed-origin client with bounded GET retries and secret-safe failures.

    A supplied httpx client is caller-owned. The default transport has no
    automatic connection retries and does not inherit proxy environment values.
    """

    def __init__(
        self,
        token: str,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        request_timeout: float = 30.0,
        request_interval: float = 1.0,
        max_get_attempts: int = 3,
    ) -> None:
        if (
            not isinstance(token, str)
            or not token
            or not token.isascii()
            or any(not 33 <= ord(c) <= 126 for c in token)
        ):
            raise ApifyError("invalid_config", "A valid Apify token is required.")
        if (
            not math.isfinite(request_timeout)
            or not 0 < request_timeout <= 60
            or not math.isfinite(request_interval)
            or not 0 <= request_interval <= 60
            or type(max_get_attempts) is not int
            or not 1 <= max_get_attempts <= 10
        ):
            raise ApifyError("invalid_config", "Invalid HTTP timeout, interval, or retry limit.")
        self._headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        self._owns_client = client is None
        self._client = client if client is not None else httpx.Client(trust_env=False)
        self._sleep = sleep
        self._request_timeout = request_timeout
        self._request_interval = request_interval
        self._max_get_attempts = max_get_attempts
        self._last_request_at: float | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> ApifyClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            remaining = self._request_interval - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at = time.monotonic()

    def _retry_delay(self, response: httpx.Response | None, attempt: int) -> float:
        delay = min(float(2 ** (attempt - 1)), _MAX_RETRY_DELAY_SECONDS)
        raw = None if response is None else response.headers.get("Retry-After")
        if raw is not None:
            try:
                seconds = float(raw)
                if not math.isfinite(seconds) or seconds < 0:
                    raise ValueError
                delay = seconds
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(raw)
                    if retry_at.tzinfo is None:
                        raise ValueError
                    delay = max(0.0, (retry_at - datetime.now(UTC)).total_seconds())
                except (TypeError, ValueError, OverflowError):
                    raise ApifyError(
                        "retry_later", "Invalid retry timing; resume the known run later."
                    ) from None
        if delay > _MAX_RETRY_DELAY_SECONDS:
            raise ApifyError(
                "retry_later", "Apify requested a longer wait; resume the known run later."
            )
        return delay

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str],
        body: dict[str, object] | None = None,
    ) -> httpx.Response:
        is_start = method == "POST"
        attempts = 1 if is_start else self._max_get_attempts
        for attempt in range(1, attempts + 1):
            self._throttle()
            try:
                request = httpx.Request(
                    method,
                    API_ORIGIN + path,
                    headers=self._headers,
                    params=params,
                    json=body,
                    extensions={"timeout": httpx.Timeout(self._request_timeout).as_dict()},
                )
                # Build the request ourselves so a caller-owned client's default
                # params, cookies, and credentials cannot leak into this URL.
                response = self._client.send(
                    request,
                    follow_redirects=False,
                    auth=None,
                )
            except httpx.TransportError:
                if is_start:
                    raise ApifyError(
                        "start_unknown",
                        "Start outcome unknown. Check Apify for the run ID before starting again.",
                    ) from None
                if attempt == attempts:
                    raise ApifyError(
                        "transport_error", "Apify could not be reached; resume the known run later."
                    ) from None
                self._sleep(self._retry_delay(None, attempt))
                continue

            status = response.status_code
            if status == (201 if is_start else 200):
                return response
            if status in (401, 403):
                raise ApifyError(
                    "access_denied",
                    "Apify rejected access. Check the token's required permissions.",
                )
            if is_start and status == 408:
                raise ApifyError(
                    "start_unknown",
                    "The start timed out remotely. Check Apify before starting again.",
                )
            if 300 <= status < 400:
                if is_start:
                    raise ApifyError(
                        "start_unknown",
                        "The start returned a redirect. Check Apify before starting again.",
                    )
                raise ApifyError(
                    "redirect_rejected",
                    "Apify returned an unexpected redirect; it was not followed.",
                )
            if status == 429 or 500 <= status < 600:
                if is_start:
                    code = "rate_limited" if status == 429 else "start_unknown"
                    raise ApifyError(
                        code,
                        "The start was not retried. Check Apify before starting another paid run.",
                    )
                if attempt == attempts:
                    code = "rate_limited" if status == 429 else "server_error"
                    raise ApifyError(
                        code, "Apify is temporarily unavailable; resume the known run later."
                    )
                self._sleep(self._retry_delay(response, attempt))
                continue
            if is_start and not 400 <= status < 500:
                raise ApifyError(
                    "start_unknown",
                    "The start response was unexpected. Check Apify before starting again.",
                )
            raise ApifyError(
                "http_error", "Apify rejected the request; no empty result was assumed."
            )
        raise AssertionError("Unreachable retry state")

    def start_run(
        self,
        actor_input: dict[str, object],
        *,
        max_charge_usd: Decimal,
        timeout_seconds: int = 120,
        build: str = DEFAULT_BUILD,
    ) -> RunInfo:
        if (
            not isinstance(max_charge_usd, Decimal)
            or not max_charge_usd.is_finite()
            or max_charge_usd <= 0
            or type(timeout_seconds) is not int
            or not 1 <= timeout_seconds <= 3600
            or not isinstance(build, str)
            or _BUILD.fullmatch(build) is None
        ):
            raise ApifyError(
                "invalid_input",
                "A finite positive charge cap, bounded timeout, and numbered build are required.",
            )
        response = self._request(
            "POST",
            f"/v2/actors/{ACTOR_ID}/runs",
            params={
                "build": build,
                "timeout": str(timeout_seconds),
                "maxTotalChargeUsd": str(max_charge_usd),
            },
            body=actor_input,
        )
        try:
            return _parse_run(_json_response(response))
        except ApifyError:
            raise ApifyError(
                "start_unknown",
                "The start response was invalid. Check Apify for a run ID; do not start again.",
            ) from None

    def get_run(self, run_id: str) -> RunInfo:
        run_id = _valid_id(run_id)
        response = self._request("GET", f"/v2/actor-runs/{run_id}", params={})
        result = _parse_run(_json_response(response))
        if result.id != run_id:
            raise _schema_error()
        return result

    def get_dataset_page(self, dataset_id: str, *, offset: int, limit: int = 100) -> DatasetPage:
        dataset_id = _valid_id(dataset_id)
        if (
            type(offset) is not int
            or offset < 0
            or type(limit) is not int
            or not 1 <= limit <= 1000
        ):
            raise ApifyError("invalid_input", "Dataset offset or page size is invalid.")
        response = self._request(
            "GET",
            f"/v2/datasets/{dataset_id}/items",
            # Do not use clean/skipEmpty: skipped items would invalidate offsets.
            params={"format": "json", "offset": str(offset), "limit": str(limit), "desc": "false"},
        )
        payload = _json_response(response)
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise _schema_error()
        reported_offset = _pagination_integer(response, "Offset")
        total = _pagination_integer(response, "Total")
        count = _pagination_integer(response, "Count")
        reported_limit = _pagination_integer(response, "Limit")
        if (
            len(payload) > limit
            or (reported_offset is not None and reported_offset != offset)
            or (count is not None and count != len(payload))
            or (reported_limit is not None and reported_limit != limit)
            or (total is not None and payload and offset + len(payload) > total)
            or (total is not None and not payload and offset < total)
        ):
            raise _schema_error()
        return DatasetPage(items=payload, offset=offset, total=total)
