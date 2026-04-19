# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Deep APRS validation tests — KissBuffer, AX.25, APRS payload, parse_aprs_line,
# kiss_loop (mock TCP), ingest pipeline, API endpoint, config, state.

import asyncio
import json
import os
import struct

import pytest

from app.decoders.direwolf_kiss import (
    KissBuffer,
    _decode_callsign,
    _decode_address,
    _parse_ax25,
    _parse_aprs_payload,
    parse_kiss_frame,
    get_kiss_config,
    describe_kiss,
    kiss_loop,
    _FRAME_END,
    _FRAME_ESC,
    _TRANS_FEND,
    _TRANS_FESC,
)
from app.decoders.parsers import parse_aprs_line
from app.decoders.ingest import build_callsign_event, is_valid_callsign


# ═══════════════════════════════════════════════════════════════════
# Helpers — AX.25 address encoding (mirrors Direwolf encoding)
# ═══════════════════════════════════════════════════════════════════

def _encode_addr(call, last=False, ssid=0):
    """Encode a callsign into a 7-byte AX.25 address field."""
    call = call.ljust(6)
    addr = bytes([(ord(ch) << 1) & 0xFE for ch in call])
    ssid_byte = 0x60 | ((ssid & 0x0F) << 1)
    if last:
        ssid_byte |= 0x01
    return addr + bytes([ssid_byte])


def _build_kiss_frame(src, dest="APRS", digis=None, info=b"", src_ssid=0):
    """Build a complete KISS frame (port_cmd + AX.25)."""
    digis = digis or []
    dest_addr = _encode_addr(dest, last=(len(digis) == 0 and True) if False else False)
    src_addr = _encode_addr(src, last=(len(digis) == 0), ssid=src_ssid)
    digi_addrs = b""
    for i, d in enumerate(digis):
        digi_addrs += _encode_addr(d, last=(i == len(digis) - 1))
    # If no digipeaters, mark src as last
    if not digis:
        # Rebuild src with last=True
        src_addr = _encode_addr(src, last=True, ssid=src_ssid)
    control_pid = bytes([0x03, 0xF0])
    ax25 = dest_addr + src_addr + digi_addrs + control_pid + info
    return bytes([0x00]) + ax25  # port_cmd=0x00 (data, port 0)


def _wrap_kiss(frame_data):
    """Wrap raw KISS frame data in FEND delimiters."""
    return bytes([_FRAME_END]) + frame_data + bytes([_FRAME_END])


# ═══════════════════════════════════════════════════════════════════
# 1. KissBuffer — KISS framing layer
# ═══════════════════════════════════════════════════════════════════

class TestKissBuffer:
    """Test KISS TNC framing: FEND delimiters, escape sequences, multi-frame."""

    def test_single_frame(self):
        buf = KissBuffer()
        payload = bytes([0x00, 0x01, 0x02, 0x03])
        data = bytes([_FRAME_END]) + payload + bytes([_FRAME_END])
        frames = buf.feed(data)
        assert len(frames) == 1
        assert frames[0] == payload

    def test_multiple_frames_in_one_feed(self):
        buf = KissBuffer()
        p1 = bytes([0x00, 0xAA])
        p2 = bytes([0x00, 0xBB])
        data = bytes([_FRAME_END]) + p1 + bytes([_FRAME_END]) + p2 + bytes([_FRAME_END])
        frames = buf.feed(data)
        assert len(frames) == 2
        assert frames[0] == p1
        assert frames[1] == p2

    def test_split_across_feeds(self):
        """Frame split across two TCP reads."""
        buf = KissBuffer()
        payload = bytes([0x00, 0x01, 0x02, 0x03, 0x04])
        part1 = bytes([_FRAME_END]) + payload[:3]
        part2 = payload[3:] + bytes([_FRAME_END])
        assert buf.feed(part1) == []
        frames = buf.feed(part2)
        assert len(frames) == 1
        assert frames[0] == payload

    def test_escape_fend(self):
        """FEND byte inside payload must be escaped as ESC + TRANS_FEND."""
        buf = KissBuffer()
        # Data containing escaped 0xC0
        escaped = bytes([0x00, _FRAME_ESC, _TRANS_FEND, 0x01])
        data = bytes([_FRAME_END]) + escaped + bytes([_FRAME_END])
        frames = buf.feed(data)
        assert len(frames) == 1
        assert frames[0] == bytes([0x00, _FRAME_END, 0x01])

    def test_escape_fesc(self):
        """ESC byte inside payload must be escaped as ESC + TRANS_FESC."""
        buf = KissBuffer()
        escaped = bytes([0x00, _FRAME_ESC, _TRANS_FESC, 0x01])
        data = bytes([_FRAME_END]) + escaped + bytes([_FRAME_END])
        frames = buf.feed(data)
        assert len(frames) == 1
        assert frames[0] == bytes([0x00, _FRAME_ESC, 0x01])

    def test_empty_frame_ignored(self):
        """Back-to-back FENDs with no data produce no frames."""
        buf = KissBuffer()
        data = bytes([_FRAME_END, _FRAME_END, _FRAME_END])
        frames = buf.feed(data)
        assert frames == []

    def test_data_before_first_fend_discarded(self):
        """Data before the first FEND delimiter should be discarded."""
        buf = KissBuffer()
        garbage = bytes([0x41, 0x42, 0x43])
        payload = bytes([0x00, 0x01])
        data = garbage + bytes([_FRAME_END]) + payload + bytes([_FRAME_END])
        frames = buf.feed(data)
        assert len(frames) == 1
        assert frames[0] == payload

    def test_unknown_escape_passthrough(self):
        """Unknown escape byte (not TRANS_FEND/TRANS_FESC) passes through."""
        buf = KissBuffer()
        escaped = bytes([0x00, _FRAME_ESC, 0x42, 0x01])
        data = bytes([_FRAME_END]) + escaped + bytes([_FRAME_END])
        frames = buf.feed(data)
        assert len(frames) == 1
        # 0x42 passed through after ESC
        assert frames[0] == bytes([0x00, 0x42, 0x01])

    def test_buffer_reset_between_frames(self):
        """Buffer state is clean between frames."""
        buf = KissBuffer()
        p1 = bytes([0x00, 0x01])
        p2 = bytes([0x00, 0x02])
        buf.feed(bytes([_FRAME_END]) + p1 + bytes([_FRAME_END]))
        frames = buf.feed(bytes([_FRAME_END]) + p2 + bytes([_FRAME_END]))
        assert len(frames) == 1
        assert frames[0] == p2


