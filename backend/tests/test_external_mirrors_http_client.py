# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""Tests for backend.app.external_mirrors.http_client."""

from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from backend.app.external_mirrors.http_client import (
    NONCE_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    VERSION_HEADER,
    MirrorHttpClient,
    canonical_json,
    sign_payload,
    verify_signature,
)


# ---------------------------------------------------------------------------
# Signing helpers
# ---------------------------------------------------------------------------

def test_canonical_json_is_deterministic():
    a = canonical_json({"b": 2, "a": [1, 2, 3]})
    b = canonical_json({"a": [1, 2, 3], "b": 2})
    assert a == b
    assert a == b'{"a":[1,2,3],"b":2}'


def test_sign_payload_matches_manual_hmac():
    secret = "supersecret"
    body = b'{"a":1}'
    ts = "2026-04-22T12:00:00Z"
    nonce = "abc123"
    expected = hmac.new(
        secret.encode(),
        ts.encode() + b"\n" + nonce.encode() + b"\n" + body,
        hashlib.sha256,
    ).hexdigest()
    assert sign_payload(secret, body, ts, nonce) == expected


def test_verify_signature_round_trip():
    secret = "k"
    body = b"hello"
    ts = "t"
    nonce = "n"
    sig = sign_payload(secret, body, ts, nonce)
    assert verify_signature(secret, body, ts, nonce, sig) is True
    assert verify_signature(secret, body, ts, nonce, "deadbeef") is False
    # Tampered timestamp invalidates.
    assert verify_signature(secret, body, "t2", nonce, sig) is False


def test_sign_payload_requires_secret():
    with pytest.raises(ValueError):
        sign_payload("", b"x", "t", "n")


# ---------------------------------------------------------------------------
# HTTP transport — success / 4xx / 5xx / network
# ---------------------------------------------------------------------------

def _make_client(handler, **kwargs):
    transport = httpx.MockTransport(handler)
    return MirrorHttpClient(
        transport=transport,
        sleep=lambda _s: None,  # no real sleeps in tests
        backoff_base_seconds=0.0,
        backoff_cap_seconds=0.0,
        **kwargs,
    )


def test_post_success_returns_ok_with_signed_headers():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content
        return httpx.Response(200, text='{"ok":true}')

    client = _make_client(handler)
    result = client.post(
        "https://mirror.example.com/ingest.php",
        {"events": [1, 2, 3]},
        secret_token="secret",
        mirror_name="primary",
    )
    assert result.success is True
    assert result.status_code == 200
    assert result.attempts == 1
    assert result.response_body == '{"ok":true}'
    assert captured["method"] == "POST"

    headers = captured["headers"]
    assert headers["x-4ham-mirror-name"] == "primary"
    assert headers[VERSION_HEADER.lower()]
    ts = headers[TIMESTAMP_HEADER.lower()]
    nonce = headers[NONCE_HEADER.lower()]
    sig = headers[SIGNATURE_HEADER.lower()]
    body = captured["body"]
    assert verify_signature("secret", body, ts, nonce, sig) is True
    # Body is canonical JSON (no whitespace).
    assert body == b'{"events":[1,2,3]}'


def test_post_4xx_does_not_retry():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, text="unauthorized")

    client = _make_client(handler, max_retries=3)
    result = client.post(
        "https://x", {"a": 1}, secret_token="k", mirror_name="m"
    )
    assert result.success is False
    assert result.status_code == 401
    assert result.attempts == 1
    assert calls["n"] == 1
    assert result.error == "http 401"
    assert result.response_body == "unauthorized"


def test_post_5xx_retries_up_to_budget():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="busy")

    client = _make_client(handler, max_retries=2)
    result = client.post("https://x", {"a": 1}, secret_token="k")
    assert result.success is False
    assert result.status_code == 503
    # initial + 2 retries = 3
    assert calls["n"] == 3
    assert result.attempts == 3


def test_post_5xx_then_200_succeeds():
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] < 3:
            return httpx.Response(500, text="oops")
        return httpx.Response(200, text="ok")

    client = _make_client(handler, max_retries=5)
    result = client.post("https://x", {"a": 1}, secret_token="k")
    assert result.success is True
    assert result.status_code == 200
    assert result.attempts == 3


def test_post_network_error_retries_then_fails():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("conn refused")

    client = _make_client(handler, max_retries=2)
    result = client.post("https://x", {"a": 1}, secret_token="k")
    assert result.success is False
    assert result.status_code is None
    assert calls["n"] == 3
    assert "transport" in (result.error or "")


def test_post_timeout_retries_then_fails():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("slow")

    client = _make_client(handler, max_retries=1)
    result = client.post("https://x", {"a": 1}, secret_token="k")
    assert result.success is False
    assert calls["n"] == 2
    assert "timeout" in (result.error or "")


def test_post_response_body_truncated():
    big = "X" * 5000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=big)

    client = _make_client(handler)
    result = client.post("https://x", {"a": 1}, secret_token="k")
    assert result.success is True
    assert result.response_body is not None
    assert len(result.response_body) <= 2100
    assert result.response_body.endswith("...[truncated]")


def test_default_verify_tls_true():
    client = MirrorHttpClient()
    assert client._verify is True
