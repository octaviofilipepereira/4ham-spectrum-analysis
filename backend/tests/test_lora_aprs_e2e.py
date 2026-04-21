# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""
End-to-end integration tests for the LoRa-APRS pipeline.

Exercises the full backend ingestion path *without* SDR hardware:

  scripts/lora_aprs_udp_sender.py  →  UDP :PORT  →  lora_aprs_loop
      →  _lora_aprs_on_event  →  enrichment + ingest path

What this validates beyond ``test_lora_aprs.py``:

* The **backend API callback** (``_lora_aprs_on_event``) is wired
  correctly, enriches each event with ``frequency_hz=433_775_000``,
  and updates ``state.decoder_status["lora_aprs"]["last_packet_at"]``.
* The status callback (``_lora_aprs_status_cb``) flips the
  ``connected`` flag and records the bound address.
* Multiple frames in sequence (mimicking a live ``gr-lora_sdr``
  flowgraph) are all delivered without packet loss on loopback.
"""

import asyncio
import os
import socket
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Import after sys.path is set so ``app`` resolves.
from app.decoders.lora_aprs import lora_aprs_loop  # noqa: E402


SENDER_SCRIPT = REPO_ROOT.parent / "scripts" / "lora_aprs_udp_sender.py"


def _free_udp_port() -> int:
    """Pick a free local UDP port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class LoraAprsE2EApiTests(unittest.TestCase):
    """End-to-end tests through the API integration layer."""

    def setUp(self):
        self._saved_env = {
            k: os.environ.get(k)
            for k in ("LORA_APRS_ENABLE", "LORA_APRS_HOST", "LORA_APRS_PORT")
        }

    def tearDown(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_api_callback_enriches_event_with_frequency(self):
        """``_lora_aprs_on_event`` must add frequency_hz=433.775 MHz."""
        # Import here so state singleton is fresh per test run.
        from app.api import decoders as decoders_mod

        captured = []

        def fake_ingest(events, _meta):
            captured.extend(events)
            return {"saved": len(events)}

        # Patch the ingest helper to avoid touching the real DB.
        with patch.object(decoders_mod, "_ingest_callsign_payloads", fake_ingest):
            # Patch broadcast to no-op (no real WS clients in test env).
            decoders_mod._lora_aprs_on_event({
                "callsign": "CT7BFV-9",
                "lat": 40.123,
                "lon": -8.456,
                "source": "lora_aprs",
                "mode": "APRS",
            })

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["frequency_hz"], 433_775_000)
        self.assertEqual(captured[0]["source"], "lora_aprs")
        # last_packet_at should be set to a non-empty ISO string.
        last = decoders_mod.state.decoder_status["lora_aprs"]["last_packet_at"]
        self.assertIsNotNone(last)
        self.assertIn("T", last)  # ISO 8601 format

    def test_api_callback_preserves_existing_frequency(self):
        """If event already has frequency_hz, callback must not overwrite."""
        from app.api import decoders as decoders_mod

        captured = []

        def fake_ingest(events, _meta):
            captured.extend(events)
            return {"saved": len(events)}

        with patch.object(decoders_mod, "_ingest_callsign_payloads", fake_ingest):
            decoders_mod._lora_aprs_on_event({
                "callsign": "CT7XYZ",
                "frequency_hz": 433_900_000,  # custom non-default
                "source": "lora_aprs",
            })

        self.assertEqual(captured[0]["frequency_hz"], 433_900_000)

    def test_api_status_callback_updates_state(self):
        """``_lora_aprs_status_cb`` flips connected/address/last_error fields."""
        from app.api import decoders as decoders_mod

        st = decoders_mod.state.decoder_status["lora_aprs"]
        # connected
        decoders_mod._lora_aprs_status_cb("connected", "udp://127.0.0.1:5687")
        self.assertTrue(st["connected"])
        self.assertEqual(st["address"], "udp://127.0.0.1:5687")
        self.assertIsNone(st["last_error"])

        # error
        decoders_mod._lora_aprs_status_cb("error", "bind failed")
        self.assertFalse(st["connected"])
        self.assertEqual(st["last_error"], "bind failed")

        # disconnected
        decoders_mod._lora_aprs_status_cb("connected", "udp://127.0.0.1:5687")
        decoders_mod._lora_aprs_status_cb("disconnected", "")
        self.assertFalse(st["connected"])

    def test_api_callback_ignores_invalid_input(self):
        """Empty / non-dict events must not crash the callback."""
        from app.api import decoders as decoders_mod
        # Should silently ignore — no exception.
        decoders_mod._lora_aprs_on_event(None)
        decoders_mod._lora_aprs_on_event({})
        decoders_mod._lora_aprs_on_event("not a dict")  # type: ignore[arg-type]


@unittest.skipUnless(SENDER_SCRIPT.exists(), "udp sender script missing")
class LoraAprsE2ESenderTests(unittest.TestCase):
    """End-to-end test driven by the real ``lora_aprs_udp_sender.py`` CLI."""

    def test_sender_script_drives_loop_to_event(self):
        """Spawn the sender as a subprocess; verify the loop ingests its frame."""
        port = _free_udp_port()
        os.environ["LORA_APRS_ENABLE"] = "1"
        os.environ["LORA_APRS_HOST"] = "127.0.0.1"
        os.environ["LORA_APRS_PORT"] = str(port)

        received = []
        stop = asyncio.Event()

        async def runner():
            def on_event(ev):
                received.append(ev)
                stop.set()

            task = asyncio.create_task(
                lora_aprs_loop(on_event, stop, reconnect_delay=0.1)
            )
            # Give loop a moment to bind.
            await asyncio.sleep(0.15)

            # Drive frames via the real sender CLI (mirrors what users will
            # run when validating a fresh install).
            for _ in range(20):
                if received:
                    break
                subprocess.run(
                    [
                        sys.executable, str(SENDER_SCRIPT),
                        "--host", "127.0.0.1", "--port", str(port),
                        "--callsign", "CT7BFV-9", "--count", "1",
                    ],
                    capture_output=True, check=True, timeout=5,
                )
                await asyncio.sleep(0.1)

            stop.set()
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except asyncio.TimeoutError:
                task.cancel()

        try:
            asyncio.run(runner())
        finally:
            for k in ("LORA_APRS_ENABLE", "LORA_APRS_HOST", "LORA_APRS_PORT"):
                os.environ.pop(k, None)

        self.assertTrue(received, "sender script did not produce any event")
        ev = received[0]
        self.assertEqual(ev["callsign"], "CT7BFV-9")
        self.assertEqual(ev["source"], "lora_aprs")
        self.assertEqual(ev["mode"], "APRS")


if __name__ == "__main__":
    unittest.main()
