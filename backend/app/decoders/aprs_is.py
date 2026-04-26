# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

"""
APRS-IS Client
==============
Connects to the APRS Internet Service (APRS-IS) to receive real-time
APRS packets from the global network.  This complements the RF pipeline
(rtl_fm → Direwolf → KISS TCP) by adding Internet-sourced stations.

Protocol reference: http://www.aprs-is.net/Connecting.aspx
"""

import asyncio
import os
import re
import socket

from app.decoders.aprs_parser import parse_aprs_packet


# ── Configuration ────────────────────────────────────────────────────
#
# Host/port are read from the environment on every connection attempt
# (not captured at import time) so that the Admin Config UI can change
# them at runtime via /api/settings without a backend restart. Falling
# back to the official APRS-IS DNS rotator keeps the behaviour identical
# when the user does not override the value.

DEFAULT_APRS_IS_HOST = "rotate.aprs2.net"
DEFAULT_APRS_IS_PORT = 14580


def _get_host() -> str:
    return os.getenv("APRS_IS_HOST", DEFAULT_APRS_IS_HOST) or DEFAULT_APRS_IS_HOST


def _get_port() -> int:
    try:
        return int(os.getenv("APRS_IS_PORT", str(DEFAULT_APRS_IS_PORT)))
    except (TypeError, ValueError):
        return DEFAULT_APRS_IS_PORT


APRS_IS_FILTER_RANGE_KM = int(os.getenv("APRS_IS_RANGE_KM", "150"))


def _compute_passcode(callsign: str) -> int:
    """Compute APRS-IS passcode from callsign (base only, no SSID)."""
    base = callsign.split("-")[0].upper()
    code = 0x73E2
    for i in range(0, len(base) - 1, 2):
        code ^= ord(base[i]) << 8
        code ^= ord(base[i + 1])
    if len(base) % 2:
        code ^= ord(base[-1]) << 8
    return code & 0x7FFF


# ── APRS-IS line parser ─────────────────────────────────────────────

# Standard uncompressed position pattern:
# SRC>DST,PATH:!DDMM.MMN/DDDMM.MMW...   or  =DDMM.MMN/DDDMM.MMW...
_POS_RE = re.compile(
    r"^([A-Za-z0-9/\-]{3,9})>([^:]+):([!=@/])"
    r"(\d{4}\.\d{2}[NS])(.)(\d{5}\.\d{2}[EW])(.)(.*)"
)

# Object pattern:  ;name_____*DDMM.MMN/DDDMM.MMW...
_OBJECT_RE = re.compile(
    r"^([A-Za-z0-9/\-]{3,9})>([^:]+):[;)](.{9})\*"
    r"(\d{4}\.\d{2}[NS])(.)(\d{5}\.\d{2}[EW])(.)(.*)"
)

# Mic-E position is encoded in the destination field — simplified
# detection only (full Mic-E decoding is complex).
_MICE_DT_RE = re.compile(
    r"^([A-Za-z0-9/\-]{3,9})>([A-Z0-9]{6}),([^:]+):`(.+)"
)

# Compressed position: SRC>DST,PATH:[!=@/]<sym_table><4 lat><4 lon><sym_code>...
_COMPRESSED_RE = re.compile(
    r"^([A-Za-z0-9/\-]{3,9})>([^:]+):([!=@/])([/\\A-Z])([\x21-\x7c]{4})([\x21-\x7c]{4})(.)(.{3})(.*)"
)


def _parse_lat(raw: str) -> float | None:
    """Parse 'DDMM.MMN' → decimal degrees."""
    try:
        deg = int(raw[0:2])
        minutes = float(raw[2:7])
        hem = raw[7]
        lat = deg + minutes / 60.0
        if hem == "S":
            lat = -lat
        return lat
    except (ValueError, IndexError):
        return None


def _parse_lon(raw: str) -> float | None:
    """Parse 'DDDMM.MME' → decimal degrees."""
    try:
        deg = int(raw[0:3])
        minutes = float(raw[3:8])
        hem = raw[8]
        lon = deg + minutes / 60.0
        if hem == "W":
            lon = -lon
        return lon
    except (ValueError, IndexError):
        return None


def _decode_compressed_lat(chars: str) -> float:
    """Decode 4 base-91 characters into latitude (decimal degrees)."""
    val = 0
    for ch in chars:
        val = val * 91 + (ord(ch) - 33)
    return 90.0 - val / 380926.0


def _decode_compressed_lon(chars: str) -> float:
    """Decode 4 base-91 characters into longitude (decimal degrees)."""
    val = 0
    for ch in chars:
        val = val * 91 + (ord(ch) - 33)
    return -180.0 + val / 190463.0


