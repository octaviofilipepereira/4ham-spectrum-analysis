# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

"""Tests for the scan rotation scheduler."""

import asyncio
import pytest
from app.scan.rotation import RotationConfig, RotationSlot, ScanRotation, _clamp_dwell


# ── RotationConfig.from_dict ─────────────────────────────────────

class TestRotationConfig:

    def test_bands_mode_basic(self):
        cfg = RotationConfig.from_dict({
            "rotation_mode": "bands",
            "dwell_s": 60,
            "slots": [
                {"band": "20m", "mode": "ft8"},
                {"band": "40m", "mode": "cw"},
            ],
        })
        assert len(cfg.slots) == 2
        assert cfg.slots[0].band == "20m"
        assert cfg.slots[0].mode == "ft8"
        assert cfg.slots[0].dwell_s == 60
        assert cfg.slots[1].band == "40m"
        assert cfg.slots[1].mode == "cw"
        assert cfg.loop is True

    def test_modes_mode_basic(self):
        cfg = RotationConfig.from_dict({
            "rotation_mode": "modes",
            "band": "20m",
            "dwell_s": 30,
            "modes": ["ft8", "cw", "ssb"],
        })
        assert len(cfg.slots) == 3
        for s in cfg.slots:
            assert s.band == "20m"
        assert cfg.slots[0].mode == "ft8"
        assert cfg.slots[1].mode == "cw"
        assert cfg.slots[2].mode == "ssb"

    def test_per_slot_dwell_override(self):
        cfg = RotationConfig.from_dict({
            "rotation_mode": "bands",
            "dwell_s": 60,
            "slots": [
                {"band": "20m", "mode": "ft8", "dwell_s": 120},
                {"band": "40m", "mode": "ft8"},
            ],
        })
        assert cfg.slots[0].dwell_s == 120
        assert cfg.slots[1].dwell_s == 60

    def test_wspr_dwell_clamped_to_120(self):
        cfg = RotationConfig.from_dict({
            "rotation_mode": "modes",
            "band": "20m",
            "dwell_s": 30,
            "modes": ["ft8", "wspr"],
        })
        assert cfg.slots[0].dwell_s == 30  # ft8 min is 15
        assert cfg.slots[1].dwell_s == 120  # wspr min is 120

    def test_ft4_dwell_clamped_to_8(self):
        cfg = RotationConfig.from_dict({
            "rotation_mode": "modes",
            "band": "20m",
            "dwell_s": 5,
            "modes": ["ft4", "ft8"],
        })
        assert cfg.slots[0].dwell_s == 8  # ft4 min
        assert cfg.slots[1].dwell_s == 15  # ft8 min

    def test_loop_false(self):
        cfg = RotationConfig.from_dict({
            "rotation_mode": "bands",
            "dwell_s": 60,
            "loop": False,
            "slots": [
                {"band": "20m", "mode": "ft8"},
                {"band": "40m", "mode": "ft8"},
            ],
        })
        assert cfg.loop is False

    def test_error_less_than_2_slots(self):
        with pytest.raises(ValueError, match="at least 2"):
            RotationConfig.from_dict({
                "rotation_mode": "bands",
                "dwell_s": 60,
                "slots": [{"band": "20m", "mode": "ft8"}],
            })

    def test_error_modes_missing_band(self):
        with pytest.raises(ValueError, match="band"):
            RotationConfig.from_dict({
                "rotation_mode": "modes",
                "dwell_s": 60,
                "modes": ["ft8", "cw"],
            })

    def test_error_bands_empty_slots(self):
        with pytest.raises(ValueError, match="slots"):
            RotationConfig.from_dict({
                "rotation_mode": "bands",
                "dwell_s": 60,
                "slots": [],
            })

    def test_error_slot_missing_mode(self):
        with pytest.raises(ValueError, match="band.*mode"):
            RotationConfig.from_dict({
                "rotation_mode": "bands",
                "dwell_s": 60,
                "slots": [
                    {"band": "20m"},
                    {"band": "40m", "mode": "ft8"},
                ],
            })


# ── _clamp_dwell ─────────────────────────────────────────────────

class TestClampDwell:

    def test_respects_minimum(self):
        assert _clamp_dwell("wspr", 30) == 120
        assert _clamp_dwell("ft8", 5) == 15
        assert _clamp_dwell("ft4", 3) == 8
        assert _clamp_dwell("cw", 5) == 10
        assert _clamp_dwell("ssb", 5) == 15

    def test_allows_above_minimum(self):
        assert _clamp_dwell("ft8", 300) == 300
        assert _clamp_dwell("wspr", 240) == 240

    def test_unknown_mode_uses_default(self):
        assert _clamp_dwell("aprs", 3) == 10


