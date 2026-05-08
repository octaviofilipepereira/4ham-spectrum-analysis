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


class _StarvingController:
    def __init__(self):
        self.read_calls = 0

    def read_samples(self, _device, _stream, _chunk_size):
        self.read_calls += 1
        return None


@pytest.mark.asyncio
async def test_iq_pump_recovers_preview_after_prolonged_starvation(monkeypatch):
    controller = _StarvingController()
    engine = ScanEngine(controller)
    engine.preview = True
    engine.device = object()
    engine.stream = object()
    engine.sample_rate = 2_048_000
    engine.center_hz = 14_175_000
    engine._iq_starvation_recover_s = 5.0

    sleep_calls = []
    monotonic_values = iter([0.0, 1.0, 6.2])
    recovered = []

    def fake_monotonic():
        try:
            return next(monotonic_values)
        except StopIteration:
            return 6.2

    async def fake_sleep(delay):
        sleep_calls.append(delay)

    async def fake_recover_preview_device():
        recovered.append(True)
        engine.preview = False
        return True

    monkeypatch.setattr("app.scan.engine.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("app.scan.engine.time.monotonic", fake_monotonic)
    monkeypatch.setattr(engine, "_recover_preview_device", fake_recover_preview_device)

    await engine._iq_pump_loop()

    assert controller.read_calls == 3
    assert recovered == [True]
    assert sleep_calls == [0.005, 0.005, 0.005]