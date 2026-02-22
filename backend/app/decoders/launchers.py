# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

import asyncio
import os
import shlex


def env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return bool(default)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def resolve_command(env_name, default_command):
    raw = os.getenv(env_name, default_command) or ""
    parts = shlex.split(raw)
    return [part for part in parts if part]


async def start_process(command):
    if not command:
        return None
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    return process


async def stop_process(process, timeout_s=3.0):
    if process is None:
        return
    if process.returncode is not None:
        return

    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout_s)
        return
    except asyncio.TimeoutError:
        pass

    process.kill()
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout_s)
    except asyncio.TimeoutError:
        return
