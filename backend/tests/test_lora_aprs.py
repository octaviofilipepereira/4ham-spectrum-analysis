# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""
Offline tests for the LoRa-APRS decoder.

These tests exercise ``parse_lora_frame`` with synthetic frame
vectors (no SDR hardware, no network).  The end-to-end UDP loop is
covered by injecting datagrams into a local socket pair.
"""

import asyncio
import os
import socket
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Import after sys.path is set so ``app`` resolves.
from app.decoders.lora_aprs import (  # noqa: E402
    LORA_APRS_HEADER,
    describe_lora,
    get_lora_config,
    lora_aprs_loop,
    parse_lora_frame,
)


# Sample frames captured/synthesised from typical LoRa-APRS traffic.
FRAME_HEADERED = (
    LORA_APRS_HEADER
    + b"CT7BFV-9>APLM01,WIDE1-1:!4012.34N/00824.56W>LoRa APRS test"
)
FRAME_PLAIN = b"CT4XYZ>APLM01:!3845.12N/00908.45W>portable"
FRAME_COMPRESSED = (
    LORA_APRS_HEADER
    + b"OE5BPA-7>APLM01:!//ABCD/wxyzKabc test compressed"
)
FRAME_GARBAGE = b"\x00\x01\x02not aprs"
FRAME_EMPTY = b""


class ParseLoraFrameTests(unittest.TestCase):
    def test_strips_lora_header_and_parses_position(self):
        event = parse_lora_frame(FRAME_HEADERED)
        self.assertIsNotNone(event)
        self.assertEqual(event["callsign"], "CT7BFV-9")
        self.assertEqual(event["mode"], "APRS")
        self.assertEqual(event["source"], "lora_aprs")
        self.assertAlmostEqual(event["lat"], 40 + 12.34 / 60.0, places=4)
        self.assertAlmostEqual(event["lon"], -(8 + 24.56 / 60.0), places=4)
        self.assertIn("LoRa APRS test", event["msg"])

    def test_accepts_frame_without_header(self):
        event = parse_lora_frame(FRAME_PLAIN)
        self.assertIsNotNone(event)
        self.assertEqual(event["callsign"], "CT4XYZ")
        self.assertEqual(event["source"], "lora_aprs")
        self.assertAlmostEqual(event["lat"], 38 + 45.12 / 60.0, places=4)
        self.assertAlmostEqual(event["lon"], -(9 + 8.45 / 60.0), places=4)

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_lora_frame(FRAME_GARBAGE))

    def test_empty_returns_none(self):
        self.assertIsNone(parse_lora_frame(FRAME_EMPTY))
        self.assertIsNone(parse_lora_frame(None))

    def test_string_input_supported(self):
        text = "CT4XYZ>APLM01:!3845.12N/00908.45W>portable"
        event = parse_lora_frame(text)
        self.assertIsNotNone(event)
        self.assertEqual(event["source"], "lora_aprs")


class LoraConfigTests(unittest.TestCase):
    def setUp(self):
        self._saved = {
            k: os.environ.get(k)
            for k in ("LORA_APRS_ENABLE", "LORA_APRS_HOST", "LORA_APRS_PORT")
        }
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_disabled_by_default(self):
        self.assertIsNone(get_lora_config())
        self.assertIsNone(describe_lora())

    def test_enabled_via_env(self):
        os.environ["LORA_APRS_ENABLE"] = "1"
        cfg = get_lora_config()
        self.assertEqual(cfg, ("127.0.0.1", 5687))
        self.assertEqual(describe_lora(), "udp://127.0.0.1:5687")

    def test_invalid_port_returns_none(self):
        os.environ["LORA_APRS_ENABLE"] = "1"
        os.environ["LORA_APRS_PORT"] = "not-a-number"
        self.assertIsNone(get_lora_config())


class LoraLoopTests(unittest.TestCase):
    def test_loop_consumes_udp_datagrams(self):
        # Pick a free local port and configure decoder to listen there.
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        os.environ["LORA_APRS_ENABLE"] = "1"
        os.environ["LORA_APRS_HOST"] = "127.0.0.1"
        os.environ["LORA_APRS_PORT"] = str(port)

        received = []
        stop = asyncio.Event()

        async def runner():
            def on_event(ev):
                received.append(ev)
                # First parsed event ends the loop.
                stop.set()

            task = asyncio.create_task(
                lora_aprs_loop(on_event, stop, reconnect_delay=0.1)
            )
            # Give the loop a moment to bind the socket.
            for _ in range(50):
                await asyncio.sleep(0.02)
                # Send a datagram from a client socket.
                client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                client.sendto(FRAME_HEADERED, ("127.0.0.1", port))
                client.close()
                if received:
                    break
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

        self.assertTrue(received, "loop did not deliver any datagram")
        self.assertEqual(received[0]["callsign"], "CT7BFV-9")
        self.assertEqual(received[0]["source"], "lora_aprs")


if __name__ == "__main__":
    unittest.main()
