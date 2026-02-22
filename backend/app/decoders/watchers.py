# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 00:34:50 UTC

import asyncio
import os


def _should_start_from_end(flag_value):
    if not flag_value:
        return True
    value = str(flag_value).strip().lower()
    return value not in {"1", "true", "yes", "on"}


async def tail_lines(path, on_line, stop_event, poll_s=1.0, from_end=True):
    offset = 0
    if from_end and os.path.exists(path):
        try:
            offset = os.path.getsize(path)
        except OSError:
            offset = 0

    while not stop_event.is_set():
        if not os.path.exists(path):
            await asyncio.sleep(poll_s)
            continue

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                handle.seek(offset)
                chunk = handle.read()
                offset = handle.tell()
        except OSError:
            await asyncio.sleep(poll_s)
            continue

        if chunk:
            for line in chunk.splitlines():
                if line.strip():
                    result = on_line(line)
                    if asyncio.iscoroutine(result):
                        await result
        await asyncio.sleep(poll_s)


def tail_from_end_default():
    return _should_start_from_end(os.getenv("DECODER_TAIL_FROM_START"))
