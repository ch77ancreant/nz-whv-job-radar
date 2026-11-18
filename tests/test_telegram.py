import json
import logging

import httpx
import pytest

from nz_job_radar.telegram import (
    TelegramClient,
    TelegramError,
    normalize_chat_id,
    validate_token,
)

TOKEN = "123456789:" + "A" * 35
CHAT = "-1001234567890"


def success(chat_id: int = int(CHAT), message_id: int = 17) -> httpx.Response:
    return httpx.Response(
        200, json={"ok": True, "result": {"message_id": message_id, "chat": {"id": chat_id}}}
    )


def test_single_request_has_fixed_origin_plain_text_and_no_preview() -> None:
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "POST"
        assert request.url.scheme == "https"
        assert request.url.host == "api.telegram.org"
        assert request.url.path == "/bot" + TOKEN + "/sendMessage"
        assert not request.url.query
        payload = json.loads(request.content)
        assert payload == {
            "chat_id": int(CHAT),
            "text": "Hello <b>plain text</b>",
            "link_preview_options": {"is_disabled": True},
        }
        assert request.extensions["timeout"] == {
            "connect": 15.0,
            "read": 15.0,
            "write": 15.0,
            "pool": 15.0,
        }
        return success()

    with TelegramClient(TOKEN, transport=httpx.MockTransport(handle)) as client:
        assert client.send(CHAT, "Hello <b>plain text</b>") == 17
    assert len(calls) == 1


@pytest.mark.parametrize(
    "raw,expected",
    [("123", "123"), (" 00123 ", "123"), ("+123", "123"), ("-00123", "-123"), (CHAT, CHAT)],
)
def test_chat_id_is_canonical_and_numeric(raw: str, expected: str) -> None:
    assert normalize_chat_id(raw) == expected