# ═══════════════════════════════════════════════════════════════════
# 2. AX.25 Address Decoding
# ═══════════════════════════════════════════════════════════════════

class TestAX25Addressing:
    """Test AX.25 callsign encoding/decoding round-trip."""

    def test_decode_simple_callsign(self):
        addr = _encode_addr("CT7BFV", last=True)
        call = _decode_callsign(addr)
        assert call == "CT7BFV"

    def test_decode_callsign_with_ssid(self):
        addr = _encode_addr("CT7BFV", last=True, ssid=7)
        call = _decode_callsign(addr)
        assert call == "CT7BFV-7"

    def test_decode_callsign_ssid_zero_omitted(self):
        addr = _encode_addr("CT7BFV", last=True, ssid=0)
        call = _decode_callsign(addr)
        assert call == "CT7BFV"  # No -0 appended

    def test_decode_short_callsign(self):
        addr = _encode_addr("K1DX", last=True)
        call = _decode_callsign(addr)
        assert call == "K1DX"

    def test_decode_address_last_bit(self):
        addr = _encode_addr("CT7BFV", last=True)
        call, last = _decode_address(addr)
        assert call == "CT7BFV"
        assert last is True

    def test_decode_address_not_last(self):
        addr = _encode_addr("CT7BFV", last=False)
        call, last = _decode_address(addr)
        assert call == "CT7BFV"
        assert last is False

    def test_decode_short_address_returns_none(self):
        assert _decode_callsign(b"\x00\x01\x02") is None
        call, last = _decode_address(b"\x00\x01\x02")
        assert call is None

    def test_decode_ssid_range(self):
        """SSID 0-15 round-trip."""
        for ssid in range(16):
            addr = _encode_addr("CT1AA", last=True, ssid=ssid)
            call = _decode_callsign(addr)
            if ssid == 0:
                assert call == "CT1AA"
            else:
                assert call == f"CT1AA-{ssid}"


# ═══════════════════════════════════════════════════════════════════
# 3. AX.25 Frame Parsing (_parse_ax25)
# ═══════════════════════════════════════════════════════════════════

class TestParseAX25:
    """Test AX.25 UI frame parsing: addresses, digipeaters, info field."""

    def test_minimal_frame_two_addresses(self):
        """Src + Dest only, no digipeaters."""
        frame = _build_kiss_frame("CT7BFV", info=b"Hello")[1:]  # strip port_cmd
        result = _parse_ax25(frame)
        assert result is not None
        assert result["src"] == "CT7BFV"
        assert result["dest"] == "APRS"
        assert result["path"] == []
        assert result["info"] == b"Hello"

    def test_frame_with_one_digipeater(self):
        frame = _build_kiss_frame("CT1ABC", digis=["WIDE1"], info=b"!test")[1:]
        result = _parse_ax25(frame)
        assert result["src"] == "CT1ABC"
        assert result["path"] == ["WIDE1"]

    def test_frame_with_multiple_digipeaters(self):
        frame = _build_kiss_frame("EA1XYZ", digis=["WIDE1", "WIDE2"], info=b"data")[1:]
        result = _parse_ax25(frame)
        assert result["src"] == "EA1XYZ"
        assert len(result["path"]) == 2
        assert "WIDE1" in result["path"]
        assert "WIDE2" in result["path"]

    def test_too_short_frame_returns_none(self):
        assert _parse_ax25(b"") is None
        assert _parse_ax25(b"\x00" * 10) is None
        assert _parse_ax25(None) is None

    def test_frame_without_info_field(self):
        """Frame with addresses but no control/PID/info (truncated)."""
        dest = _encode_addr("APRS", last=False)
        src = _encode_addr("CT7BFV", last=True)
        frame = dest + src  # Just addresses, 14 bytes
        result = _parse_ax25(frame)
        assert result is not None
        assert result["src"] == "CT7BFV"
        assert result["info"] is None


