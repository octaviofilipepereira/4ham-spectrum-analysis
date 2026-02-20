import struct

from app.decoders.direwolf_kiss import parse_kiss_frame
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