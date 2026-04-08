# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

"""
Scan Rotation Scheduler
=======================
Cycles through a user-defined sequence of band+mode slots, spending a
configurable dwell time on each before advancing to the next.

Two rotation strategies are supported:

* **bands** — each slot specifies a band *and* a mode
  (e.g. 20m/FT8 → 40m/FT8 → 20m/CW).
* **modes** — all slots share the same band, only the mode changes
  (e.g. 20m/FT8 → 20m/CW → 20m/WSPR).

The scheduler does NOT touch the SDR or decoders directly.  Instead it
calls into the scan API layer (which already handles band lookup,
subband clipping, decoder lifecycle, etc.) via injected async
callbacks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)

# Minimum dwell per mode to respect decoder cycle times (seconds).
_MIN_DWELL_S: Dict[str, int] = {
    "ft8": 15,
    "ft4": 8,
    "wspr": 120,
    "cw": 10,
    "ssb": 15,
}
_DEFAULT_MIN_DWELL_S = 10


@dataclass
class RotationSlot:
    """One step in the rotation sequence."""
    band: str          # e.g. "20m"
    mode: str          # e.g. "ft8"
    dwell_s: int = 60  # seconds to stay on this slot


@dataclass
class RotationConfig:
    """Full rotation configuration."""
    slots: List[RotationSlot] = field(default_factory=list)
    # If true, loop forever; if false, stop after one pass.
    loop: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RotationConfig":
        """Build a RotationConfig from an API payload.

        Accepted shapes
        ---------------
        **Multi-band** (``rotation_mode == "bands"``):
        ```json
        {
          "rotation_mode": "bands",
          "dwell_s": 120,
          "slots": [
            {"band": "20m", "mode": "ft8"},
            {"band": "40m", "mode": "ft8", "dwell_s": 60}
          ],
          "loop": true
        }
        ```

        **Single-band multi-mode** (``rotation_mode == "modes"``):
        ```json
        {
          "rotation_mode": "modes",
          "band": "20m",
          "dwell_s": 60,
          "modes": ["ft8", "cw", "wspr"]
        }
        ```
        """
        rotation_mode = str(data.get("rotation_mode", "bands")).strip().lower()
        default_dwell = int(data.get("dwell_s", 60) or 60)
        do_loop = bool(data.get("loop", True))

        slots: List[RotationSlot] = []

        if rotation_mode == "modes":
            band = str(data.get("band", "")).strip()
            if not band:
                raise ValueError("rotation_mode 'modes' requires a 'band' field")
            modes = data.get("modes", [])
            if not modes or not isinstance(modes, list):
                raise ValueError("rotation_mode 'modes' requires a 'modes' list")
            for m in modes:
                mode = str(m).strip().lower()
                dwell = _clamp_dwell(mode, default_dwell)
                slots.append(RotationSlot(band=band, mode=mode, dwell_s=dwell))
        else:
            raw_slots = data.get("slots", [])
            if not raw_slots or not isinstance(raw_slots, list):
                raise ValueError("rotation_mode 'bands' requires a 'slots' list")
            for s in raw_slots:
                band = str(s.get("band", "")).strip()
                mode = str(s.get("mode", "")).strip().lower()
                if not band or not mode:
                    raise ValueError("Each slot must have 'band' and 'mode'")
                slot_dwell = int(s.get("dwell_s", default_dwell) or default_dwell)
                dwell = _clamp_dwell(mode, slot_dwell)
                slots.append(RotationSlot(band=band, mode=mode, dwell_s=dwell))

        if len(slots) < 2:
            raise ValueError("Rotation requires at least 2 slots")

        return cls(slots=slots, loop=do_loop)


def _clamp_dwell(mode: str, requested: int) -> int:
    """Ensure dwell respects the minimum for the given mode."""
    minimum = _MIN_DWELL_S.get(mode, _DEFAULT_MIN_DWELL_S)
    return max(requested, minimum)


# Type alias for the async callback the scheduler calls when
# it's time to switch to a new slot.
SwitchCallback = Callable[[RotationSlot], Coroutine[Any, Any, bool]]


class ScanRotation:
    """Orchestrates timed cycling through rotation slots.

    Usage
    -----
    ```python
    rotation = ScanRotation(config, switch_callback)
    await rotation.start()   # begins cycling
    await rotation.stop()    # stops (scan stays on current slot)
    ```
    """

    def __init__(
        self,
        config: RotationConfig,
        switch_cb: SwitchCallback,
    ) -> None:
        self.config = config
        self._switch_cb = switch_cb
        self._current_index: int = 0
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._slot_started_at: float = 0.0

    # ── Public interface ──────────────────────────────────────────

    @property
    def running(self) -> bool:
        return self._running

    @property
    def current_slot(self) -> Optional[RotationSlot]:
        if not self.config.slots:
            return None
        return self.config.slots[self._current_index]

    @property
    def next_slot(self) -> Optional[RotationSlot]:
        if not self.config.slots:
            return None
        idx = (self._current_index + 1) % len(self.config.slots)
        return self.config.slots[idx]

    @property
    def time_remaining_s(self) -> float:
        if not self._running or not self.current_slot:
            return 0.0
        elapsed = time.monotonic() - self._slot_started_at
        remaining = self.current_slot.dwell_s - elapsed
        return max(0.0, remaining)

    async def start(self) -> bool:
        """Start rotation from the first slot."""
        if self._running:
            return False
        if not self.config.slots:
            return False
        self._current_index = 0
        self._running = True
        self._slot_started_at = time.monotonic()
        self._task = asyncio.create_task(self._rotation_loop())
        logger.info(
            "rotation_started slots=%d loop=%s",
            len(self.config.slots),
            self.config.loop,
        )
        return True

    async def stop(self) -> bool:
        """Stop rotation. The scan stays on whatever slot is active."""
        if not self._running:
            return False
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("rotation_stopped at_slot=%d", self._current_index)
        return True

    def status(self) -> Dict[str, Any]:
        """Return a JSON-serialisable status snapshot."""
        current = self.current_slot
        nxt = self.next_slot
        return {
            "running": self._running,
            "current_index": self._current_index,
            "total_slots": len(self.config.slots),
            "current_slot": {
                "band": current.band,
                "mode": current.mode,
                "dwell_s": current.dwell_s,
            } if current else None,
            "next_slot": {
                "band": nxt.band,
                "mode": nxt.mode,
                "dwell_s": nxt.dwell_s,
            } if nxt else None,
            "time_remaining_s": round(self.time_remaining_s, 1),
            "loop": self.config.loop,
            "slots": [
                {"band": s.band, "mode": s.mode, "dwell_s": s.dwell_s}
                for s in self.config.slots
            ],
        }

    # ── Internal loop ─────────────────────────────────────────────

    async def _rotation_loop(self) -> None:
        """Main scheduler loop — activate slot, wait dwell, advance."""
        try:
            while self._running:
                slot = self.config.slots[self._current_index]
                self._slot_started_at = time.monotonic()

                logger.info(
                    "rotation_slot band=%s mode=%s dwell=%ds index=%d/%d",
                    slot.band, slot.mode, slot.dwell_s,
                    self._current_index + 1, len(self.config.slots),
                )

                try:
                    ok = await self._switch_cb(slot)
                    if not ok:
                        logger.warning(
                            "rotation_switch_failed band=%s mode=%s — skipping",
                            slot.band, slot.mode,
                        )
                except Exception:
                    logger.exception(
                        "rotation_switch_error band=%s mode=%s",
                        slot.band, slot.mode,
                    )

                # Wait for the dwell period
                await asyncio.sleep(slot.dwell_s)

                # Advance to next slot
                self._current_index = (
                    (self._current_index + 1) % len(self.config.slots)
                )

                # If not looping and we wrapped around, stop
                if not self.config.loop and self._current_index == 0:
                    logger.info("rotation_single_pass_complete")
                    self._running = False
                    break

        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