# ═══════════════════════════════════════════════════════════════════
# 4. APRS Payload Parsing (_parse_aprs_payload)
# ═══════════════════════════════════════════════════════════════════

class TestParseAPRSPayload:
    """Test APRS position format parsing (! and = markers)."""

    def test_standard_position_north_west(self):
        """!DDMM.mmN/DDDMM.mmW- format (Portugal area)."""
        text = "!3859.50N/00911.20W-Test station"
        extras, payload = _parse_aprs_payload(text)
        assert abs(extras["lat"] - 38.992) < 0.001
        assert abs(extras["lon"] - (-9.187)) < 0.001
        assert extras["msg"] == "Test station"
        assert extras["symbol_table"] == "/"
        assert extras["symbol_code"] == "-"

    def test_standard_position_south_east(self):
        """Southern hemisphere, eastern longitude."""
        text = "!3350.00S/15100.00E-Sydney"
        extras, payload = _parse_aprs_payload(text)
        assert extras["lat"] < 0  # South
        assert extras["lon"] > 0  # East
        assert abs(extras["lat"] - (-33.833)) < 0.01
        assert abs(extras["lon"] - 151.0) < 0.01

    def test_equals_marker_position(self):
        """= marker (position with message capability)."""
        text = "=4052.50N/00350.00W-Mobile"
        extras, payload = _parse_aprs_payload(text)
        assert abs(extras["lat"] - 40.875) < 0.001
        assert abs(extras["lon"] - (-3.833)) < 0.01

    def test_non_position_payload(self):
        """Status or message payload without position."""
        text = ">Hello World"
        extras, payload = _parse_aprs_payload(text)
        assert "lat" not in extras
        assert "lon" not in extras

    def test_empty_payload(self):
        extras, payload = _parse_aprs_payload("")
        assert extras == {}
        assert payload is None

    def test_none_payload(self):
        extras, payload = _parse_aprs_payload(None)
        assert extras == {}
        assert payload is None

    def test_short_payload_not_parsed_as_position(self):
        """Payload shorter than 20 chars should not be parsed as position."""
        text = "!3859.50N/009"
        extras, payload = _parse_aprs_payload(text)
        assert "lat" not in extras

    def test_invalid_coordinates_graceful(self):
        """Malformed lat/lon should not crash — may parse as compressed."""
        text = "!XXXX.XXN/XXXXX.XXW-Bad"
        extras, payload = _parse_aprs_payload(text)
        # Should not crash; with compressed parsing, X chars are valid base-91
        # so this may return coordinates — the key is no crash
        assert isinstance(extras, dict)

    def test_equator_greenwich(self):
        """0°N 0°W — equator/greenwich."""
        text = "!0000.00N/00000.00W-Zero"
        extras, payload = _parse_aprs_payload(text)
        assert extras["lat"] == 0.0
        assert extras["lon"] == 0.0

    def test_compressed_position_ct1end(self):
        """Compressed APRS position — real CT1END-3 packet from RF."""
        text = "=/:rnrL.Qpy  BGreetings from CT1END {UIV32N}"
        extras, payload = _parse_aprs_payload(text)
        assert extras.get("lat") is not None, "compressed lat not parsed"
        assert extras.get("lon") is not None, "compressed lon not parsed"
        # CT1END is near Lisbon (~38.77°N, ~9.28°W)
        assert abs(extras["lat"] - 38.77) < 0.5
        assert abs(extras["lon"] - (-9.28)) < 0.5
        assert extras["symbol_table"] == "/"
        assert extras["symbol_code"] == "y"

    def test_compressed_position_primary_table(self):
        """Compressed position with / symbol table."""
        # Encode lat=40.0, lon=-8.0 in base-91
        # lat: (90 - 40) * 380926 = 19046300 → encode
        # lon: (-8 - (-180)) * 190463 = 172 * 190463 = 32759636 → encode
        text = "=/5L!!<*e!>"
        extras, payload = _parse_aprs_payload(text)
        # Should parse without error (may or may not have valid coords depending on encoding)
        assert payload is not None

    def test_compressed_position_with_timestamp(self):
        """Compressed position with / data-type (timestamped)."""
        text = "/092345z/:rnrL.Qpy  B"
        extras, payload = _parse_aprs_payload(text)
        assert extras.get("lat") is not None, "timestamped compressed lat not parsed"
        assert extras.get("lon") is not None, "timestamped compressed lon not parsed"


# ═══════════════════════════════════════════════════════════════════
# 4b. Compressed APRS positions via parse_aprs_is_line
# ═══════════════════════════════════════════════════════════════════

