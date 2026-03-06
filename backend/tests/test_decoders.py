# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 16:27:19 UTC

import struct
import json

from app.decoders.direwolf_kiss import parse_kiss_frame
from app.decoders.ingest import build_callsign_event
from app.decoders.parsers import parse_ssb_asr_text


def _encode_addr(call, last=False, ssid=0):
    call = call.ljust(6)
    addr = bytes([(ord(ch) << 1) & 0xFE for ch in call])
    ssid_byte = 0x60 | ((ssid & 0x0F) << 1)
    if last:
        ssid_byte |= 0x01
    return addr + bytes([ssid_byte])


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
    assert event["parse_method"] == "phonetic"


def test_ssb_asr_parser_returns_none_without_callsign():
    event = parse_ssb_asr_text("good afternoon station with strong signal")
    assert event is None


def test_ssb_asr_parser_extracts_grid_report_and_frequency():
    event = parse_ssb_asr_text("CT1ABC IN51 59 14.255 MHz")
    assert event is not None
    assert event["callsign"] == "CT1ABC"
    assert event["parse_method"] == "direct"
    assert event["grid"] == "IN51"
    assert event["report"] == "59"
    assert event["frequency_hz"] == 14255000


def test_ssb_asr_parser_accepts_french_number_words():
    event = parse_ssb_asr_text("appel charlie tango un alpha bravo charlie portatif")
    assert event is not None
    assert event["callsign"] == "CT1ABC/P"


def test_ssb_asr_parser_accepts_german_number_words_with_umlaut():
    event = parse_ssb_asr_text("hier charlie tango fünf alpha bravo charlie portabel")
    assert event is not None
    assert event["callsign"] == "CT5ABC/P"


def test_build_callsign_event_allows_ssb_traffic_without_callsign():
    event = build_callsign_event(
        {
            "mode": "SSB",
            "raw": "good afternoon all stations",
            "msg": "good afternoon all stations",
            "ssb_state": "SSB_TRAFFIC",
            "ssb_score": 0.41,
            "ssb_parse_method": "none",
        },
        {},
    )
    assert event is not None
    assert event["mode"] == "SSB"
    assert event["callsign"] == ""
    payload = json.loads(event["payload"])
    assert payload["ssb_state"] == "SSB_TRAFFIC"
    assert float(payload["ssb_score"]) == 0.41
    assert payload["ssb_parse_method"] == "none"


def test_build_callsign_event_infers_20m_band_from_frequency():
    event = build_callsign_event({"callsign": "CT1ABC", "frequency_hz": 14255000}, {})
    assert event is not None
    assert event["band"] == "20m"


def test_build_callsign_event_infers_15m_band_from_frequency():
    event = build_callsign_event({"callsign": "CT1ABC", "frequency_hz": 21250000}, {})
    assert event is not None
    assert event["band"] == "15m"


def test_build_callsign_event_preserves_power_dbm():
    event = build_callsign_event(
        {"callsign": "CT1ABC", "frequency_hz": 14250000, "power_dbm": -73.2},
        {}
    )
    assert event is not None
    assert float(event["power_dbm"]) == -73.2