@pytest.mark.parametrize(
    "raw", ["0", "-0", "@public_channel", "", "12 3", "１23", "1e3", str(2**52), "-" + str(2**52)]
)
def test_invalid_chat_id_is_rejected_before_transport(raw: str) -> None:
    def unexpected(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Invalid destinations must not reach HTTP")

    with TelegramClient(TOKEN, transport=httpx.MockTransport(unexpected)) as client:
        with pytest.raises(TelegramError) as caught:
            client.send(raw, "Hello")
    assert caught.value.outcome == "failed"
    assert caught.value.code == "invalid_chat_id"


@pytest.mark.parametrize("raw", ["", "secret", "123:short", "0:" + "A" * 35, TOKEN + "/evil"])
def test_token_validation_never_echoes_secret(raw: str) -> None:
    with pytest.raises(TelegramError) as caught:
        validate_token(raw)
    assert caught.value.code == "invalid_token"
    assert "secret" not in str(caught.value)
    assert TOKEN not in str(caught.value)


def test_token_trimming_and_client_repr_are_secret_safe() -> None:
    assert validate_token(" \n" + TOKEN + "\t") == TOKEN
    with TelegramClient(TOKEN, transport=httpx.MockTransport(lambda request: success())) as client:
        assert TOKEN not in repr(client)


@pytest.mark.parametrize("timeout", [0, -1, 61, 10**500, float("inf"), float("nan"), True])
def test_timeout_is_bounded(timeout: float) -> None:
    with pytest.raises(TelegramError) as caught:
        TelegramClient(TOKEN, timeout=timeout)
    assert caught.value.outcome == "failed"


@pytest.mark.parametrize("text", ["", "a" * 4097, "😀" * 2049, "bad\ud800text"])
def test_invalid_text_is_rejected_before_transport(text: str) -> None:
    with TelegramClient(TOKEN, transport=httpx.MockTransport(lambda request: success())) as client:
        with pytest.raises(TelegramError) as caught:
            client.send(CHAT, text)
    assert caught.value.code == "invalid_text"


def test_utf16_exact_boundary_is_allowed() -> None:
    with TelegramClient(TOKEN, transport=httpx.MockTransport(lambda request: success())) as client:
        assert client.send(CHAT, "😀" * 2048) == 17


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_explicit_client_error_is_failed_and_payload_is_not_exposed(status: int) -> None:
    reply = httpx.Response(
        status,
        json={"ok": False, "error_code": status, "description": "sensitive " + TOKEN},
    )
    with TelegramClient(TOKEN, transport=httpx.MockTransport(lambda request: reply)) as client:
        with pytest.raises(TelegramError) as caught:
            client.send(CHAT, "Hello")
    assert caught.value.outcome == "failed"
    assert TOKEN not in repr(caught.value)
    assert "sensitive" not in str(caught.value)


def test_confirmed_flood_control_is_retryable_without_client_retry() -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            429,
            json={"ok": False, "error_code": 429, "parameters": {"retry_after": 37}},
        )

    with TelegramClient(TOKEN, transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(TelegramError) as caught:
            client.send(CHAT, "Hello")
    assert calls == 1
    assert caught.value.outcome == "retryable"
    assert caught.value.code == "rate_limited"
    assert caught.value.retry_after == 37


@pytest.mark.parametrize("retry_after", [None, 0, -1, True, "5", 2.5, 604801, 10**100])
def test_unusable_flood_control_delay_is_not_blindly_retried(retry_after: object) -> None:
    reply = httpx.Response(
        429,
        json={"ok": False, "error_code": 429, "parameters": {"retry_after": retry_after}},
    )
    with TelegramClient(TOKEN, transport=httpx.MockTransport(lambda request: reply)) as client:
        with pytest.raises(TelegramError) as caught:
            client.send(CHAT, "Hello")
    assert caught.value.outcome == "delivery_unknown"
    assert caught.value.retry_after is None


@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(429, text="rate limited"),
        httpx.Response(429, json={"ok": False, "error_code": 429}),
        httpx.Response(500, json={"ok": False, "error_code": 500}),
        httpx.Response(
            503, json={"ok": False, "error_code": 429, "parameters": {"retry_after": 5}}
        ),
        httpx.Response(200, text="not JSON"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"ok": True}),
        httpx.Response(
            200, json={"ok": "true", "result": {"message_id": 1, "chat": {"id": int(CHAT)}}}
        ),
        httpx.Response(
            200, json={"ok": True, "result": {"message_id": True, "chat": {"id": int(CHAT)}}}
        ),
        httpx.Response(200, json={"ok": True, "result": {"message_id": 1, "chat": {"id": CHAT}}}),
        success(chat_id=123),
        success(message_id=0),
        success(message_id=-1),
        httpx.Response(302, headers={"Location": "https://evil.invalid/"}, json={"ok": True}),
    ],
)
def test_ambiguous_response_is_delivery_unknown_and_never_follows_redirect(
    reply: httpx.Response,
) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return reply

    with TelegramClient(TOKEN, transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(TelegramError) as caught:
            client.send(CHAT, "Hello")
    assert caught.value.outcome == "delivery_unknown"
    assert calls == 1


@pytest.mark.parametrize(
    "error_type,outcome",
    [
        (httpx.ConnectError, "retryable"),
        (httpx.ConnectTimeout, "retryable"),
        (httpx.PoolTimeout, "retryable"),
        (httpx.ReadTimeout, "delivery_unknown"),
        (httpx.WriteTimeout, "delivery_unknown"),
        (httpx.ReadError, "delivery_unknown"),
        (httpx.WriteError, "delivery_unknown"),
        (httpx.RemoteProtocolError, "delivery_unknown"),
        (httpx.LocalProtocolError, "delivery_unknown"),
        (ValueError, "delivery_unknown"),
    ],
)
def test_transport_failure_outcome_is_explicit_and_secrets_are_suppressed(
    error_type, outcome: str
) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise error_type("failed URL " + str(request.url))

    with TelegramClient(TOKEN, transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(TelegramError) as caught:
            client.send(CHAT, "Hello")
    assert calls == 1
    assert caught.value.outcome == outcome
    assert TOKEN not in repr(caught.value)
    assert "api.telegram.org" not in str(caught.value)
    assert caught.value.__suppress_context__


def test_chat_migration_requires_manual_confirmation() -> None:
    reply = httpx.Response(
        400,
        json={"ok": False, "error_code": 400, "parameters": {"migrate_to_chat_id": -100999}},
    )
    with TelegramClient(TOKEN, transport=httpx.MockTransport(lambda request: reply)) as client:
        with pytest.raises(TelegramError) as caught:
            client.send(CHAT, "Hello")
    assert caught.value.outcome == "failed"
    assert caught.value.code == "chat_migration_required"
    assert "100999" not in str(caught.value)


def test_httpx_info_logging_does_not_receive_the_token_url(caplog) -> None:
    caplog.set_level(logging.INFO, logger="httpx")
    logging.getLogger("httpx").info("Unrelated HTTPX logging remains enabled")
    with TelegramClient(TOKEN, transport=httpx.MockTransport(lambda request: success())) as client:
        assert client.send(CHAT, "Hello") == 17
    assert "Unrelated HTTPX logging remains enabled" in caplog.text
    assert TOKEN not in caplog.text
    assert "sendMessage" not in caplog.text


def test_default_transport_disables_ambient_proxy_and_retries(monkeypatch) -> None:
    kwargs_seen: dict[str, object] = {}

    def factory(**kwargs: object) -> httpx.MockTransport:
        kwargs_seen.update(kwargs)
        return httpx.MockTransport(lambda request: success())

    monkeypatch.setattr("nz_job_radar.telegram.httpx.HTTPTransport", factory)
    with TelegramClient(TOKEN) as client:
        assert client.send(CHAT, "Hello") == 17
    assert kwargs_seen == {"trust_env": False, "retries": 0}


def test_oversized_response_is_unknown() -> None:
    reply = httpx.Response(200, content=b"x" * 1_000_001)
    with TelegramClient(TOKEN, transport=httpx.MockTransport(lambda request: reply)) as client:
        with pytest.raises(TelegramError) as caught:
            client.send(CHAT, "Hello")
    assert caught.value.outcome == "delivery_unknown"


def test_even_connection_named_error_after_response_headers_is_delivery_unknown() -> None:
    class BrokenBody(httpx.SyncByteStream):
        def __iter__(self):
            raise httpx.ConnectError("provider URL " + TOKEN)
            yield b""  # pragma: no cover - marks the stream as an iterator

    reply = httpx.Response(200, stream=BrokenBody())
    with TelegramClient(TOKEN, transport=httpx.MockTransport(lambda request: reply)) as client:
        with pytest.raises(TelegramError) as caught:
            client.send(CHAT, "Hello")
    assert caught.value.outcome == "delivery_unknown"
    assert TOKEN not in str(caught.value)


def test_close_is_idempotent_and_closed_client_cannot_send() -> None:
    client = TelegramClient(TOKEN, transport=httpx.MockTransport(lambda request: success()))
    client.close()
    client.close()
    with pytest.raises(TelegramError) as caught:
        client.send(CHAT, "Hello")
    assert caught.value.code == "client_closed"