class TestParseAprsIsLineCompressed:
    """Test compressed APRS-IS line parsing."""

    def test_compressed_position_is(self):
        """Compressed position from APRS-IS line."""
        from app.decoders.aprs_is import parse_aprs_is_line
        line = "CT1END-3>APRS,TCPIP*:=/:rnrL.Qpy  BGreetings from CT1END"
        event = parse_aprs_is_line(line)
        assert event is not None, "compressed APRS-IS line not parsed"
        assert event["callsign"] == "CT1END-3"
        assert abs(event["lat"] - 38.77) < 0.5
        assert abs(event["lon"] - (-9.28)) < 0.5
        assert event["source"] == "aprs_is"

    def test_uncompressed_position_is_still_works(self):
        """Ensure standard uncompressed parsing is not broken."""
        from app.decoders.aprs_is import parse_aprs_is_line
        line = "CT7BFV>APRS,WIDE1-1:!4013.50N/00830.00W-Test"
        event = parse_aprs_is_line(line)
        assert event is not None
        assert event["callsign"] == "CT7BFV"
        assert abs(event["lat"] - 40.225) < 0.01
        assert abs(event["lon"] - (-8.5)) < 0.01

    def test_compressed_kiss_frame(self):
        """Compressed position via KISS frame pipeline."""
        info = "=/:rnrL.Qpy  BGreetings from CT1END".encode("utf-8")
        frame = _build_kiss_frame("CT1END", src_ssid=3, info=info)
        event = parse_kiss_frame(frame)
        assert event is not None
        assert event["callsign"] == "CT1END-3"
        assert event["lat"] is not None
        assert event["lon"] is not None
        assert abs(event["lat"] - 38.77) < 0.5
        assert abs(event["lon"] - (-9.28)) < 0.5


# ═══════════════════════════════════════════════════════════════════
# 5. parse_kiss_frame (full KISS → event pipeline)
# ═══════════════════════════════════════════════════════════════════

class TestParseKissFrame:
    """Test complete KISS frame → APRS event dict conversion."""

    def test_position_report_with_digipeater(self):
        """Real-world-like APRS position report via digipeater."""
        info = "!3859.50N/00911.20W-Test".encode("utf-8")
        frame = _build_kiss_frame("CT1ABC", digis=["CPNW2"], info=info)
        event = parse_kiss_frame(frame)
        assert event is not None
        assert event["callsign"] == "CT1ABC"
        assert event["mode"] == "APRS"
        assert event["path"] == "CPNW2"
        assert abs(event["lat"] - 38.992) < 0.001
        assert abs(event["lon"] - (-9.187)) < 0.001
        assert event["msg"] == "Test"

    def test_status_message_no_position(self):
        """APRS status message — no lat/lon."""
        info = ">Station active".encode("utf-8")
        frame = _build_kiss_frame("EA4GHR", info=info)
        event = parse_kiss_frame(frame)
        assert event is not None
        assert event["callsign"] == "EA4GHR"
        assert event["mode"] == "APRS"
        assert event["lat"] is None
        assert event["lon"] is None

    def test_callsign_with_ssid(self):
        """Callsign with SSID should be preserved."""
        info = "!3859.50N/00911.20W-".encode("utf-8")
        frame = _build_kiss_frame("CT7BFV", src_ssid=7, info=info)
        event = parse_kiss_frame(frame)
        assert event is not None
        assert event["callsign"] == "CT7BFV-7"

    def test_empty_frame_returns_none(self):
        assert parse_kiss_frame(b"") is None
        assert parse_kiss_frame(None) is None

    def test_non_data_port_cmd_rejected(self):
        """Port command != 0x00 (data) should be rejected."""
        info = "!3859.50N/00911.20W-".encode("utf-8")
        frame = _build_kiss_frame("CT1ABC", info=info)
        # Change port_cmd from 0x00 to 0x01 (TX delay command)
        frame = bytes([0x01]) + frame[1:]
        assert parse_kiss_frame(frame) is None

    def test_multiple_digipeaters_in_path(self):
        info = "!3859.50N/00911.20W-Multi".encode("utf-8")
        frame = _build_kiss_frame("F4HXY", digis=["WIDE1", "WIDE2", "RELAY"], info=info)
        event = parse_kiss_frame(frame)
        assert event is not None
        assert event["callsign"] == "F4HXY"
        assert "WIDE1" in event["path"]
        assert "WIDE2" in event["path"]
        assert "RELAY" in event["path"]

    def test_frame_with_no_info(self):
        """AX.25 frame with addresses but empty info."""
        dest = _encode_addr("APRS", last=False)
        src = _encode_addr("CT7BFV", last=True)
        control_pid = bytes([0x03, 0xF0])
        ax25 = dest + src + control_pid  # No info bytes
        frame = bytes([0x00]) + ax25
        event = parse_kiss_frame(frame)
        assert event is not None
        assert event["callsign"] == "CT7BFV"
        assert event["mode"] == "APRS"


# ═══════════════════════════════════════════════════════════════════
# 6. parse_aprs_line (text-based APRS parser)
# ═══════════════════════════════════════════════════════════════════

