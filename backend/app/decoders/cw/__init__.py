# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

# © 2026 CT7BFV — CW Decoder package
"""
Standalone CW (Morse code) decoder.

No integration with the 4ham backend — pure signal processing.
"""

from .decoder import CWDecoder, DecodeResult
from .morse_table import MORSE_TO_CHAR, CHAR_TO_MORSE, encode_text, decode_symbol

__all__ = [
    "CWDecoder",
    "DecodeResult",
    "MORSE_TO_CHAR",
    "CHAR_TO_MORSE",
    "encode_text",
    "decode_symbol",
]
