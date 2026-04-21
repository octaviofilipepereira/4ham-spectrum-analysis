# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 16:27:19 UTC

import asyncio
import os


_FRAME_END = 0xC0
_FRAME_ESC = 0xDB
_TRANS_FEND = 0xDC
_TRANS_FESC = 0xDD


class KissBuffer:
    def __init__(self):
        self.buffer = bytearray()
        self.in_frame = False
        self.escape = False

    def feed(self, data):
        frames = []
        for byte in data:
            if byte == _FRAME_END:
                if self.in_frame and self.buffer:
                    frames.append(bytes(self.buffer))
                self.buffer = bytearray()
                self.in_frame = True
                self.escape = False
                continue

            if not self.in_frame:
                continue

            if self.escape:
                if byte == _TRANS_FEND:
                    self.buffer.append(_FRAME_END)
                elif byte == _TRANS_FESC:
                    self.buffer.append(_FRAME_ESC)
                else:
                    self.buffer.append(byte)
                self.escape = False
                continue

            if byte == _FRAME_ESC:
                self.escape = True
                continue

            self.buffer.append(byte)
        return frames


def _decode_callsign(addr):
    if len(addr) < 7:
        return None
    call = "".join([chr((b >> 1) & 0x7F) for b in addr[:6]]).strip()
    if not call:
        return None
    ssid = (addr[6] >> 1) & 0x0F
    if ssid:
        call = f"{call}-{ssid}"
    return call


def _decode_address(addr):
    if len(addr) < 7:
        return None, False
    call = _decode_callsign(addr)
    last = bool(addr[6] & 0x01)
    return call, last


def _parse_ax25(frame):
    if not frame or len(frame) < 14:
        return None
    offset = 0
    addresses = []
    for _ in range(10):
        if offset + 7 > len(frame):
            break
        call, last = _decode_address(frame[offset:offset + 7])
        addresses.append(call)
        offset += 7
        if last:
            break

    if len(addresses) < 2:
        return None

    dest = addresses[0]
    src = addresses[1]
    path = [call for call in addresses[2:] if call]
    if offset + 2 > len(frame):
        return {
            "dest": dest,
            "src": src,
            "path": path,
            "info": None
        }

    control = frame[offset]
    pid = frame[offset + 1]
    info = frame[offset + 2:]
    if control != 0x03 or pid != 0xF0:
        info = frame[offset + 2:]

    return {
        "dest": dest,
        "src": src,
        "path": path,
        "info": info
    }


def _decode_compressed_lat(chars):
    """Decode 4 base-91 characters into latitude (decimal degrees)."""
    val = 0
    for ch in chars:
        val = val * 91 + (ord(ch) - 33)
    return 90.0 - val / 380926.0


def _decode_compressed_lon(chars):
    """Decode 4 base-91 characters into longitude (decimal degrees)."""
    val = 0
    for ch in chars:
        val = val * 91 + (ord(ch) - 33)
    return -180.0 + val / 190463.0


def _is_compressed_position(payload, offset):
    """Check if payload[offset:] looks like a compressed APRS position.
    Compressed format: <sym_table><4 lat chars><4 lon chars><sym_code>..."""
    if len(payload) < offset + 10:
        return False
    sym_table = payload[offset]
    if sym_table not in ("/", "\\") and not sym_table.isupper():
        return False
    # All 8 base-91 position chars must be in printable range 33–124
    for ch in payload[offset + 1:offset + 9]:
        if not (33 <= ord(ch) <= 124):
            return False
    return True


