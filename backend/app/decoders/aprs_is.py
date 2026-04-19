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


# ── Configuration ────────────────────────────────────────────────────

APRS_IS_HOST = os.getenv("APRS_IS_HOST", "rotate.aprs2.net")
APRS_IS_PORT = int(os.getenv("APRS_IS_PORT", "14580"))
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


def parse_aprs_is_line(line: str) -> dict | None:
    """
    Parse a single APRS-IS text line into an event dict.
    Returns None for server comments, malformed lines, or lines without position.
    """
    if not line or line.startswith("#"):
        return None

    # Try uncompressed position (! = / @)
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

    # Try object/item
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

    # Lines without recognised position data — skip
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
        try:
            if logger:
                logger(f"aprs_is_connecting:{APRS_IS_HOST}:{APRS_IS_PORT}")
            if status_cb:
                status_cb("connecting", f"{APRS_IS_HOST}:{APRS_IS_PORT}")

            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(APRS_IS_HOST, APRS_IS_PORT),
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
                status_cb("connected", f"{APRS_IS_HOST}:{APRS_IS_PORT}")

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
