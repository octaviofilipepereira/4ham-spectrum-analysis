# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

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


def _parse_aprs_payload(text):
    if not text:
        return {}, None
    payload = str(text)
    if len(payload) >= 20 and payload[0] in ("!", "="):
        lat_raw = payload[1:9]
        symbol_table = payload[9]
        lon_raw = payload[10:19]
        symbol_code = payload[19]
        comment = payload[20:]
        try:
            lat_deg = int(lat_raw[0:2])
            lat_min = float(lat_raw[2:7])
            lat_hem = lat_raw[7]
            lon_deg = int(lon_raw[0:3])
            lon_min = float(lon_raw[3:8])
            lon_hem = lon_raw[8]
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
                "symbol_code": symbol_code
            }, payload
        except (ValueError, IndexError):
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
        "msg": extras.get("msg")
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
