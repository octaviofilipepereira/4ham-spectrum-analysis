# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 00:34:50 UTC

import asyncio
import os
import re
import struct

from app.decoders.parsers import extract_callsign


_MAGIC = b"WSJT-X"
_GRID_RE = re.compile(r"^[A-R]{2}\d{2}[A-X]{0,2}$", re.IGNORECASE)
_REPORT_RE = re.compile(r"^(R)?[+-]?\d{1,2}$", re.IGNORECASE)


class WsjtxState:
    def __init__(self):
        self.dial_hz = None
        self.instance_id = None


def _read_u32(data, offset):
    if offset + 4 > len(data):
        return None, offset
    return struct.unpack(">I", data[offset:offset + 4])[0], offset + 4


def _read_i32(data, offset):
    if offset + 4 > len(data):
        return None, offset
    return struct.unpack(">i", data[offset:offset + 4])[0], offset + 4


def _read_u64(data, offset):
    if offset + 8 > len(data):
        return None, offset
    return struct.unpack(">Q", data[offset:offset + 8])[0], offset + 8


def _read_f64(data, offset):
    if offset + 8 > len(data):
        return None, offset
    return struct.unpack(">d", data[offset:offset + 8])[0], offset + 8


def _read_u8(data, offset):
    if offset + 1 > len(data):
        return None, offset
    return data[offset], offset + 1


def _read_qstring(data, offset):
    length, offset = _read_u32(data, offset)
    if length is None:
        return None, offset
    if length == 0xFFFFFFFF:
        return None, offset

    if length == 0:
        return "", offset

    remaining = len(data) - offset
    if remaining <= 0:
        return None, offset

    byte_len = None
    if remaining >= length * 2:
        byte_len = length * 2
        raw = data[offset:offset + byte_len]
        try:
            value = raw.decode("utf-16-be")
        except UnicodeDecodeError:
            value = raw.decode("utf-8", errors="ignore")
        return value, offset + byte_len

    if remaining >= length:
        raw = data[offset:offset + length]
        try:
            value = raw.decode("utf-8")
        except UnicodeDecodeError:
            value = raw.decode("utf-8", errors="ignore")
        return value, offset + length

    return None, offset


def parse_wsjtx_datagram(data, state):
    if not data.startswith(_MAGIC):
        return None
    offset = len(_MAGIC)
    _, offset = _read_u32(data, offset)
    instance_id, offset = _read_qstring(data, offset)
    if instance_id:
        state.instance_id = instance_id
    message_type, offset = _read_u32(data, offset)
    if message_type is None:
        return None

    if message_type == 1:
        dial_hz, _ = _read_u64(data, offset)
        if dial_hz:
            state.dial_hz = int(dial_hz)
        return None

    if message_type != 2:
        return None

    is_new, offset = _read_u8(data, offset)
    time_s, offset = _read_i32(data, offset)
    snr_db, offset = _read_i32(data, offset)
    dt_s, offset = _read_f64(data, offset)
    df_hz, offset = _read_u32(data, offset)
    mode, offset = _read_qstring(data, offset)
    message, offset = _read_qstring(data, offset)
    if message is None:
        return None
    callsign = extract_callsign(message)
    if not callsign:
        return None

    grid = None
    report = None
    for token in str(message).split():
        if grid is None and _GRID_RE.match(token):
            grid = token.upper()
            continue
        if report is None and _REPORT_RE.match(token):
            report = token.upper()

    frequency_hz = None
    if state.dial_hz is not None and df_hz is not None:
        frequency_hz = int(state.dial_hz + df_hz)

    return {
        "mode": (mode or "FT8").upper(),
        "callsign": callsign,
        "snr_db": float(snr_db) if snr_db is not None else None,
        "df_hz": int(df_hz) if df_hz is not None else None,
        "frequency_hz": frequency_hz,
        "grid": grid,
        "report": report,
        "time_s": int(time_s) if time_s is not None else None,
        "dt_s": float(dt_s) if dt_s is not None else None,
        "is_new": bool(is_new) if is_new is not None else None,
        "raw": message
    }


class WsjtxUdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, state, on_event, logger=None):
        self.state = state
        self.on_event = on_event
        self.logger = logger

    def datagram_received(self, data, addr):
        event = parse_wsjtx_datagram(data, self.state)
        if not event:
            return
        result = self.on_event(event)
        if asyncio.iscoroutine(result):
            asyncio.create_task(result)


def get_wsjtx_udp_config():
    port = os.getenv("WSJTX_UDP_PORT")
    host = os.getenv("WSJTX_UDP_HOST", "0.0.0.0")
    enabled = os.getenv("WSJTX_UDP_ENABLE")
    if not enabled and not port:
        return None
    try:
        port = int(port or 2237)
    except ValueError:
        return None
    return host, port


def wsjtx_udp_enabled():
    return get_wsjtx_udp_config() is not None


def describe_wsjtx_udp():
    config = get_wsjtx_udp_config()
    if not config:
        return None
    host, port = config
    return f"{host}:{port}"


def create_wsjtx_udp_listener(state, on_event, logger=None):
    config = get_wsjtx_udp_config()
    if not config:
        return None
    host, port = config
    loop = asyncio.get_running_loop()
    protocol_factory = lambda: WsjtxUdpProtocol(state, on_event, logger=logger)
    return loop.create_datagram_endpoint(protocol_factory, local_addr=(host, port))