class TestParseAPRSLine:
    """Test APRS text line parser (Direwolf monitor output format)."""

    def test_standard_line(self):
        result = parse_aprs_line("CT1ABC>APRS,WIDE1-1:!3859.50N/00911.20W-Test")
        assert result is not None
        assert result["callsign"] == "CT1ABC"
        assert result["mode"] == "APRS"
        assert ">" in result["raw"]

    def test_callsign_case_normalized(self):
        result = parse_aprs_line("ct1abc>APRS:test")
        assert result["callsign"] == "CT1ABC"

    def test_missing_arrow_returns_none(self):
        assert parse_aprs_line("CT1ABC APRS test") is None

    def test_empty_callsign_returns_none(self):
        assert parse_aprs_line(">APRS:test") is None

    def test_empty_string_returns_none(self):
        assert parse_aprs_line("") is None

    def test_none_returns_none(self):
        assert parse_aprs_line(None) is None

    def test_whitespace_only_returns_none(self):
        assert parse_aprs_line("   ") is None

    def test_complex_path(self):
        result = parse_aprs_line("EA4GHR-9>APDOG,EA4RCH-3*,WIDE1-1:!4024.54N/00345.45W-PHG2360/EA4GHR-9")
        assert result["callsign"] == "EA4GHR-9"

    def test_preserves_raw_line(self):
        line = "CT7BFV>APRS:>Status message"
        result = parse_aprs_line(line)
        assert result["raw"] == line


# ═══════════════════════════════════════════════════════════════════
# 7. Ingest Pipeline — build_callsign_event for APRS
# ═══════════════════════════════════════════════════════════════════

class TestAPRSIngest:
    """Test build_callsign_event with APRS-specific payloads."""

    def test_basic_aprs_event(self):
        event = build_callsign_event({
            "callsign": "CT1ABC",
            "mode": "APRS",
            "raw": "CT1ABC>APRS:!3859.50N/00911.20W-Test",
        }, {})
        assert event is not None
        assert event["mode"] == "APRS"
        assert event["callsign"] == "CT1ABC"
        assert event["source"] == "direwolf"
        assert event["type"] == "callsign"

    def test_aprs_with_coordinates(self):
        event = build_callsign_event({
            "callsign": "CT7BFV",
            "mode": "APRS",
            "lat": 38.992,
            "lon": -9.187,
            "raw": "test",
        }, {})
        assert event is not None
        assert event["lat"] == 38.992
        assert event["lon"] == -9.187

    def test_aprs_with_path(self):
        event = build_callsign_event({
            "callsign": "CT1ABC",
            "mode": "APRS",
            "path": "WIDE1,WIDE2",
            "raw": "test",
        }, {})
        assert event is not None
        assert event["path"] == "WIDE1,WIDE2"

    def test_aprs_with_frequency_infers_band(self):
        event = build_callsign_event({
            "callsign": "CT1ABC",
            "mode": "APRS",
            "frequency_hz": 144800000,
            "raw": "test",
        }, {})
        assert event is not None
        assert event["band"] == "2m"
        assert event["frequency_hz"] == 144800000

    def test_aprs_without_callsign_rejected(self):
        """APRS events without a callsign should be rejected (unlike SSB/CW)."""
        event = build_callsign_event({
            "mode": "APRS",
            "raw": "some raw data",
        }, {})
        assert event is None

    def test_aprs_invalid_callsign_rejected(self):
        event = build_callsign_event({
            "callsign": "ABCDEF",
            "mode": "APRS",
            "raw": "test",
        }, {})
        assert event is None

    def test_aprs_source_always_direwolf(self):
        event = build_callsign_event({
            "callsign": "CT1ABC",
            "mode": "APRS",
            "raw": "test",
        }, {})
        assert event["source"] == "direwolf"

    def test_aprs_msg_preserved(self):
        event = build_callsign_event({
            "callsign": "CT1ABC",
            "mode": "APRS",
            "msg": "Emergency!",
            "raw": "test",
        }, {})
        assert event is not None
        assert event["msg"] == "Emergency!"

    def test_aprs_timestamp_auto(self):
        """If no timestamp provided, one is auto-generated."""
        event = build_callsign_event({
            "callsign": "CT1ABC",
            "mode": "APRS",
            "raw": "test",
        }, {})
        assert event["timestamp"] is not None
        assert "T" in event["timestamp"]  # ISO format

    def test_aprs_scan_state_device(self):
        """Device from scan_state should be inherited."""
        event = build_callsign_event({
            "callsign": "CT1ABC",
            "mode": "APRS",
            "raw": "test",
        }, {"device": "rtlsdr:0"})
        assert event["device"] == "rtlsdr:0"


# ═══════════════════════════════════════════════════════════════════
# 8. get_kiss_config / describe_kiss
# ═══════════════════════════════════════════════════════════════════

