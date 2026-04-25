# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

"""
APRS Packet Parser (aprslib wrapper)
====================================
Single entry point for decoding APRS packets in TNC2 monitor format
("SRC>DST,PATH:payload").  Wraps the third-party ``aprslib`` library
which supports the full APRS spec including Mic-E (the ``\u0060`` payload
prefix used by Kenwood TH-D7e, GPS-equipped mobile rigs, etc.).

This module replaces the hand-rolled regex parsers that previously lived
in ``aprs_is.py``, ``direwolf_kiss.py`` and ``parsers.py``, all of which
silently dropped position data for Mic-E packets.
"""

from __future__ import annotations

from typing import Optional

import aprslib


# Exceptions raised by aprslib when a line cannot be parsed.
_PARSE_EXC = (
    aprslib.exceptions.ParseError,
    aprslib.exceptions.UnknownFormat,
)


def parse_aprs_packet(line: str) -> Optional[dict]:
    """
    Parse an APRS packet in TNC2 monitor format.

    Returns a normalised event dict on success, or ``None`` if the line is
    malformed or carries no recognised position.

    The returned dict shape matches what the rest of the codebase already
    expects from ``parse_aprs_is_line`` / ``parse_kiss_frame``:

        {
            "callsign":     str,           # source callsign with SSID
            "path":         str,           # comma-joined digipeater path
            "lat":          float | None,
            "lon":          float | None,
            "msg":          str | None,    # comment text
            "raw":          str,           # original line
            "mode":         "APRS",
            "symbol_table": str | None,
            "symbol_code":  str | None,
            "format":       str,           # 'mic-e' / 'uncompressed' / ...
        }

    Position-less packets (status, message, telemetry, weather without
    position) are returned with ``lat=None`` / ``lon=None`` so downstream
    storage still keeps the callsign event for traffic statistics.
    """
    if not line:
        return None

    text = str(line).strip()
    if not text or text.startswith("#"):
        return None

    try:
        parsed = aprslib.parse(text)
    except _PARSE_EXC:
        return None
    except Exception:
        # Defensive: never let a malformed packet take down the loop.
        return None

    # Third-party traffic ('}' DTI): digipeaters/iGates re-transmit packets
    # from other stations encapsulated in their own frame. The real
    # callsign + position lives in 'subpacket'. Unwrap (up to a few levels
    # in case of nested 3rd-party traffic, which is legal but rare).
    for _ in range(4):
        if parsed.get("format") == "thirdparty" and isinstance(parsed.get("subpacket"), dict):
            parsed = parsed["subpacket"]
        else:
            break

    src = parsed.get("from")
    if not src:
        return None

    lat = parsed.get("latitude")
    lon = parsed.get("longitude")
    if lat is not None and lon is not None:
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            lat_f = lon_f = None
        else:
            if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
                lat_f = lon_f = None
    else:
        lat_f = lon_f = None

    path_list = parsed.get("path") or []
    if isinstance(path_list, list):
        path_str = ",".join(str(p) for p in path_list if p)
    else:
        path_str = str(path_list)

    comment = parsed.get("comment")
    if isinstance(comment, str):
        comment = comment.strip() or None
    else:
        comment = None

    return {
        "callsign":     str(src).upper(),
        "path":         path_str,
        "lat":          lat_f,
        "lon":          lon_f,
        "msg":          comment,
        "raw":          text,
        "mode":         "APRS",
        "symbol_table": parsed.get("symbol_table"),
        "symbol_code":  parsed.get("symbol"),
        "format":       parsed.get("format"),
    }


def build_tnc2_line(src: str, dest: str, path, info) -> Optional[str]:
    """
    Reconstruct a TNC2 monitor-format line from AX.25 frame components.

    Used by the Direwolf KISS decoder, which receives raw AX.25 frames
    instead of pre-formatted text lines.
    """
    if not src or not dest:
        return None

    path = path or []
    if isinstance(path, (list, tuple)):
        path_str = ",".join(str(p) for p in path if p)
    else:
        path_str = str(path)

    if isinstance(info, (bytes, bytearray)):
        info_text = info.decode("utf-8", errors="ignore")
    elif info is None:
        info_text = ""
    else:
        info_text = str(info)

    header = f"{src}>{dest}"
    if path_str:
        header = f"{header},{path_str}"
    return f"{header}:{info_text}"
