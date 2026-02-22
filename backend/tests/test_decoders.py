# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

import struct

from app.decoders.direwolf_kiss import parse_kiss_frame
from app.decoders.ingest import build_callsign_event
from app.decoders.parsers import parse_ssb_asr_text, parse_wsjtx_line
from app.decoders.wsjtx_udp import WsjtxState, parse_wsjtx_datagram


MAGIC = b"WSJT-X"


def _qstring(value):
    encoded = value.encode("utf-16-be")
    length = len(value)
    return struct.pack(">I", length) + encoded


def _wsjtx_header(message_type):
    return MAGIC + struct.pack(">I", 2) + _qstring("test") + struct.pack(">I", message_type)


def _encode_addr(call, last=False, ssid=0):
    call = call.ljust(6)
    addr = bytes([(ord(ch) << 1) & 0xFE for ch in call])
    ssid_byte = 0x60 | ((ssid & 0x0F) << 1)
    if last:
        ssid_byte |= 0x01
    return addr + bytes([ssid_byte])


def test_wsjtx_udp_decode_with_dial():
    state = WsjtxState()
    dial = 14074000
    status = _wsjtx_header(1) + struct.pack(">Q", dial)
    assert parse_wsjtx_datagram(status, state) is None
    assert state.dial_hz == dial

    message = "CQ CT1ABC IN51"
    df_hz = 50
    packet = (
        _wsjtx_header(2)
        + struct.pack(">B", 0)
        + struct.pack(">i", 0)
        + struct.pack(">i", -12)
        + struct.pack(">d", 0.0)
        + struct.pack(">I", df_hz)
        + _qstring("FT8")
        + _qstring(message)
    )
    event = parse_wsjtx_datagram(packet, state)
    assert event is not None
    assert event["callsign"] == "CT1ABC"
    assert event["frequency_hz"] == dial + df_hz
    assert event["grid"] == "IN51"


def test_direwolf_kiss_parser():
    dest = _encode_addr("APRS", last=False)
    src = _encode_addr("CT1ABC", last=False)
    digi = _encode_addr("CPNW2", last=True)
    control_pid = bytes([0x03, 0xF0])
    info = "!3859.50N/00911.20W-Test".encode("utf-8")
    ax25 = dest + src + digi + control_pid + info
    frame = bytes([0x00]) + ax25
    event = parse_kiss_frame(frame)
    assert event is not None
    assert event["callsign"] == "CT1ABC"
    assert event["path"] == "CPNW2"
    assert event["payload"].startswith("!")
    assert round(event["lat"], 3) == 38.992
    assert round(event["lon"], 3) == -9.187


def test_ssb_asr_parser_phonetic_callsign():
    event = parse_ssb_asr_text("CQ CQ this is Charlie Tango One Alpha Bravo Charlie portable")
    assert event is not None
    assert event["mode"] == "SSB"
    assert event["callsign"] == "CT1ABC/P"


def test_ssb_asr_parser_returns_none_without_callsign():
    event = parse_ssb_asr_text("good afternoon station with strong signal")
    assert event is None


def test_ssb_asr_parser_extracts_grid_report_and_frequency():
    event = parse_ssb_asr_text("CT1ABC IN51 59 14.255 MHz")
    assert event is not None
    assert event["callsign"] == "CT1ABC"
    assert event["grid"] == "IN51"
    assert event["report"] == "59"
    assert event["frequency_hz"] == 14255000


def test_parse_wsjtx_line_extracts_grid():
    line = "200109  -12  0.2  14074000  FT8  CQ CT1ABC IN50"
    event = parse_wsjtx_line(line)
    assert event is not None
    assert event["callsign"] == "CT1ABC"
    assert event["grid"] == "IN50"


def test_parse_wsjtx_line_extracts_report():
    line = "200109  -07  0.2  14074000  FT8  CT1ABC EA1XYZ -03"
    event = parse_wsjtx_line(line)
    assert event is not None
    assert event["report"] == "-03"


def test_build_callsign_event_infers_20m_band_from_frequency():
    event = build_callsign_event({"callsign": "CT1ABC", "frequency_hz": 14255000}, {})
    assert event is not None
    assert event["band"] == "20m"


def test_build_callsign_event_infers_15m_band_from_frequency():
    event = build_callsign_event({"callsign": "CT1ABC", "frequency_hz": 21250000}, {})
    assert event is not None
    assert event["band"] == "15m"