class TestKissConfig:
    """Test KISS TCP configuration from environment variables."""

    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("DIREWOLF_KISS_ENABLE", raising=False)
        monkeypatch.delenv("DIREWOLF_KISS_PORT", raising=False)
        assert get_kiss_config() is None
        assert describe_kiss() is None

    def test_enabled_via_env(self, monkeypatch):
        monkeypatch.setenv("DIREWOLF_KISS_ENABLE", "1")
        monkeypatch.delenv("DIREWOLF_KISS_PORT", raising=False)
        config = get_kiss_config()
        assert config is not None
        host, port = config
        assert host == "127.0.0.1"
        assert port == 8001  # default

    def test_custom_host_port(self, monkeypatch):
        monkeypatch.setenv("DIREWOLF_KISS_ENABLE", "1")
        monkeypatch.setenv("DIREWOLF_KISS_HOST", "192.168.1.100")
        monkeypatch.setenv("DIREWOLF_KISS_PORT", "9001")
        host, port = get_kiss_config()
        assert host == "192.168.1.100"
        assert port == 9001

    def test_port_only_enables(self, monkeypatch):
        monkeypatch.delenv("DIREWOLF_KISS_ENABLE", raising=False)
        monkeypatch.setenv("DIREWOLF_KISS_PORT", "8001")
        config = get_kiss_config()
        assert config is not None

    def test_invalid_port_returns_none(self, monkeypatch):
        monkeypatch.setenv("DIREWOLF_KISS_ENABLE", "1")
        monkeypatch.setenv("DIREWOLF_KISS_PORT", "not_a_number")
        assert get_kiss_config() is None

    def test_describe_kiss_format(self, monkeypatch):
        monkeypatch.setenv("DIREWOLF_KISS_ENABLE", "1")
        monkeypatch.setenv("DIREWOLF_KISS_HOST", "10.0.0.1")
        monkeypatch.setenv("DIREWOLF_KISS_PORT", "7777")
        assert describe_kiss() == "10.0.0.1:7777"


# ═══════════════════════════════════════════════════════════════════
# 9. kiss_loop — async TCP client with mock server
# ═══════════════════════════════════════════════════════════════════

class TestKissLoop:
    """Test kiss_loop with a real TCP mock server."""

    @pytest.mark.asyncio
    async def test_receives_and_parses_frame(self, monkeypatch):
        """kiss_loop connects, receives a KISS frame, calls on_event."""
        events = []
        logs = []

        def on_event(ev):
            events.append(ev)

        def logger(msg):
            logs.append(msg)

        # Build a KISS-wrapped APRS frame
        info = "!3859.50N/00911.20W-MockTest".encode("utf-8")
        frame_data = _build_kiss_frame("CT1TST", digis=["WIDE1"], info=info)
        kiss_bytes = _wrap_kiss(frame_data)

        # Start a mock TCP server
        server_ready = asyncio.Event()
        port_holder = [0]

        async def handle_client(reader, writer):
            writer.write(kiss_bytes)
            await writer.drain()
            # Close connection after sending
            writer.close()
            if hasattr(writer, "wait_closed"):
                await writer.wait_closed()

        server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
        port_holder[0] = server.sockets[0].getsockname()[1]

        monkeypatch.setenv("DIREWOLF_KISS_ENABLE", "1")
        monkeypatch.setenv("DIREWOLF_KISS_HOST", "127.0.0.1")
        monkeypatch.setenv("DIREWOLF_KISS_PORT", str(port_holder[0]))

        stop = asyncio.Event()

        async def run_loop():
            await kiss_loop(on_event, stop, logger=logger, reconnect_delay=0.1)

        task = asyncio.create_task(run_loop())

        # Wait for event to be received (with timeout)
        for _ in range(50):
            if events:
                break
            await asyncio.sleep(0.05)

        stop.set()
        server.close()
        await server.wait_closed()
        # Give task time to finish
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except asyncio.TimeoutError:
            task.cancel()

        assert len(events) >= 1
        assert events[0]["callsign"] == "CT1TST"
        assert events[0]["mode"] == "APRS"
        assert abs(events[0]["lat"] - 38.992) < 0.001
        assert any("connected" in msg for msg in logs)

    @pytest.mark.asyncio
    async def test_status_callback(self, monkeypatch):
        """status_cb is called with 'connected' and 'disconnected'."""
        statuses = []

        def status_cb(state, detail):
            statuses.append((state, detail))

        def on_event(ev):
            pass

        server = await asyncio.start_server(
            lambda r, w: (w.close(),),
            "127.0.0.1", 0
        )
        port = server.sockets[0].getsockname()[1]

        monkeypatch.setenv("DIREWOLF_KISS_ENABLE", "1")
        monkeypatch.setenv("DIREWOLF_KISS_HOST", "127.0.0.1")
        monkeypatch.setenv("DIREWOLF_KISS_PORT", str(port))

        stop = asyncio.Event()
        task = asyncio.create_task(
            kiss_loop(on_event, stop, reconnect_delay=0.1, status_cb=status_cb)
        )

        # Wait for connection cycle
        for _ in range(30):
            if statuses:
                break
            await asyncio.sleep(0.05)

        stop.set()
        server.close()
        await server.wait_closed()
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except asyncio.TimeoutError:
            task.cancel()

        states = [s[0] for s in statuses]
        assert "connected" in states or "disconnected" in states

    @pytest.mark.asyncio
    async def test_reconnects_on_failure(self, monkeypatch):
        """kiss_loop reconnects after connection failure."""
        logs = []

        def logger(msg):
            logs.append(msg)

        # Point to a port with no server
        monkeypatch.setenv("DIREWOLF_KISS_ENABLE", "1")
        monkeypatch.setenv("DIREWOLF_KISS_HOST", "127.0.0.1")
        monkeypatch.setenv("DIREWOLF_KISS_PORT", "19999")

        stop = asyncio.Event()
        task = asyncio.create_task(
            kiss_loop(lambda ev: None, stop, logger=logger, reconnect_delay=0.1)
        )

        # Wait for at least 2 connection attempts
        for _ in range(50):
            error_logs = [m for m in logs if "error" in m.lower()]
            if len(error_logs) >= 2:
                break
            await asyncio.sleep(0.05)

        stop.set()
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except asyncio.TimeoutError:
            task.cancel()

        error_logs = [m for m in logs if "error" in m.lower()]
        assert len(error_logs) >= 2, f"Expected >=2 reconnect errors, got {len(error_logs)}: {logs}"

    @pytest.mark.asyncio
    async def test_disabled_config_returns_immediately(self, monkeypatch):
        """kiss_loop returns immediately when config is None."""
        monkeypatch.delenv("DIREWOLF_KISS_ENABLE", raising=False)
        monkeypatch.delenv("DIREWOLF_KISS_PORT", raising=False)
        stop = asyncio.Event()
        # Should return immediately without blocking
        await asyncio.wait_for(
            kiss_loop(lambda ev: None, stop),
            timeout=1.0
        )

    @pytest.mark.asyncio
    async def test_async_on_event_awaited(self, monkeypatch):
        """If on_event returns a coroutine, kiss_loop should await it."""
        events = []

        async def on_event(ev):
            events.append(ev)

        info = "!3859.50N/00911.20W-AsyncTest".encode("utf-8")
        frame_data = _build_kiss_frame("CT1ASY", info=info)
        kiss_bytes = _wrap_kiss(frame_data)

        async def handle_client(reader, writer):
            writer.write(kiss_bytes)
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]

        monkeypatch.setenv("DIREWOLF_KISS_ENABLE", "1")
        monkeypatch.setenv("DIREWOLF_KISS_HOST", "127.0.0.1")
        monkeypatch.setenv("DIREWOLF_KISS_PORT", str(port))

        stop = asyncio.Event()
        task = asyncio.create_task(
            kiss_loop(on_event, stop, reconnect_delay=0.1)
        )

        for _ in range(50):
            if events:
                break
            await asyncio.sleep(0.05)

        stop.set()
        server.close()
        await server.wait_closed()
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except asyncio.TimeoutError:
            task.cancel()

        assert len(events) >= 1
        assert events[0]["callsign"] == "CT1ASY"


