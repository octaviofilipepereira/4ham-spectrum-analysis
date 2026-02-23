# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 18:45:00 UTC

from datetime import datetime, timezone


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


class Ft8SlotTracker:
    def __init__(self, slot_seconds=15, min_hits=2, freq_tolerance_hz=40.0, max_slots=6):
        self.slot_seconds = max(5, int(slot_seconds))
        self.min_hits = max(1, int(min_hits))
        self.freq_tolerance_hz = max(1.0, float(freq_tolerance_hz))
        self.max_slots = max(2, int(max_slots))

        self._slots = {}
        self._total_locked = 0
        self._last_lock_at = None
        self._last_locked_tracks = []

    def _slot_start_epoch(self, now):
        if isinstance(now, datetime):
            ts = now.timestamp()
        else:
            ts = _safe_float(now, default=0.0)
        return int(ts // self.slot_seconds) * self.slot_seconds

    def _get_slot(self, slot_epoch):
        slot_key = str(int(slot_epoch))
        slot = self._slots.get(slot_key)
        if slot is None:
            slot = {"slot_epoch": int(slot_epoch), "tracks": []}
            self._slots[slot_key] = slot
        return slot

    def _find_track(self, tracks, frequency_hz, mode):
        target = float(frequency_hz)
        mode_text = str(mode or "").strip().upper() or "FT8"
        for track in tracks:
            if str(track.get("mode") or "").strip().upper() != mode_text:
                continue
            if abs(float(track.get("frequency_hz", 0)) - target) <= self.freq_tolerance_hz:
                return track
        return None

    def _cleanup_slots(self):
        if len(self._slots) <= self.max_slots:
            return
        ordered = sorted(self._slots.values(), key=lambda item: int(item.get("slot_epoch", 0)), reverse=True)
        keep = {str(int(item.get("slot_epoch", 0))) for item in ordered[: self.max_slots]}
        for key in list(self._slots.keys()):
            if key not in keep:
                self._slots.pop(key, None)

    def update(self, now, candidates):
        slot_epoch = self._slot_start_epoch(now)
        slot = self._get_slot(slot_epoch)
        tracks = slot["tracks"]
        locked = []

        for candidate in list(candidates or []):
            if not isinstance(candidate, dict):
                continue
            frequency_hz = _safe_int(candidate.get("frequency_hz"), default=0)
            if frequency_hz <= 0:
                continue
            mode = str(candidate.get("mode") or "").strip().upper() or "FT8"
            confidence = _safe_float(candidate.get("confidence"), default=0.0)
            snr_db = _safe_float(candidate.get("snr_db"), default=0.0)

            track = self._find_track(tracks, frequency_hz, mode)
            if track is None:
                track = {
                    "mode": mode,
                    "frequency_hz": frequency_hz,
                    "hits": 0,
                    "best_confidence": 0.0,
                    "best_snr_db": -999.0,
                    "locked": False,
                    "last_seen_at": None,
                }
                tracks.append(track)

            prev_hits = int(track.get("hits", 0))
            track["hits"] = prev_hits + 1
            track["mode"] = mode
            track["frequency_hz"] = int(round((track.get("frequency_hz", frequency_hz) * prev_hits + frequency_hz) / max(1, track["hits"])))
            track["best_confidence"] = max(_safe_float(track.get("best_confidence"), default=0.0), confidence)
            track["best_snr_db"] = max(_safe_float(track.get("best_snr_db"), default=-999.0), snr_db)
            track["last_seen_at"] = datetime.now(timezone.utc).isoformat()

            if not bool(track.get("locked")) and track["hits"] >= self.min_hits:
                track["locked"] = True
                locked_track = {
                    "slot_epoch": int(slot_epoch),
                    "mode": str(track.get("mode") or "FT8"),
                    "frequency_hz": int(track["frequency_hz"]),
                    "hits": int(track["hits"]),
                    "best_confidence": round(_safe_float(track.get("best_confidence"), default=0.0), 3),
                    "best_snr_db": round(_safe_float(track.get("best_snr_db"), default=0.0), 2),
                }
                locked.append(locked_track)

        if locked:
            self._total_locked += len(locked)
            self._last_lock_at = datetime.now(timezone.utc).isoformat()
            self._last_locked_tracks = list(locked)

        self._cleanup_slots()
        return locked

    def snapshot(self):
        active_tracks = sum(len(item.get("tracks", [])) for item in self._slots.values())
        return {
            "slot_seconds": int(self.slot_seconds),
            "min_hits": int(self.min_hits),
            "freq_tolerance_hz": float(self.freq_tolerance_hz),
            "active_slots": int(len(self._slots)),
            "active_tracks": int(active_tracks),
            "total_locked": int(self._total_locked),
            "last_lock_at": self._last_lock_at,
            "last_locked_tracks": list(self._last_locked_tracks),
        }
