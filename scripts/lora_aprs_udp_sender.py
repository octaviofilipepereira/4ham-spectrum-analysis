#!/usr/bin/env python3
# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-04-21

"""
LoRa-APRS UDP sender (developer / E2E validation tool)
======================================================

Sends synthetic LoRa-APRS frames (with the standard ``<\\xff\\x01``
OE5BPA header) to the local 4ham backend UDP listener, so the full
LoRa-APRS pipeline can be exercised **without any SDR hardware or
gr-lora_sdr install**.

Use this to validate:

* The backend UDP listener (``lora_aprs_loop``) is bound and reachable.
* The frame parser correctly strips the LoRa header and extracts
  callsign / position / symbol.
* Events appear on the APRS map under the **📡 LoRa** filter and are
  written to the database with ``source=lora_aprs`` and
  ``frequency_hz=433_775_000``.

Usage
-----

::

    # Default: send one CT7BFV-9 position frame to 127.0.0.1:5687
    python3 scripts/lora_aprs_udp_sender.py

    # Send N frames with a custom callsign and inter-frame delay
    python3 scripts/lora_aprs_udp_sender.py --callsign CT7XYZ --count 5 --interval 2

    # Target a different host/port (e.g. remote backend on the LAN)
    python3 scripts/lora_aprs_udp_sender.py --host 192.168.1.50 --port 5687

This tool is **not** part of the production runtime — it lives in
``scripts/`` as a developer aid and is referenced from the
installation manual as the recommended way to verify a fresh LoRa
APRS install before hooking up a real ``gr-lora_sdr`` flowgraph.
"""

from __future__ import annotations

import argparse
import socket
import sys
import time


LORA_APRS_HEADER = b"<\xff\x01"


def build_frame(callsign: str, lat: str = "4012.34N", lon: str = "00824.56W",
                comment: str = "Test from lora_aprs_udp_sender") -> bytes:
    """Build a TNC2-formatted APRS position packet wrapped in a LoRa header."""
    # APRS uncompressed position with timestamp-less '!' indicator.
    # Symbol table '/' + symbol code '>' = car (per APRS symbol set).
    payload = (
        f"{callsign}>APLM01,WIDE1-1:!{lat}/{lon}>{comment}"
    ).encode("ascii", errors="replace")
    return LORA_APRS_HEADER + payload


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Send synthetic LoRa-APRS frames over UDP.")
    p.add_argument("--host", default="127.0.0.1", help="Target host (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=5687, help="Target UDP port (default 5687)")
    p.add_argument("--callsign", default="CT7BFV-9", help="Source callsign (default CT7BFV-9)")
    p.add_argument("--lat", default="4012.34N", help="APRS latitude (DDMM.mmH)")
    p.add_argument("--lon", default="00824.56W", help="APRS longitude (DDDMM.mmH)")
    p.add_argument("--comment", default="Test from lora_aprs_udp_sender", help="APRS comment text")
    p.add_argument("--count", type=int, default=1, help="Number of frames to send (default 1)")
    p.add_argument("--interval", type=float, default=1.0,
                   help="Seconds between frames when --count > 1 (default 1.0)")
    args = p.parse_args(argv)

    frame = build_frame(args.callsign, args.lat, args.lon, args.comment)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for i in range(args.count):
            sock.sendto(frame, (args.host, args.port))
            print(f"[{i+1}/{args.count}] sent {len(frame)} bytes to {args.host}:{args.port} "
                  f"({args.callsign})")
            if i + 1 < args.count:
                time.sleep(args.interval)
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