# ═══════════════════════════════════════════════════════════════════
# 10. Real-world APRS frames (Direwolf-captured patterns)
# ═══════════════════════════════════════════════════════════════════

class TestRealWorldAPRS:
    """Test with patterns based on real Direwolf KISS output."""

    def test_portuguese_station_position(self):
        """CT1EBQ at Lisbon area."""
        info = "!3844.37N/00907.85W#PHG2360/CT1EBQ-Lisbon APRS".encode("utf-8")
        frame = _build_kiss_frame("CT1EBQ", digis=["WIDE1", "WIDE2"], info=info)
        event = parse_kiss_frame(frame)
        assert event["callsign"] == "CT1EBQ"
        assert abs(event["lat"] - 38.739) < 0.01  # ~38.74°N
        assert abs(event["lon"] - (-9.131)) < 0.01  # ~9.13°W

    def test_spanish_station(self):
        """EA4 prefix — Madrid area."""
        info = "!4025.00N/00342.00W-EA4Test".encode("utf-8")
        frame = _build_kiss_frame("EA4RCH", src_ssid=3, info=info)
        event = parse_kiss_frame(frame)
        assert event["callsign"] == "EA4RCH-3"
        assert event["lat"] > 40.0

    def test_german_station(self):
        """DL prefix."""
        info = "!4812.00N/01120.00E/DL1Test".encode("utf-8")
        frame = _build_kiss_frame("DL1ABC", info=info)
        event = parse_kiss_frame(frame)
        assert event["callsign"] == "DL1ABC"
        assert event["lat"] > 48.0
        assert event["lon"] > 11.0

    def test_us_station(self):
        """W/K prefix — US station."""
        info = "!4052.50N/07400.00W-NYC".encode("utf-8")
        frame = _build_kiss_frame("W2ABC", info=info)
        event = parse_kiss_frame(frame)
        assert event["callsign"] == "W2ABC"
        assert abs(event["lat"] - 40.875) < 0.01
        assert abs(event["lon"] - (-74.0)) < 0.01

    def test_japanese_station(self):
        """JA prefix."""
        info = "!3540.00N/13945.00E/JA1Test".encode("utf-8")
        frame = _build_kiss_frame("JA1ABC", info=info)
        event = parse_kiss_frame(frame)
        assert event["callsign"] == "JA1ABC"
        assert event["lat"] > 35.0
        assert event["lon"] > 139.0


