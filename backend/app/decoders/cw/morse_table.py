# © 2026 CT7BFV — Standalone CW Decoder
# Morse code lookup tables (dots='.', dashes='-')

# Standard ITU Morse alphabet
MORSE_TO_CHAR: dict[str, str] = {
    # Letters
    ".-":    "A",
    "-...":  "B",
    "-.-.":  "C",
    "-..":   "D",
    ".":     "E",
    "..-.":  "F",
    "--.":   "G",
    "....":  "H",
    "..":    "I",
    ".---":  "J",
    "-.-":   "K",
    ".-..":  "L",
    "--":    "M",
    "-.":    "N",
    "---":   "O",
    ".--.":  "P",
    "--.-":  "Q",
    ".-.":   "R",
    "...":   "S",
    "-":     "T",
    "..-":   "U",
    "...-":  "V",
    ".--":   "W",
    "-..-":  "X",
    "-.--":  "Y",
    "--..":  "Z",
    # Digits
    ".----": "1",
    "..---": "2",
    "...--": "3",
    "....-": "4",
    ".....": "5",
    "-....": "6",
    "--...": "7",
    "---..": "8",
    "----.": "9",
    "-----": "0",
    # Punctuation
    ".-.-.-": ".",
    "--..--": ",",
    "..--..": "?",
    ".----.": "'",
    "-.-.--": "!",
    "-..-.":  "/",
    "-.--.":  "(",
    "-.--.-": ")",
    ".-...":  "&",
    "---...": ":",
    "-.-.-.": ";",
    "-...-":  "=",
    ".-.-.":  "+",
    "-....-": "-",
    "..--.-": "_",
    ".-..-.": '"',
    "...-..-": "$",
    ".--.-.": "@",
    # Prosigns (note: -...- = BT = same code as "="; -.--.= KN = same code as "(")
    "...---...": "SOS",
    ".-.-":   "AA",   # new line
    "-.-.-":  "CT",   # start
    "...-.-": "SK",   # end of contact
    "...-.": "SN",   # understood
}

# Reverse: char → morse (for encoding / test generation)
CHAR_TO_MORSE: dict[str, str] = {v: k for k, v in MORSE_TO_CHAR.items() if len(v) == 1}
# Override single-char entries only (skip prosigns)
CHAR_TO_MORSE.update({
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..",
    "E": ".", "F": "..-.", "G": "--.", "H": "....",
    "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.",
    "Q": "--.-", "R": ".-.", "S": "...", "T": "-",
    "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
    "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-...." , "7": "--...", "8": "---..",
    "9": "----.", "0": "-----",
    "/": "-..-.", "?": "..--..", ".": ".-.-.-", ",": "--..--",
})


def decode_symbol(symbol: str) -> str:
    """Decode a single Morse symbol (e.g. '.-') to a character.
    Returns '?' for unknown symbols."""
    return MORSE_TO_CHAR.get(symbol, "?")


def encode_text(text: str) -> list[str]:
    """Encode plain text to list of Morse symbols (one per character).
    Spaces in text become None entries (word gap marker)."""
    result: list[str | None] = []
    for ch in text.upper():
        if ch == " ":
            result.append(None)          # word gap
        elif ch in CHAR_TO_MORSE:
            result.append(CHAR_TO_MORSE[ch])
    return result