def parse_aprs_is_line(line: str) -> dict | None:
    """
    Parse a single APRS-IS text line into an event dict.
    Returns None for server comments, malformed lines, or packets without
    a recognised position.

    Delegates to aprslib via :mod:`app.decoders.aprs_parser`, which
    supports the full APRS spec including Mic-E.  Falls back to the
    legacy hand-rolled regexes for the few packets aprslib rejects.
    """
    if not line or line.startswith("#"):
        return None

    event = parse_aprs_packet(line)
    if event and event.get("lat") is not None and event.get("lon") is not None:
        event["source"] = "aprs_is"
        # Frames received over TCP from APRS-IS always carry TCPIP in the
        # path – that is the *transport*, not an indication that a local
        # iGate re-broadcast the frame on RF. The rf_gated flag is only
        # meaningful for RF receivers (Direwolf KISS); force it off here.
        event["rf_gated"] = None
        return event

    # Legacy fallback (uncompressed / compressed / object) for packets
    # aprslib could not handle.
    m = _POS_RE.match(line)
    if m:
        src, path_str, _dtype, lat_raw, sym_table, lon_raw, sym_code, comment = m.groups()
        lat = _parse_lat(lat_raw)
        lon = _parse_lon(lon_raw)
        if lat is None or lon is None:
            return None
        return {
            "callsign": src,
            "path": path_str,
            "lat": lat,
            "lon": lon,
            "msg": comment.strip() if comment else None,
            "raw": line,
            "mode": "APRS",
            "source": "aprs_is",
            "symbol_table": sym_table,
            "symbol_code": sym_code,
        }

    m = _COMPRESSED_RE.match(line)
    if m:
        src, path_str, _dtype, sym_table, lat_chars, lon_chars, sym_code, _csT, comment = m.groups()
        try:
            lat = _decode_compressed_lat(lat_chars)
            lon = _decode_compressed_lon(lon_chars)
            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                return {
                    "callsign": src,
                    "path": path_str,
                    "lat": lat,
                    "lon": lon,
                    "msg": comment.strip() if comment else None,
                    "raw": line,
                    "mode": "APRS",
                    "source": "aprs_is",
                    "symbol_table": sym_table,
                    "symbol_code": sym_code,
                }
        except (ValueError, IndexError):
            pass

    m = _OBJECT_RE.match(line)
    if m:
        src, path_str, obj_name, lat_raw, sym_table, lon_raw, sym_code, comment = m.groups()
        lat = _parse_lat(lat_raw)
        lon = _parse_lon(lon_raw)
        if lat is None or lon is None:
            return None
        return {
            "callsign": obj_name.strip(),
            "path": path_str,
            "lat": lat,
            "lon": lon,
            "msg": comment.strip() if comment else None,
            "raw": line,
            "mode": "APRS",
            "source": "aprs_is",
            "symbol_table": sym_table,
            "symbol_code": sym_code,
        }

    return None


# ── Internet connectivity check ──────────────────────────────────────

def check_internet(timeout: float = 3.0) -> bool:
    """Quick check: can we reach a public DNS resolver?"""
    try:
        s = socket.create_connection(("1.1.1.1", 53), timeout=timeout)
        s.close()
        return True
    except OSError:
        return False


# ── APRS-IS async loop ──────────────────────────────────────────────

async def aprs_is_loop(
    callsign: str,
    lat: float,
    lon: float,
    on_event,
    stop_event: asyncio.Event,
    logger=None,
    reconnect_delay: float = 10.0,
    status_cb=None,
    range_km: int | None = None,
):
    """
    Connect to APRS-IS, authenticate, set a range filter, and stream
    packets.  Calls *on_event(dict)* for each parsed APRS packet
    that has position data.

    Parameters
    ----------
    callsign : str
        Station callsign for login (e.g. "CT7BFV").
    lat, lon : float
        QTH coordinates for the range filter.
    on_event : callable
        Callback receiving a parsed event dict. May be sync or async.
    stop_event : asyncio.Event
        Set this to stop the loop gracefully.
    range_km : int, optional
        Override the default filter range (default: APRS_IS_FILTER_RANGE_KM).
    """
    if range_km is None:
        range_km = APRS_IS_FILTER_RANGE_KM

    passcode = _compute_passcode(callsign)
    login_line = (
        f"user {callsign} pass {passcode} vers 4HAM 1.0 "
        f"filter r/{lat:.4f}/{lon:.4f}/{range_km}\r\n"
    )

    while not stop_event.is_set():
        reader = writer = None
        host = _get_host()
        port = _get_port()
        try:
            if logger:
                logger(f"aprs_is_connecting:{host}:{port}")
            if status_cb:
                status_cb("connecting", f"{host}:{port}")

            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=15.0,
            )

            # Read server banner
            banner = await asyncio.wait_for(reader.readline(), timeout=10.0)
            if logger:
                logger(f"aprs_is_banner:{banner.decode(errors='ignore').strip()}")

            # Send login
            writer.write(login_line.encode())
            await writer.drain()

            # Read login response
            resp = await asyncio.wait_for(reader.readline(), timeout=10.0)
            resp_str = resp.decode(errors="ignore").strip()
            if logger:
                logger(f"aprs_is_login_response:{resp_str}")
            if "logresp" not in resp_str.lower():
                if status_cb:
                    status_cb("error", f"bad login response: {resp_str}")
                await asyncio.sleep(reconnect_delay)
                continue

            if status_cb:
                status_cb("connected", f"{host}:{port}")

            # Main receive loop
            while not stop_event.is_set():
                try:
                    line_bytes = await asyncio.wait_for(
                        reader.readline(), timeout=90.0
                    )
                except asyncio.TimeoutError:
                    # Send keepalive
                    writer.write(b"#keepalive\r\n")
                    await writer.drain()
                    continue

                if not line_bytes:
                    break  # Connection closed

                line = line_bytes.decode(errors="ignore").strip()
                if not line or line.startswith("#"):
                    continue

                event = parse_aprs_is_line(line)
                if event:
                    result = on_event(event)
                    if asyncio.iscoroutine(result):
                        await result

        except asyncio.CancelledError:
            break
        except Exception as exc:
            if logger:
                logger(f"aprs_is_error:{exc}")
            if status_cb:
                status_cb("error", str(exc))
        finally:
            if writer:
                try:
                    writer.close()
                    if hasattr(writer, "wait_closed"):
                        await writer.wait_closed()
                except Exception:
                    pass
            if status_cb:
                status_cb("disconnected", "")

        if not stop_event.is_set():
            await asyncio.sleep(reconnect_delay)