def _parse_aprs_payload(text):
    if not text:
        return {}, None
    payload = str(text)
    if len(payload) < 2 or payload[0] not in ("!", "=", "/", "@"):
        return {}, payload

    # Determine offset after data-type indicator
    dtype = payload[0]
    if dtype in ("/", "@"):
        # Timestamped position: 7 chars timestamp after dtype
        offset = 8
    else:
        offset = 1

    # Try uncompressed position first: !DDMM.MMN/DDDMM.MMW...
    if len(payload) >= offset + 19:
        lat_raw = payload[offset:offset + 8]
        symbol_table = payload[offset + 8]
        lon_raw = payload[offset + 9:offset + 18]
        symbol_code = payload[offset + 18]
        comment = payload[offset + 19:]
        try:
            lat_deg = int(lat_raw[0:2])
            lat_min = float(lat_raw[2:7])
            lat_hem = lat_raw[7]
            lon_deg = int(lon_raw[0:3])
            lon_min = float(lon_raw[3:8])
            lon_hem = lon_raw[8]
            if lat_hem in ("N", "S") and lon_hem in ("E", "W"):
                lat = lat_deg + (lat_min / 60.0)
                lon = lon_deg + (lon_min / 60.0)
                if lat_hem == "S":
                    lat = -lat
                if lon_hem == "W":
                    lon = -lon
                return {
                    "lat": lat,
                    "lon": lon,
                    "msg": comment.strip() if comment else None,
                    "symbol_table": symbol_table,
                    "symbol_code": symbol_code,
                }, payload
        except (ValueError, IndexError):
            pass

    # Try compressed format: <sym_table><4 lat b91><4 lon b91><sym_code>...
    if _is_compressed_position(payload, offset):
        try:
            sym_table = payload[offset]
            lat = _decode_compressed_lat(payload[offset + 1:offset + 5])
            lon = _decode_compressed_lon(payload[offset + 5:offset + 9])
            sym_code = payload[offset + 9]
            comment = payload[offset + 13:] if len(payload) > offset + 13 else ""
            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                return {
                    "lat": lat,
                    "lon": lon,
                    "msg": comment.strip() if comment else None,
                    "symbol_table": sym_table,
                    "symbol_code": sym_code,
                }, payload
        except (ValueError, IndexError):
            pass

    return {}, payload

    return {}, payload


def parse_kiss_frame(frame):
    if not frame:
        return None
    port_cmd = frame[0]
    if port_cmd & 0x0F != 0x00:
        return None
    ax25 = frame[1:]
    parsed = _parse_ax25(ax25)
    if not parsed or not parsed.get("src"):
        return None
    info_bytes = parsed.get("info")
    payload_text = None
    if info_bytes:
        payload_text = info_bytes.decode("utf-8", errors="ignore")
    extras, payload = _parse_aprs_payload(payload_text)
    return {
        "callsign": parsed.get("src"),
        "raw": payload or (payload_text or ax25.hex()),
        "mode": "APRS",
        "path": ",".join(parsed.get("path") or []),
        "payload": payload,
        "lat": extras.get("lat"),
        "lon": extras.get("lon"),
        "msg": extras.get("msg"),
        "symbol_table": extras.get("symbol_table"),
        "symbol_code": extras.get("symbol_code"),
    }


def get_kiss_config():
    host = os.getenv("DIREWOLF_KISS_HOST", "127.0.0.1")
    port = os.getenv("DIREWOLF_KISS_PORT")
    enabled = os.getenv("DIREWOLF_KISS_ENABLE")
    if not enabled and not port:
        return None
    try:
        port = int(port or 8001)
    except ValueError:
        return None
    return host, port


def describe_kiss():
    config = get_kiss_config()
    if not config:
        return None
    host, port = config
    return f"{host}:{port}"


async def kiss_loop(on_event, stop_event, logger=None, reconnect_delay=3.0, status_cb=None):
    config = get_kiss_config()
    if not config:
        return
    host, port = config
    buffer = KissBuffer()

    while not stop_event.is_set():
        try:
            reader, writer = await asyncio.open_connection(host, port)
            if logger:
                logger(f"direwolf_kiss_connected {host}:{port}")
            if status_cb:
                status_cb("connected", f"{host}:{port}")
            while not stop_event.is_set():
                data = await reader.read(1024)
                if not data:
                    break
                for frame in buffer.feed(data):
                    event = parse_kiss_frame(frame)
                    if not event:
                        continue
                    result = on_event(event)
                    if asyncio.iscoroutine(result):
                        await result
            writer.close()
            if hasattr(writer, "wait_closed"):
                await writer.wait_closed()
            if status_cb:
                status_cb("disconnected", f"{host}:{port}")
        except Exception as exc:
            if logger:
                logger(f"direwolf_kiss_error {exc}")
            if status_cb:
                status_cb("error", str(exc))
            await asyncio.sleep(reconnect_delay)
        if not stop_event.is_set():
            await asyncio.sleep(reconnect_delay)
