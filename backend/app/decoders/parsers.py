# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 16:27:19 UTC

import re


_CALLSIGN_RE = re.compile(r"\b[A-Z0-9]{1,3}\d{1,4}[A-Z0-9]{1,3}(?:/[A-Z0-9]+)?\b")
_GRID_RE = re.compile(r"^[A-R]{2}\d{2}[A-X]{0,2}$", re.IGNORECASE)
_REPORT_RE = re.compile(r"^(R)?[+-]?\d{1,2}$", re.IGNORECASE)
_SSB_REPORT_RE = re.compile(r"^(?:[1-5][1-9]{1,2}|R?[+-]?\d{1,2})$", re.IGNORECASE)

_PHONETIC_MAP = {
    "ALFA": "A",
    "ALPHA": "A",
    "BRAVO": "B",
    "CHARLIE": "C",
    "DELTA": "D",
    "ECHO": "E",
    "FOXTROT": "F",
    "GOLF": "G",
    "HOTEL": "H",
    "INDIA": "I",
    "JULIET": "J",
    "JULIETT": "J",
    "KILO": "K",
    "LIMA": "L",
    "MIKE": "M",
    "NOVEMBER": "N",
    "OSCAR": "O",
    "PAPA": "P",
    "QUEBEC": "Q",
    "ROMEO": "R",
    "SIERRA": "S",
    "TANGO": "T",
    "UNIFORM": "U",
    "VICTOR": "V",
    "WHISKEY": "W",
    "XRAY": "X",
    "YANKEE": "Y",
    "ZULU": "Z",
}

_NUMBER_WORD_MAP = {
    "ZERO": "0",
    "OH": "0",
    "NIL": "0",
    "CERO": "0",
    "UM": "1",
    "ONE": "1",
    "UNO": "1",
    "DOIS": "2",
    "TWO": "2",
    "DOS": "2",
    "TRES": "3",
    "THREE": "3",
    "CUATRO": "4",
    "QUATRO": "4",
    "FOUR": "4",
    "CINCO": "5",
    "FIVE": "5",
    "SEIS": "6",
    "SIX": "6",
    "SETE": "7",
    "SIETE": "7",
    "SEVEN": "7",
    "OITO": "8",
    "OCHO": "8",
    "EIGHT": "8",
    "NOVE": "9",
    "NUEVE": "9",
    "NINE": "9",
}

_SKIP_WORDS = {
    "CQ",
    "QRZ",
    "DE",
    "DX",
    "THIS",
    "IS",
    "FROM",
    "CHAMANDO",
    "LLAMANDO",
}

_SLASH_WORDS = {
    "SLASH",
    "BARRA",
    "DIAGONAL",
}

_SUFFIX_WORDS = {
    "PORTABLE": "P",
    "MOBILE": "M",
    "MARITIME": "MM",
    "QRP": "QRP",
    "QRPP": "QRPP",
}


def extract_callsign(text):
    if not text:
        return None
    match = _CALLSIGN_RE.search(text.upper())
    if not match:
        return None
    return match.group(0)


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


def parse_ssb_asr_text(text):
    if not text:
        return None

    raw = str(text).strip()
    tokens = re.findall(r"[A-Za-z0-9./+-]+", raw.upper())

    grid = None
    report = None
    frequency_hz = None
    for token in tokens:
        cleaned = token.strip(".,;:()[]{}")
        if not cleaned:
            continue
        if grid is None and _GRID_RE.match(cleaned):
            grid = cleaned.upper()
            continue
        if report is None and _SSB_REPORT_RE.match(cleaned):
            report = cleaned.upper()
            continue
        if frequency_hz is None:
            if re.fullmatch(r"\d{6,10}", cleaned):
                frequency_hz = int(cleaned)
                continue
            mhz_match = re.fullmatch(r"(\d{1,3}\.\d{1,6})(?:MHZ)?", cleaned)
            if mhz_match:
                mhz_value = float(mhz_match.group(1))
                if 1.0 <= mhz_value <= 1000.0:
                    frequency_hz = int(round(mhz_value * 1_000_000))

    direct = extract_callsign(raw)
    if direct:
        return {
            "callsign": direct,
            "raw": raw,
            "mode": "SSB",
            "frequency_hz": frequency_hz,
            "grid": grid,
            "report": report
        }

    if not tokens:
        return None

    stream = []
    for token in tokens:
        if token in _SKIP_WORDS:
            continue
        if token in _SLASH_WORDS:
            stream.append("/")
            continue
        if token in _SUFFIX_WORDS:
            stream.append("/")
            stream.append(_SUFFIX_WORDS[token])
            continue
        mapped = _PHONETIC_MAP.get(token)
        if mapped:
            stream.append(mapped)
            continue
        digit = _NUMBER_WORD_MAP.get(token)
        if digit:
            stream.append(digit)
            continue
        if re.fullmatch(r"[A-Z0-9/]+", token):
            stream.append(token)

    if not stream:
        return None

    candidate = "".join(stream)
    candidate = re.sub(r"/{2,}", "/", candidate)
    callsign = extract_callsign(candidate)
    if not callsign:
        return None

    return {
        "callsign": callsign,
        "raw": raw,
        "mode": "SSB",
        "frequency_hz": frequency_hz,
        "grid": grid,
        "report": report
    }
