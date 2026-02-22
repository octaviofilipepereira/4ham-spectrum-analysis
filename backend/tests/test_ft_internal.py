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
