"""No test may accidentally reach a real network or paid provider."""

import socket
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Real network calls are forbidden in this test suite")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
