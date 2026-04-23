# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""
Async pusher loop for external mirrors.

A single ``ExternalMirrorPusher`` instance owns one asyncio task.
On every tick it lists enabled mirrors and, for each one whose
``push_interval_seconds`` has elapsed since ``last_push_at``, builds a
payload and POSTs it via ``MirrorHttpClient`` (off-thread, since httpx
is sync here). Bookkeeping (watermark, consecutive_failures, audit) is
delegated to ``ExternalMirrorRepository.update_after_push``.

The pusher MUST NOT raise: any unexpected error is swallowed and
logged so the loop survives.

Token storage: tokens are bcrypt-hashed at rest. To sign requests we
need the plaintext, which the repository does NOT keep. We therefore
read it from a memory-only cache populated on:
  * mirror creation (returned plaintext registered into the cache),
  * token rotation (idem).
On process restart, mirrors with no cached token are skipped (and
audit-logged once). The user can rotate the token from the Admin UI to
re-arm the mirror.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Dict, Optional

from .http_client import MirrorHttpClient, PushResult
from .payload import build_payload, has_new_data
from .repository import ExternalMirror, ExternalMirrorRepository
from .token_vault import TokenVault

logger = logging.getLogger(__name__)

DEFAULT_TICK_SECONDS = 15.0


class TokenCache:
    """In-memory mapping mirror_id -> plaintext token.

    When constructed with both ``repository`` and ``vault``, the cache also
    persists the encrypted plaintext alongside each mirror so that the pusher
    survives backend restarts without operator intervention. With either
    missing it degrades to memory-only (legacy behaviour).
    """

    def __init__(
        self,
        *,
        repository: Optional[ExternalMirrorRepository] = None,
        vault: Optional[TokenVault] = None,
    ) -> None:
        self._tokens: Dict[int, str] = {}
        self._lock = threading.Lock()
        self._repo = repository
        self._vault = vault

    def set(self, mirror_id: int, token: str) -> None:
        mid = int(mirror_id)
        with self._lock:
            self._tokens[mid] = token
        if self._repo is not None and self._vault is not None:
            try:
                self._repo.set_token_ciphertext(mid, self._vault.encrypt(token))
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to persist encrypted token for mirror %d: %s", mid, exc
                )

    def get(self, mirror_id: int) -> Optional[str]:
        with self._lock:
            return self._tokens.get(int(mirror_id))

    def drop(self, mirror_id: int) -> None:
        mid = int(mirror_id)
        with self._lock:
            self._tokens.pop(mid, None)
        if self._repo is not None:
            try:
                self._repo.set_token_ciphertext(mid, None)
            except Exception:  # pragma: no cover - defensive
                pass

    def known_ids(self) -> set:
        with self._lock:
            return set(self._tokens.keys())

    def load_persisted(self) -> int:
        """Decrypt and load any persisted plaintext tokens. Returns count loaded."""
        if self._repo is None or self._vault is None:
            return 0
        loaded = 0
        for mirror_id, ciphertext in self._repo.iter_token_ciphertexts():
            try:
                plaintext = self._vault.decrypt(ciphertext)
            except Exception as exc:
                logger.warning(
                    "Failed to decrypt persisted token for mirror %d (%s) \u2014 "
                    "rotate from Admin to re-arm.",
                    mirror_id,
                    exc.__class__.__name__,
                )
                continue
            with self._lock:
                self._tokens[int(mirror_id)] = plaintext
            loaded += 1
        return loaded


class ExternalMirrorPusher:
    def __init__(
        self,
        *,
        repo: ExternalMirrorRepository,
        token_cache: TokenCache,
        http_client: Optional[MirrorHttpClient] = None,
        tick_seconds: float = DEFAULT_TICK_SECONDS,
    ) -> None:
        self._repo = repo
        self._tokens = token_cache
        self._http = http_client or MirrorHttpClient()
        self._tick = max(1.0, float(tick_seconds))
        self._task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._warned_missing_token: set = set()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="external-mirror-pusher")
        logger.info("ExternalMirrorPusher: started (tick=%.1fs)", self._tick)

    async def stop(self) -> None:
        if not self._task:
            return
        if self._stop_event:
            self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=10.0)
        except asyncio.TimeoutError:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        self._stop_event = None
        logger.info("ExternalMirrorPusher: stopped")

    async def _run(self) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            try:
                await self._tick_once()
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("ExternalMirrorPusher tick failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._tick)
            except asyncio.TimeoutError:
                continue
            else:
                break

    async def _tick_once(self) -> None:
        mirrors = await asyncio.to_thread(self._repo.list, include_disabled=False)
        for mirror in mirrors:
            if not mirror.enabled:
                continue
            if not self._is_due(mirror):
                continue
            await self._push_one(mirror)

    def _is_due(self, mirror: ExternalMirror) -> bool:
        if not mirror.last_push_at:
            return True
        try:
            from datetime import datetime, timezone

            last = datetime.fromisoformat(mirror.last_push_at.replace("Z", "+00:00"))
            elapsed = (datetime.now(timezone.utc) - last).total_seconds()
        except Exception:
            return True
        return elapsed >= float(mirror.push_interval_seconds)

    async def _push_one(self, mirror: ExternalMirror) -> None:
        token = self._tokens.get(mirror.id)
        if not token:
            if mirror.id not in self._warned_missing_token:
                self._warned_missing_token.add(mirror.id)
                logger.warning(
                    "Mirror '%s' (id=%d) has no cached token — rotate from Admin to re-arm.",
                    mirror.name,
                    mirror.id,
                )
                try:
                    await asyncio.to_thread(
                        self._repo.log_event,
                        mirror.id,
                        "skipped_no_token",
                        None,
                        {"reason": "Plaintext token not cached (process restart)."},
                    )
                except Exception:
                    pass
            return

        # Build payload off the event loop.
        payload = await asyncio.to_thread(
            build_payload,
            self._repo._db,
            mirror_name=mirror.name,
            last_watermark=mirror.last_push_watermark,
            scopes=mirror.data_scopes,
        )
        if not has_new_data(payload) and mirror.last_push_at:
            # Even with no new data, we still POST a heartbeat so the
            # receiver knows the source is alive — but only when due.
            # Receiver can short-circuit on counts == 0.
            pass

        result: PushResult = await asyncio.to_thread(
            self._http.post,
            mirror.endpoint_url,
            payload,
            secret_token=token,
            mirror_name=mirror.name,
        )

        new_watermark = int(payload["meta"]["new_watermark"])
        await asyncio.to_thread(
            self._repo.update_after_push,
            mirror.id,
            success=result.success,
            watermark=new_watermark if result.success else None,
            status_msg=result.status_message,
        )
        if result.success:
            logger.info(
                "Mirror push OK: name=%s id=%d status=%s attempts=%d watermark=%d events=%d/%d elapsed=%dms",
                mirror.name,
                mirror.id,
                result.status_code,
                result.attempts,
                new_watermark,
                payload["counts"].get("callsign", 0),
                payload["counts"].get("occupancy", 0),
                result.elapsed_ms,
            )
        else:
            logger.warning(
                "Mirror push FAILED: name=%s id=%d status=%s attempts=%d error=%s",
                mirror.name,
                mirror.id,
                result.status_code,
                result.attempts,
                result.error,
            )


__all__ = [
    "DEFAULT_TICK_SECONDS",
    "ExternalMirrorPusher",
    "TokenCache",
]