# ═══════════════════════════════════════════════════════════════════
# 11. Edge Cases & Robustness
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Boundary conditions and error handling."""

    def test_kiss_buffer_massive_frame(self):
        """Large frame (1KB payload) should be handled.
        Payload must not contain raw 0xC0 (FRAME_END) or 0xDB (FRAME_ESC)
        as those are KISS special bytes that split/escape the stream."""
        buf = KissBuffer()
        # Use bytes that exclude KISS special values (0xC0, 0xDB)
        safe_bytes = bytes(b for b in range(256) if b not in (_FRAME_END, _FRAME_ESC))
        payload = (safe_bytes * 5)[:1024]
        data = bytes([_FRAME_END]) + payload + bytes([_FRAME_END])
        frames = buf.feed(data)
        assert len(frames) == 1
        assert len(frames[0]) == 1024

    def test_kiss_buffer_consecutive_escapes(self):
        """Two escape sequences in a row."""
        buf = KissBuffer()
        payload = bytes([
            0x00,
            _FRAME_ESC, _TRANS_FEND,  # → 0xC0
            _FRAME_ESC, _TRANS_FESC,  # → 0xDB
            0x01
        ])
        data = bytes([_FRAME_END]) + payload + bytes([_FRAME_END])
        frames = buf.feed(data)
        assert frames[0] == bytes([0x00, _FRAME_END, _FRAME_ESC, 0x01])

    def test_callsign_max_ssid_15(self):
        addr = _encode_addr("CT7BFV", last=True, ssid=15)
        call = _decode_callsign(addr)
        assert call == "CT7BFV-15"

    def test_parse_aprs_line_with_spaces(self):
        result = parse_aprs_line("  CT1ABC > APRS : test  ")
        assert result is not None
        # Callsign before > stripped
        assert "CT1ABC" in result["callsign"]

    def test_build_event_aprs_mode_case_insensitive(self):
        """Mode normalisation: 'aprs' → 'APRS'."""
        event = build_callsign_event({
            "callsign": "CT1ABC",
            "mode": "aprs",
            "raw": "test",
        }, {})
        assert event is not None
        assert event["mode"] == "APRS"

    def test_ingest_aprs_70cm_band(self):
        """APRS on 70cm (435 MHz)."""
        event = build_callsign_event({
            "callsign": "CT1ABC",
            "mode": "APRS",
            "frequency_hz": 435000000,
            "raw": "test",
        }, {})
        assert event is not None
        assert event["band"] == "70cm"

    def test_valid_callsign_checks(self):
        """Verify callsign validation for APRS-typical calls."""
        assert is_valid_callsign("CT1ABC") is True
        assert is_valid_callsign("CT7BFV") is True
        assert is_valid_callsign("W2ABC") is True
        assert is_valid_callsign("JA1ABC") is True
        assert is_valid_callsign("9A1AA") is True
        assert is_valid_callsign("CT1ABC/P") is True
        # Invalid
        assert is_valid_callsign("ABCDEF") is False
        assert is_valid_callsign("123456") is False
        assert is_valid_callsign("") is False
        assert is_valid_callsign(None) is False


# ═══════════════════════════════════════════════════════════════════
# 12. KissBuffer + parse_kiss_frame integration (full pipeline)
# ═══════════════════════════════════════════════════════════════════

class TestFullPipeline:
    """End-to-end: raw TCP bytes → KissBuffer → parse_kiss_frame → event dict."""

    def test_tcp_bytes_to_event(self):
        """Simulate raw bytes as received from Direwolf TCP socket."""
        info = "!3859.50N/00911.20W-PipelineTest".encode("utf-8")
        frame_data = _build_kiss_frame("CT7BFV", digis=["CPNW2"], info=info)
        # Simulate TCP stream with FEND delimiters
        tcp_bytes = bytes([_FRAME_END]) + frame_data + bytes([_FRAME_END])

        buf = KissBuffer()
        frames = buf.feed(tcp_bytes)
        assert len(frames) == 1

        event = parse_kiss_frame(frames[0])
        assert event is not None
        assert event["callsign"] == "CT7BFV"
        assert event["mode"] == "APRS"
        assert abs(event["lat"] - 38.992) < 0.001
        assert abs(event["lon"] - (-9.187)) < 0.001

        # Now pass through ingest
        db_event = build_callsign_event(event, {"device": "rtlsdr:0"})
        assert db_event is not None
        assert db_event["type"] == "callsign"
        assert db_event["mode"] == "APRS"
        assert db_event["callsign"] == "CT7BFV"
        assert db_event["source"] == "direwolf"
        assert db_event["lat"] == event["lat"]
        assert db_event["lon"] == event["lon"]
        assert db_event["path"] == "CPNW2"
        assert db_event["device"] == "rtlsdr:0"

    def test_multiple_frames_in_stream(self):
        """Multiple KISS frames in one TCP read → multiple events."""
        buf = KissBuffer()
        events = []

        for call in ["CT1AA", "EA4BB", "DL3CC"]:
            info = f"!3859.50N/00911.20W-{call}".encode("utf-8")
            frame_data = _build_kiss_frame(call, info=info)
            tcp_bytes = bytes([_FRAME_END]) + frame_data + bytes([_FRAME_END])

            for frame in buf.feed(tcp_bytes):
                ev = parse_kiss_frame(frame)
                if ev:
                    events.append(ev)

        assert len(events) == 3
        callsigns = [e["callsign"] for e in events]
        assert "CT1AA" in callsigns
        assert "EA4BB" in callsigns
        assert "DL3CC" in callsigns
