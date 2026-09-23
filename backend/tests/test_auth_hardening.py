"""Pure tests for the request-hardening helpers (no DB, no network)."""

import httpx
import pytest

from backend.routers.applications import _client_ip
from backend.sources import instagram


class _Req:
    def __init__(self, xff=None, host="10.0.0.9"):
        self.headers = {"x-forwarded-for": xff} if xff else {}
        self.client = type("C", (), {"host": host})()


def test_client_ip_uses_the_proxy_appended_hop_not_the_client_supplied_one():
    # nginx appends the connecting address last; the first value is whatever the
    # caller put there, so a script cannot pick its own bucket.
    assert _client_ip(_Req("1.2.3.4, 203.0.113.7")) == "203.0.113.7"
    assert _client_ip(_Req("203.0.113.7")) == "203.0.113.7"
    assert _client_ip(_Req(None)) == "10.0.0.9"


def test_client_ip_ignores_blank_segments():
    assert _client_ip(_Req(" , 203.0.113.7 ")) == "203.0.113.7"


def test_token_exchange_error_never_echoes_the_request(monkeypatch):
    class _Resp:
        status_code = 400
        text = '{"error":{"message":"Invalid OAuth access token."}}'

    def fake_get(url, params=None, timeout=None):
        return _Resp()

    monkeypatch.setattr(instagram.httpx, "get", fake_get)
    with pytest.raises(RuntimeError) as exc:
        instagram.exchange_token("https://example.invalid/oauth/access_token",
                                 {"client_secret": "SECRETVALUE", "fb_exchange_token": "TOKENVALUE"})
    msg = str(exc.value)
    assert "HTTP 400" in msg and "Invalid OAuth" in msg
    assert "SECRETVALUE" not in msg and "TOKENVALUE" not in msg and "client_secret" not in msg


def test_token_exchange_transport_error_is_reduced_to_its_type(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        raise httpx.ConnectError("boom", request=httpx.Request("GET", url, params=params))

    monkeypatch.setattr(instagram.httpx, "get", fake_get)
    with pytest.raises(RuntimeError) as exc:
        instagram.exchange_token("https://example.invalid/oauth/access_token", {"client_secret": "SECRETVALUE"})
    assert str(exc.value) == "token exchange request failed: ConnectError"
    # `raise ... from None` keeps the httpx exception (and its URL) out of the
    # rendered traceback.
    assert exc.value.__cause__ is None and exc.value.__suppress_context__
