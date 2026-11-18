"""Single-attempt Telegram transport with explicit delivery uncertainty.

The persisted dispatcher owns retries. This module uses HTTPX's transport
directly so HTTPX's Client INFO logger never receives a token-bearing URL.
"""

from __future__ import annotations

import json
import math
import re
from typing import Literal

import httpx

_TOKEN = re.compile(r"[1-9][0-9]{0,19}:[A-Za-z0-9_-]{20,128}\Z")
_CHAT_ID = re.compile(r"[+-]?[0-9]{1,20}\Z")
_MAX_RESPONSE_BYTES = 1_000_000


class TelegramError(Exception):
    """Locally authored error text; never include provider payloads or URLs."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        outcome: Literal["retryable", "failed", "delivery_unknown"],
        retry_after: int | None = None,
    ) -> None:
        self.code = code
        self.outcome = outcome
        self.retry_after = retry_after
        super().__init__(message)


def validate_token(value: str) -> str:
    """Validate an explicit Bot token without reading settings or opening HTTP."""
    if not isinstance(value, str) or _TOKEN.fullmatch(value.strip()) is None:
        raise TelegramError(
            "invalid_token", "A valid Telegram Bot token is required.", outcome="failed"
        )
    return value.strip()


def normalize_chat_id(value: str) -> str:
    """Canonical numeric destination, within Telegram's 52 significant bits."""
    if not isinstance(value, str) or _CHAT_ID.fullmatch(value.strip()) is None:
        raise TelegramError(
            "invalid_chat_id", "A numeric Telegram chat ID is required.", outcome="failed"
        )
    numeric = int(value.strip())
    if numeric == 0 or abs(numeric) >= 2**52:
        raise TelegramError(
            "invalid_chat_id",
            "The Telegram chat ID is outside the supported range.",
            outcome="failed",
        )
    return str(numeric)


def _unknown(code: str = "delivery_unknown") -> TelegramError:
    return TelegramError(
        code,
        "Telegram delivery could not be confirmed; review this notification before resending.",
        outcome="delivery_unknown",
    )


def _result(status: int, payload: object, chat_id: int) -> int:
    if status >= 500 or not isinstance(payload, dict):
        raise _unknown("invalid_response")
    if status == 200 and payload.get("ok") is True:
        result = payload.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("chat"), dict):
            raise _unknown("invalid_response")
        message_id = result.get("message_id")
        returned_chat = result["chat"].get("id")
        if (
            type(message_id) is not int
            or message_id <= 0
            or type(returned_chat) is not int
            or returned_chat != chat_id
        ):
            raise _unknown("invalid_response")
        return message_id
    if status == 429 and payload.get("ok") is False and payload.get("error_code") == 429:
        parameters = payload.get("parameters")
        retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
        if type(retry_after) is int and 1 <= retry_after <= 7 * 24 * 60 * 60:
            raise TelegramError(
                "rate_limited",
                "Telegram rejected this send due to flood control; retry after the recorded delay.",
                outcome="retryable",
                retry_after=retry_after,
            )
        raise _unknown("invalid_response")
    if 400 <= status < 500 and status != 429 and payload.get("ok") is False:
        parameters = payload.get("parameters")
        if isinstance(parameters, dict) and "migrate_to_chat_id" in parameters:
            raise TelegramError(
                "chat_migration_required",
                "Telegram requires a destination change; confirm the new chat ID manually.",
                outcome="failed",
            )
        if status in {401, 403}:
            raise TelegramError(
                "access_denied",
                "Telegram rejected access; check the bot credentials and destination permissions.",
                outcome="failed",
            )
        raise TelegramError(
            "request_rejected", "Telegram explicitly rejected the notification.", outcome="failed"
        )
    raise _unknown("invalid_response")


class TelegramClient:
    """One HTTPS attempt per send; no redirects, ambient proxies, or automatic retries."""

    def __init__(
        self,
        token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        token = validate_token(token)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not 0 < timeout <= 60
            or not math.isfinite(timeout)
        ):
            raise TelegramError(
                "invalid_timeout",
                "Telegram timeout must be between 0 and 60 seconds.",
                outcome="failed",
            )
        self._url = "https://api.telegram.org/bot" + token + "/sendMessage"
        self._timeout = float(timeout)
        self._transport = (
            transport if transport is not None else httpx.HTTPTransport(trust_env=False, retries=0)
        )
        self._closed = False

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._transport.close()

    def __enter__(self) -> TelegramClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def send(self, chat_id: str, text: str) -> int:
        if self._closed:
            raise TelegramError("client_closed", "The Telegram client is closed.", outcome="failed")
        destination = int(normalize_chat_id(chat_id))
        if (
            not isinstance(text, str)
            or not 1 <= sum(2 if ord(c) > 0xFFFF else 1 for c in text) <= 4096
        ):
            raise TelegramError(
                "invalid_text",
                "Telegram text must contain 1 to 4096 UTF-16 units.",
                outcome="failed",
            )
        if any(0xD800 <= ord(char) <= 0xDFFF for char in text):
            raise TelegramError(
                "invalid_text", "Telegram text contains invalid Unicode.", outcome="failed"
            )
        request = httpx.Request(
            "POST",
            self._url,
            json={
                "chat_id": destination,
                "text": text,
                "link_preview_options": {"is_disabled": True},
            },
            extensions={"timeout": httpx.Timeout(self._timeout).as_dict()},
        )
        response_started = False
        try:
            response = self._transport.handle_request(request)
            response_started = True
            try:
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > _MAX_RESPONSE_BYTES:
                        raise _unknown("invalid_response")
                    chunks.append(chunk)
                status = response.status_code
                try:
                    payload = json.loads(b"".join(chunks))
                except (ValueError, UnicodeError):
                    raise _unknown("invalid_response") from None
            finally:
                response.close()
        except TelegramError:
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            if response_started:
                raise _unknown() from None
            raise TelegramError(
                "connection_unavailable",
                "Telegram could not be reached before sending; this notification can be retried.",
                outcome="retryable",
            ) from None
        except Exception:
            # Read/write/protocol failures cannot prove the message was not sent.
            # Never expose transport exceptions because they may contain token URLs.
            raise _unknown() from None
        return _result(status, payload, destination)
