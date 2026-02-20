import re


_CALLSIGN_RE = re.compile(r"\b[A-Z0-9]{1,3}\d{1,4}[A-Z0-9]{1,3}(?:/[A-Z0-9]+)?\b")


def extract_callsign(text):
    if not text:
        return None
    match = _CALLSIGN_RE.search(text.upper())
    if not match:
        return None
    return match.group(0)


def parse_wsjtx_line(line):
    if not line:
        return None
    parts = str(line).strip().split()
    if len(parts) < 5:
        return None
    snr_db = None
    frequency_hz = None
    try:
        snr_db = float(parts[1])
    except ValueError:
        snr_db = None
    try:
        frequency_hz = int(float(parts[3]))
    except ValueError:
        frequency_hz = None
    callsign = extract_callsign(line)
    if not callsign:
        return None
    return {
        "callsign": callsign,
        "snr_db": snr_db,
        "frequency_hz": frequency_hz,
        "raw": str(line).strip(),
        "mode": "FT8"
    }


def parse_aprs_line(line):
    if not line:
        return None
    line = str(line).strip()
    if ">" not in line:
        return None
    callsign = line.split(">", 1)[0].strip().upper()
    if not callsign:
        return None
    return {
        "callsign": callsign,
        "raw": line,
        "mode": "APRS"
    }


def parse_cw_text(text):
    callsign = extract_callsign(text)
    if not callsign:
        return None
    return {
        "callsign": callsign,
        "raw": str(text).strip(),
        "mode": "CW"
    }