# ── ScanRotation ─────────────────────────────────────────────────

class TestScanRotation:

    @pytest.mark.asyncio
    async def test_basic_rotation_advances(self):
        """Rotation should call the switch callback for each slot."""
        switched = []

        async def mock_switch(slot):
            switched.append((slot.band, slot.mode))
            return True

        config = RotationConfig(
            slots=[
                RotationSlot(band="20m", mode="ft8", dwell_s=1),
                RotationSlot(band="40m", mode="cw", dwell_s=1),
            ],
            loop=True,
        )
        rotation = ScanRotation(config, mock_switch)
        await rotation.start()
        assert rotation.running

        # Let it run through 2+ slots
        await asyncio.sleep(2.5)
        await rotation.stop()
        assert not rotation.running

        # Should have switched at least twice (first slot + advance)
        assert len(switched) >= 2
        assert switched[0] == ("20m", "ft8")
        assert switched[1] == ("40m", "cw")

    @pytest.mark.asyncio
    async def test_single_pass_stops(self):
        """loop=False should stop after visiting all slots once."""
        switched = []

        async def mock_switch(slot):
            switched.append((slot.band, slot.mode))
            return True

        config = RotationConfig(
            slots=[
                RotationSlot(band="20m", mode="ft8", dwell_s=1),
                RotationSlot(band="40m", mode="cw", dwell_s=1),
            ],
            loop=False,
        )
        rotation = ScanRotation(config, mock_switch)
        await rotation.start()
        # Wait enough for both slots + safety margin
        await asyncio.sleep(3.0)
        assert not rotation.running
        assert len(switched) == 2

    @pytest.mark.asyncio
    async def test_status_snapshot(self):
        async def mock_switch(slot):
            return True

        config = RotationConfig(
            slots=[
                RotationSlot(band="20m", mode="ft8", dwell_s=60),
                RotationSlot(band="40m", mode="cw", dwell_s=30),
            ],
            loop=True,
        )
        rotation = ScanRotation(config, mock_switch)
        await rotation.start()

        status = rotation.status()
        assert status["running"] is True
        assert status["current_index"] == 0
        assert status["total_slots"] == 2
        assert status["current_slot"]["band"] == "20m"
        assert status["next_slot"]["band"] == "40m"
        assert status["time_remaining_s"] > 0
        assert len(status["slots"]) == 2

        await rotation.stop()

    @pytest.mark.asyncio
    async def test_stop_idempotent(self):
        async def mock_switch(slot):
            return True

        config = RotationConfig(
            slots=[
                RotationSlot(band="20m", mode="ft8", dwell_s=60),
                RotationSlot(band="40m", mode="cw", dwell_s=60),
            ],
        )
        rotation = ScanRotation(config, mock_switch)
        # Stop before start should return False
        result = await rotation.stop()
        assert result is False

    @pytest.mark.asyncio
    async def test_start_twice_returns_false(self):
        async def mock_switch(slot):
            return True

        config = RotationConfig(
            slots=[
                RotationSlot(band="20m", mode="ft8", dwell_s=60),
                RotationSlot(band="40m", mode="cw", dwell_s=60),
            ],
        )
        rotation = ScanRotation(config, mock_switch)
        assert await rotation.start() is True
        assert await rotation.start() is False  # already running
        await rotation.stop()

    @pytest.mark.asyncio
    async def test_switch_failure_skips_slot(self):
        """If switch callback fails, rotation should continue to next slot."""
        switched = []

        async def mock_switch(slot):
            switched.append(slot.mode)
            if slot.mode == "cw":
                return False  # simulate failure
            return True

        config = RotationConfig(
            slots=[
                RotationSlot(band="20m", mode="ft8", dwell_s=1),
                RotationSlot(band="20m", mode="cw", dwell_s=1),
                RotationSlot(band="20m", mode="ssb", dwell_s=1),
            ],
            loop=False,
        )
        rotation = ScanRotation(config, mock_switch)
        await rotation.start()
        await asyncio.sleep(4.0)
        assert not rotation.running
        # All 3 modes should have been attempted
        assert switched == ["ft8", "cw", "ssb"]
