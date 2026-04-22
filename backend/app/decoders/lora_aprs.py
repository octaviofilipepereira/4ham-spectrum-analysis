# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-04-21

"""
LoRa APRS decoder
=================

Receives raw LoRa-APRS payloads from an external SDR pipeline (default:
``gr-lora_sdr`` running a flowgraph that decodes 868.000 MHz LoRa frames
(EU SRD band; 433.775 MHz is also supported by re-tuning the SDR) and
forwards the demodulated bytes via UDP).

LoRa-APRS framing (OE5BPA / iss-LoRa convention)
------------------------------------------------
Each LoRa payload is a 3-byte header ``b"<\\xff\\x01"`` followed by a
TNC2-format text packet, e.g.::

    <\\xff\\x01CT7BFV-9>APLM01,WIDE1-1:!4012.34N/00824.56W>Test

The text portion is parsed by the same APRS parser used for the
APRS-IS feed (``parse_aprs_is_line``), guaranteeing identical handling
of position formats, objects, and compressed coordinates.

The decoded events are tagged with ``source="lora_aprs"`` and
``mode="APRS"`` so they share the existing APRS pipeline (DB column,
WebSocket fan-out, map markers) and can be filtered separately by the
frontend.

This module is intentionally hardware-free: ``lora_aprs_loop`` opens a
local UDP socket and waits for datagrams.  Wiring an actual SDR
flowgraph is a separate concern (see ``scripts/enable_lora_aprs.sh``).
"""

import asyncio
import os
import socket

from app.decoders.aprs_is import parse_aprs_is_line


# ── Frame constants ─────────────────────────────────────────────────

# OE5BPA / iss-LoRa magic header prepended to every LoRa-APRS frame.
LORA_APRS_HEADER = b"<\xff\x01"


def parse_lora_frame(data):
    """
    Parse a raw LoRa-APRS payload (bytes) into an event dict.

    Strips the 3-byte ``<\\xff\\x01`` header if present, decodes the
    remaining bytes as UTF-8 (errors ignored), and delegates to the
    APRS-IS line parser.  Sets ``source="lora_aprs"`` on success.

    Returns ``None`` for empty/garbage frames or text that does not
    match any known APRS position format.
    """
    if not data:
        return None

    if isinstance(data, (bytes, bytearray)):
        payload = bytes(data)
        if payload.startswith(LORA_APRS_HEADER):
            payload = payload[len(LORA_APRS_HEADER):]
        text = payload.decode("utf-8", errors="ignore").strip("\r\n\x00 ")
    else:
        text = str(data).strip("\r\n\x00 ")

    if not text:
        return None

    event = parse_aprs_is_line(text)
    if not event:
        return None

    event["source"] = "lora_aprs"
    event["mode"] = "APRS"
    return event


# ── Configuration ────────────────────────────────────────────────────

def get_lora_config():
    """
    Return ``(host, port)`` for the UDP listener, or ``None`` if the
    LoRa-APRS bridge is not configured / not enabled.
    """
    host = os.getenv("LORA_APRS_HOST", "127.0.0.1")
    port = os.getenv("LORA_APRS_PORT")
    enabled = os.getenv("LORA_APRS_ENABLE")
    if not enabled and not port:
        return None
    try:
        port = int(port or 5687)
    except ValueError:
        return None
    return host, port


def describe_lora():
    config = get_lora_config()
    if not config:
        return None
    host, port = config
    return f"udp://{host}:{port}"


# ── Async UDP loop ──────────────────────────────────────────────────

class _LoraDatagramProtocol(asyncio.DatagramProtocol):
    """Minimal asyncio UDP protocol that hands every datagram to a queue."""

    def __init__(self, queue):
        self._queue = queue

    def datagram_received(self, data, addr):  # noqa: D401 - asyncio API
        try:
            self._queue.put_nowait((data, addr))
        except asyncio.QueueFull:
            # Drop oldest to make room — back-pressure rather than crash.
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait((data, addr))
            except asyncio.QueueFull:
                pass

    def error_received(self, exc):  # noqa: D401 - asyncio API
        # Errors are surfaced to the loop via the next recvfrom attempt.
        pass


async def lora_aprs_loop(
    on_event,
    stop_event,
    logger=None,
    reconnect_delay=3.0,
    status_cb=None,
    queue_maxsize=256,
):
    """
    Listen for LoRa-APRS UDP datagrams on the configured socket and
    invoke *on_event(dict)* for every successfully parsed packet.

    The signature deliberately mirrors :func:`direwolf_kiss.kiss_loop`
    so the same launcher / watcher infrastructure can manage it.

    Parameters
    ----------
    on_event : callable
        Receives the parsed event dict.  May be sync or async.
    stop_event : asyncio.Event
        Set this to terminate the loop gracefully.
    logger : callable, optional
        ``logger(msg)`` invoked on connect / disconnect / error.
    reconnect_delay : float
        Seconds to wait before reopening the socket after an error.
    status_cb : callable, optional
        ``status_cb(state, detail)`` with state in
        {"connected", "disconnected", "error"}.
    queue_maxsize : int
        Bound on the in-process datagram queue.
    """
    config = get_lora_config()
    if not config:
        return
    host, port = config

    while not stop_event.is_set():
        transport = None
        try:
            queue = asyncio.Queue(maxsize=queue_maxsize)
            loop = asyncio.get_event_loop()
            transport, _ = await loop.create_datagram_endpoint(
                lambda: _LoraDatagramProtocol(queue),
                local_addr=(host, port),
                allow_broadcast=False,
                reuse_port=False,
            )
            if logger:
                logger(f"lora_aprs_listening udp://{host}:{port}")
            if status_cb:
                status_cb("connected", f"udp://{host}:{port}")

            while not stop_event.is_set():
                try:
                    data, _addr = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                event = parse_lora_frame(data)
                if not event:
                    continue
                result = on_event(event)
                if asyncio.iscoroutine(result):
                    await result
        except OSError as exc:
            if logger:
                logger(f"lora_aprs_socket_error {exc}")
            if status_cb:
                status_cb("error", str(exc))
            await asyncio.sleep(reconnect_delay)
        except Exception as exc:
            if logger:
                logger(f"lora_aprs_error {exc}")
            if status_cb:
                status_cb("error", str(exc))
            await asyncio.sleep(reconnect_delay)
        finally:
            if transport is not None:
                try:
                    transport.close()
                except Exception:
                    pass
                if status_cb:
                    status_cb("disconnected", f"udp://{host}:{port}")
        if not stop_event.is_set():
            await asyncio.sleep(reconnect_delay)


# ── Synchronous helper for tests / external bridges ─────────────────

def open_test_socket(host="127.0.0.1", port=0):
    """
    Open a UDP socket bound to *host:port* and return ``(sock, port)``.
    Used by unit tests to inject synthetic LoRa-APRS datagrams without
    touching real hardware.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    return sock, sock.getsockname()[1]
