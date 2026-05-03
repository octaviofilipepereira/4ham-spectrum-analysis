# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

import asyncio

import pytest

from app.scan.engine import ScanEngine


class _DummyController:
    def __init__(self):
        self.closed = []

    def close(self, device, stream):
        self.closed.append((device, stream))


@pytest.mark.asyncio
async def test_preview_open_timeout_closes_late_device(monkeypatch):
    controller = _DummyController()
    engine = ScanEngine(controller)
    loop = asyncio.get_running_loop()
    open_future = loop.create_future()

    def fake_run_in_executor(_executor, _func):
        return open_future

    async def fake_wait_for(_awaitable, timeout):
        assert timeout == 25.0
        raise asyncio.TimeoutError

    monkeypatch.setattr(loop, "run_in_executor", fake_run_in_executor)
    monkeypatch.setattr("app.scan.engine.asyncio.wait_for", fake_wait_for)

    with pytest.raises(asyncio.TimeoutError):
        await engine.preview_open(device_id="rtlsdr")

    device = object()
    stream = object()
    open_future.set_result((device, stream))
    await asyncio.sleep(0)

    assert controller.closed == [(device, stream)]
    assert engine.device is None
    assert engine.stream is None
    assert engine.preview is False
    assert engine.preview_start_hz == 0
    assert engine.preview_end_hz == 0