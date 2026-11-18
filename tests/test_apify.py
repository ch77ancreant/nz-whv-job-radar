"""Offline HTTP contracts. No token file or external network is used."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import httpx
import pytest

from nz_job_radar.apify import ACTOR_ID, ApifyClient, ApifyError, build_actor_input
from nz_job_radar.profiles import Profile

TOKEN = "synthetic-test-token-not-a-secret"
RUN_ID = "SyntheticRunOkay1"
DATASET_ID = "SyntheticDataset1"


def run_payload(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": RUN_ID,
        "actId": ACTOR_ID,
        "status": "SUCCEEDED",
        "defaultDatasetId": DATASET_ID,
        "usageTotalUsd": 0.012,
        "chargedEventCounts": {"apify-default-dataset-item": 1},
        "startedAt": "2026-09-23T06:19:51.448Z",
        "finishedAt": "2026-09-23T06:20:03.152Z",
    }
    data.update(overrides)
    return {"data": data}


def mock_client(handler, *, sleep=lambda _: None, attempts=3) -> ApifyClient:
    return ApifyClient(
        TOKEN,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        request_interval=0,
        sleep=sleep,
        max_get_attempts=attempts,
    )


@pytest.mark.parametrize("locations", [("Auckland",), ("Queenstown", "Wanaka")])
def test_actor_input_is_explicit_plain_mode(locations):
    profile = cast(
        Profile,
        SimpleNamespace(
            country="NZ",
            locations=locations,
            keywords=("cafe assistant", "front of house"),
            max_results=20,
            max_pages=2,
        ),
    )
    data = build_actor_input(profile)
    assert json.loads(data["query"]) == ["cafe assistant", "front of house"]
    assert data["location"] == (
        locations[0] if len(locations) == 1 else json.dumps(list(locations))
    )
    assert data["country"] == "NZ"
    assert data["maxResults"] == 20
    assert data["maxPages"] == 2
    assert data["includeDetails"] is True
    assert data["includeApplicantInsights"] is False
    assert data["compact"] is False
    assert data["incrementalMode"] is False
    assert data["skipReposts"] is False
    assert data["descriptionFormat"] == "text"
    assert data["sortMode"] == "date"
    assert set(data) == {
        "query",
        "country",
        "location",
        "maxResults",
        "maxPages",
        "sortMode",
        "includeDetails",
        "includeApplicantInsights",
        "descriptionFormat",
        "compact",
        "incrementalMode",
        "skipReposts",
    }


def test_start_pins_build_budget_and_uses_header_auth():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(201, json=run_payload(status="RUNNING", finishedAt=None))

    client = mock_client(handler)
    result = client.start_run({"incrementalMode": False}, max_charge_usd=Decimal("0.05"))
    assert result.id == RUN_ID
    assert result.status == "RUNNING"
    assert result.finished_at is None
    assert result.usage_usd == Decimal("0.012")
    assert result.charged_item_count == 1
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.host == "api.apify.com"
    assert request.url.path == f"/v2/actors/{ACTOR_ID}/runs"
    assert dict(request.url.params) == {
        "build": "0.4.57",
        "timeout": "120",
        "maxTotalChargeUsd": "0.05",
    }
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(request.url)
    assert json.loads(request.content) == {"incrementalMode": False}


def test_injected_client_defaults_cannot_add_query_tokens_or_override_auth():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=run_payload())

    external = httpx.Client(
        transport=httpx.MockTransport(handler),
        params={"token": "must-not-be-sent"},
        headers={"Authorization": "Basic must-not-be-sent"},
        cookies={"session": "must-not-be-sent"},
    )
    with ApifyClient(TOKEN, client=external, request_interval=0) as client:
        client.get_run(RUN_ID)
    assert requests[0].url.query == b""
    assert requests[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert "Cookie" not in requests[0].headers
    assert not external.is_closed
    external.close()


@pytest.mark.parametrize(
    "failure", ["timeout", "connection", 200, 302, 408, 429, 500, 503, "malformed", "nonjson"]
)
def test_paid_start_is_never_retried(failure):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout(f"untrusted {TOKEN}", request=request)
        if failure == "connection":
            raise httpx.ConnectError(f"untrusted {TOKEN}", request=request)
        if failure == "malformed":
            return httpx.Response(201, json={"message": TOKEN})
        if failure == "nonjson":
            return httpx.Response(201, text=TOKEN)
        return httpx.Response(failure, json={"error": {"message": TOKEN}})

    with pytest.raises(ApifyError) as caught:
        mock_client(handler).start_run({}, max_charge_usd=Decimal("0.05"))
    assert len(calls) == 1
    assert caught.value.code == ("rate_limited" if failure == 429 else "start_unknown")
    assert TOKEN not in str(caught.value)


def test_retry_after_is_respected_for_get_and_retry_count_is_bounded():
    calls = []
    sleeps = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "2"}, json={"error": {"message": TOKEN}})

    with pytest.raises(ApifyError) as caught:
        mock_client(handler, sleep=sleeps.append).get_run(RUN_ID)
    assert caught.value.code == "rate_limited"
    assert len(calls) == 3
    assert sleeps == [2.0, 2.0]
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize("retry_after", ["90", "Wed, 01 Jan 2100 00:00:00 GMT", "nonsense", "NaN"])
def test_long_or_invalid_retry_after_is_not_ignored(retry_after):
    calls = []
    sleeps = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": retry_after})

    with pytest.raises(ApifyError) as caught:
        mock_client(handler, sleep=sleeps.append).get_run(RUN_ID)
    assert caught.value.code == "retry_later"
    assert len(calls) == 1
    assert sleeps == []


def test_get_can_recover_transport_then_server_error():
    calls = []
    sleeps = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout(TOKEN, request=request)
        if len(calls) == 2:
            return httpx.Response(503)
        return httpx.Response(200, json=run_payload())

    result = mock_client(handler, sleep=sleeps.append).get_run(RUN_ID)
    assert result.id == RUN_ID
    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 302])
def test_non_retryable_http_errors_are_safe(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, headers={"Location": "https://example.invalid/" + TOKEN}, content=TOKEN
        )

    with pytest.raises(ApifyError) as caught:
        mock_client(handler).get_run(RUN_ID)
    assert len(calls) == 1
    assert TOKEN not in str(caught.value)
    assert "example.invalid" not in str(caught.value)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"data": []},
        {"data": {"id": RUN_ID}},
        run_payload(id="../escape"),
        run_payload(id="different"),
        run_payload(status="not a real status"),
        run_payload(usageTotalUsd="NaN"),
        run_payload(usageTotalUsd=-1),
        run_payload(usageTotalUsd=True),
        run_payload(chargedEventCounts={"apify-default-dataset-item": -1}),
        run_payload(startedAt="not a timestamp"),
        run_payload(startedAt="2026-09-23"),
        run_payload(actId="wrongActor"),
        run_payload(defaultDatasetId="../escape"),
    ],
)
def test_success_http_with_bad_run_data_fails_closed(payload):
    client = mock_client(lambda _: httpx.Response(200, json=payload))
    with pytest.raises(ApifyError, match="unexpected response") as caught:
        client.get_run(RUN_ID)
    assert caught.value.code == "invalid_response"


def test_failed_run_and_unknown_usage_are_not_faked_as_success_or_zero():
    client = mock_client(
        lambda _: httpx.Response(
            200,
            json=run_payload(
                status="FAILED",
                usageTotalUsd=None,
                chargedEventCounts=None,
                statusMessage=f"server can echo {TOKEN}",
            ),
        )
    )
    result = client.get_run(RUN_ID)
    assert result.status == "FAILED"
    assert result.usage_usd is None
    assert result.charged_item_count is None
    assert TOKEN not in repr(result)


def test_observed_phase0_projection_can_be_parsed_without_network():
    path = Path(__file__).parent / "fixtures" / "phase0" / "seek-runs.json"
    evidence = json.loads(path.read_text(encoding="utf-8"))
    for run in evidence["runs"]:
        data = {**run, "id": run["runId"]}
        client = mock_client(lambda _, data=data: httpx.Response(200, json={"data": data}))
        actual = client.get_run(run["runId"])
        assert actual.status == run["status"]
        assert actual.usage_usd == Decimal(str(run["usageTotalUsd"]))


def test_dataset_page_uses_documented_headers_without_filtering_offsets():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json=[{"seekJobId": "12"}, {"seekJobId": "13"}],
            headers={
                "X-Apify-Pagination-Offset": "10",
                "X-Apify-Pagination-Limit": "2",
                "X-Apify-Pagination-Count": "2",
                "X-Apify-Pagination-Total": "13",
            },
        )

    result = mock_client(handler).get_dataset_page(DATASET_ID, offset=10, limit=2)
    assert result.offset == 10
    assert result.total == 13
    assert len(result.items) == 2
    assert requests[0].url.path == f"/v2/datasets/{DATASET_ID}/items"
    assert dict(requests[0].url.params) == {
        "format": "json",
        "offset": "10",
        "limit": "2",
        "desc": "false",
    }


def test_dataset_missing_total_is_unknown_not_zero():
    result = mock_client(lambda _: httpx.Response(200, json=[])).get_dataset_page(
        DATASET_ID, offset=0
    )
    assert result.items == []
    assert result.total is None


@pytest.mark.parametrize(
    ("payload", "headers"),
    [
        ({"error": {}}, {}),
        ([1], {}),
        ([], {"X-Apify-Pagination-Total": "1"}),
        ([{}], {"X-Apify-Pagination-Count": "0"}),
        ([{}], {"X-Apify-Pagination-Offset": "1"}),
        ([{}], {"X-Apify-Pagination-Total": "0"}),
        ([{}], {"X-Apify-Pagination-Limit": "1"}),
        ([], {"X-Apify-Pagination-Total": "unknown"}),
    ],
)
def test_dataset_malformed_data_is_not_silently_empty(payload, headers):
    client = mock_client(lambda _: httpx.Response(200, json=payload, headers=headers))
    with pytest.raises(ApifyError) as caught:
        client.get_dataset_page(DATASET_ID, offset=0)
    assert caught.value.code == "invalid_response"


@pytest.mark.parametrize(
    "identifier", ["../run", "a/b", "a?token=foo", "https://example.com", "", "\n"]
)
def test_invalid_path_ids_never_send_request(identifier):
    def handler(_):
        pytest.fail("No HTTP request should be sent")

    client = mock_client(handler)
    with pytest.raises(ApifyError):
        client.get_run(identifier)
    with pytest.raises(ApifyError):
        client.get_dataset_page(identifier, offset=0)


def test_non_json_success_is_safe():
    client = mock_client(lambda _: httpx.Response(200, text=TOKEN))
    with pytest.raises(ApifyError) as caught:
        client.get_run(RUN_ID)
    assert TOKEN not in str(caught.value)


def test_bad_budget_is_rejected_before_network():
    def handler(_):
        pytest.fail("Invalid budget must not start a run")

    client = mock_client(handler)
    for invalid in (Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(ApifyError):
            client.start_run({}, max_charge_usd=invalid)
