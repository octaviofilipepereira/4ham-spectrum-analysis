# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""
HTTP client used by the external mirrors pusher.

Responsibilities:
  * Serialise a payload to deterministic JSON.
  * Sign it with HMAC-SHA256 using the mirror's plaintext token as the
    shared secret. The signature covers ``timestamp + "\n" + nonce + "\n" + body``
    so that replays with a different timestamp/nonce are rejected by
    the receiver.
  * Send the POST with TLS verification, a configurable timeout and
    bounded retries with exponential backoff on transient failures.
  * Never raise on network/HTTP errors — always return a structured
    ``PushResult`` so callers can persist bookkeeping.

This module deliberately has no knowledge of the database. It can be
unit-tested with httpx's MockTransport.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx

from ..version import APP_VERSION

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE_SECONDS = 0.5
DEFAULT_BACKOFF_CAP_SECONDS = 8.0

SIGNATURE_HEADER = "X-4HAM-Signature"
TIMESTAMP_HEADER = "X-4HAM-Timestamp"
NONCE_HEADER = "X-4HAM-Nonce"
VERSION_HEADER = "X-4HAM-Mirror-Version"
MIRROR_NAME_HEADER = "X-4HAM-Mirror-Name"


def canonical_json(payload: Any) -> bytes:
    """Deterministic JSON encoding used for signing and transport."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _signing_string(timestamp: str, nonce: str, body: bytes) -> bytes:
    return timestamp.encode("ascii") + b"\n" + nonce.encode("ascii") + b"\n" + body


def sign_payload(secret: str, body: bytes, timestamp: str, nonce: str) -> str:
    """Return the hex HMAC-SHA256 signature over (timestamp, nonce, body)."""
    if not secret:
        raise ValueError("secret is required for signing")
    msg = _signing_string(timestamp, nonce, body)
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify_signature(
    secret: str,
    body: bytes,
    timestamp: str,
    nonce: str,
    received_signature: str,
) -> bool:
    """Constant-time verification helper (mirrors what the receiver does)."""
    expected = sign_payload(secret, body, timestamp, nonce)
    return hmac.compare_digest(expected, received_signature or "")


@dataclass
class PushResult:
    success: bool
    status_code: Optional[int]
    attempts: int
    error: Optional[str]
    response_body: Optional[str]
    elapsed_ms: int

    @property
    def status_message(self) -> str:
        if self.success:
            return "ok"
        if self.error:
            return self.error[:200]
        if self.status_code is not None:
            return f"http {self.status_code}"
        return "unknown error"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_nonce() -> str:
    return secrets.token_hex(16)


class MirrorHttpClient:
    """
    Thin synchronous HTTP client wrapping httpx.

    The synchronous API is intentional: the pusher will run inside its own
    thread and call this synchronously. This keeps the unit tests trivial.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS,
        backoff_cap_seconds: float = DEFAULT_BACKOFF_CAP_SECONDS,
        verify_tls: bool = True,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Optional[Any] = None,
    ) -> None:
        self._timeout = float(timeout_seconds)
        self._max_retries = max(0, int(max_retries))
        self._backoff_base = max(0.0, float(backoff_base_seconds))
        self._backoff_cap = max(self._backoff_base, float(backoff_cap_seconds))
        self._verify = verify_tls
        self._transport = transport
        self._sleep = sleep or time.sleep

    def _build_client(self) -> httpx.Client:
        kwargs: Dict[str, Any] = {
            "timeout": self._timeout,
            "verify": self._verify,
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.Client(**kwargs)

    def _backoff(self, attempt: int) -> float:
        # Exponential: base, base*2, base*4, ... capped. Attempt is 1-based.
        delay = self._backoff_base * (2 ** max(0, attempt - 1))
        return min(delay, self._backoff_cap)

    def post(
        self,
        endpoint_url: str,
        payload: Dict[str, Any],
        *,
        secret_token: str,
        mirror_name: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> PushResult:
        body = canonical_json(payload)
        timestamp = _utc_timestamp()
        nonce = _new_nonce()
        signature = sign_payload(secret_token, body, timestamp, nonce)

        headers: Dict[str, str] = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": f"4ham-mirror/{APP_VERSION}",
            VERSION_HEADER: APP_VERSION,
            TIMESTAMP_HEADER: timestamp,
            NONCE_HEADER: nonce,
            SIGNATURE_HEADER: signature,
        }
        if mirror_name:
            headers[MIRROR_NAME_HEADER] = mirror_name
        if extra_headers:
            headers.update(extra_headers)

        start = time.monotonic()
        last_error: Optional[str] = None
        last_status: Optional[int] = None
        last_body: Optional[str] = None
        attempts = 0

        with self._build_client() as client:
            for attempt in range(1, self._max_retries + 2):  # +1 initial try
                attempts = attempt
                try:
                    response = client.post(endpoint_url, content=body, headers=headers)
                except httpx.TimeoutException as exc:
                    last_error = f"timeout: {exc}"
                    last_status = None
                    if attempt > self._max_retries:
                        break
                    self._sleep(self._backoff(attempt))
                    continue
                except httpx.TransportError as exc:
                    last_error = f"transport: {exc}"
                    last_status = None
                    if attempt > self._max_retries:
                        break
                    self._sleep(self._backoff(attempt))
                    continue
                except httpx.HTTPError as exc:  # pragma: no cover - defensive
                    last_error = f"http: {exc}"
                    last_status = None
                    if attempt > self._max_retries:
                        break
                    self._sleep(self._backoff(attempt))
                    continue

                last_status = response.status_code
                last_body = _truncate(response.text, 2000)

                if 200 <= response.status_code < 300:
                    elapsed_ms = int((time.monotonic() - start) * 1000)
                    return PushResult(
                        success=True,
                        status_code=response.status_code,
                        attempts=attempt,
                        error=None,
                        response_body=last_body,
                        elapsed_ms=elapsed_ms,
                    )

                # 4xx: non-retryable (auth/format problems). Do not retry.
                if 400 <= response.status_code < 500:
                    last_error = f"http {response.status_code}"
                    break

                # 5xx: retry up to budget.
                last_error = f"http {response.status_code}"
                if attempt > self._max_retries:
                    break
                self._sleep(self._backoff(attempt))

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return PushResult(
            success=False,
            status_code=last_status,
            attempts=attempts,
            error=last_error or "unknown error",
            response_body=last_body,
            elapsed_ms=elapsed_ms,
        )


def _truncate(text: Optional[str], limit: int) -> Optional[str]:
    if text is None:
        return None
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_MAX_RETRIES",
    "MIRROR_NAME_HEADER",
    "MirrorHttpClient",
    "NONCE_HEADER",
    "PushResult",
    "SIGNATURE_HEADER",
    "TIMESTAMP_HEADER",
    "VERSION_HEADER",
    "canonical_json",
    "sign_payload",
    "verify_signature",
]
