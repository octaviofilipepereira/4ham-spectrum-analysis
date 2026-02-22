# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 17:40:00 UTC

import asyncio

from app.decoders.ft_internal import InternalFtDecoder


def test_ft_internal_decoder_lifecycle_snapshot():
    async def scenario():
        decoder = InternalFtDecoder(modes=["FT8", "FT4"], compare_with_wsjtx=True, min_confidence=0.4, poll_s=0.1)

        started = await decoder.start()
        assert started is True

        await asyncio.sleep(0.15)
        status_running = decoder.snapshot()
        assert status_running["running"] is True
        assert status_running["enabled"] is True
        assert status_running["modes"] == ["FT8", "FT4"]
        assert status_running["compare_with_wsjtx"] is True
        assert status_running["min_confidence"] == 0.4
        assert status_running["started_at"] is not None
        assert status_running["last_heartbeat_at"] is not None

        stopped = await decoder.stop()
        assert stopped is True

        status_stopped = decoder.snapshot()
        assert status_stopped["running"] is False
        assert status_stopped["enabled"] is False
        assert status_stopped["stopped_at"] is not None

    asyncio.run(scenario())


def test_ft_internal_decoder_emits_mock_events_when_enabled():
    async def scenario():
        emitted_events = []

        def on_event(payload):
            emitted_events.append(dict(payload))

        decoder = InternalFtDecoder(
            modes=["FT8", "FT4"],
            compare_with_wsjtx=False,
            min_confidence=0.5,
            poll_s=0.02,
            emit_mock_events=True,
            mock_interval_s=0.05,
            mock_callsign="CT7BFV",
            on_event=on_event,
            frequency_provider=lambda: 14074000,
        )

        await decoder.start()
        await asyncio.sleep(0.16)
        await decoder.stop()

        assert len(emitted_events) >= 2
        first = emitted_events[0]
        assert first["source"] == "internal_ft"
        assert first["callsign"] == "CT7BFV"
        assert first["frequency_hz"] == 14074000
        assert first["mode"] in {"FT8", "FT4"}
        assert first["confidence"] >= 0.5

        status = decoder.snapshot()
        assert status["events_emitted"] >= 2
        assert status["last_event_at"] is not None

    asyncio.run(scenario())
