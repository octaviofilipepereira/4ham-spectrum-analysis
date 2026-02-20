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


def parse_ax25_source(frame):
    if not frame:
        return None
    if frame[0] & 0x0F != 0:
        return None
    if len(frame) < 15:
        return None
    dest = frame[1:8]
    src = frame[8:15]
    src_call = _decode_callsign(src)
    return src_call


def parse_kiss_frame(frame):
    if not frame:
        return None
    port_cmd = frame[0]
    if port_cmd & 0x0F != 0x00:
        return None
    ax25 = frame[1:]
    callsign = parse_ax25_source(ax25)
    if not callsign:
        return None
    return {
        "callsign": callsign,
        "raw": ax25.hex(),
        "mode": "APRS"
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
