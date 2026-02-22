# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 16:27:19 UTC

import numpy as np


def encode_delta_int8(fft_db, step_db=0.5):
    if not fft_db:
        return {
            "encoding": "delta_int8",
            "fft_ref_db": 0.0,
            "fft_step_db": float(step_db),
            "fft_delta": [],
        }

    values = np.array(fft_db, dtype=np.float32)
    ref = float(np.min(values))
    step = float(step_db) if step_db and step_db > 0 else 0.5
    quantized = np.round((values - ref) / step)
    quantized = np.clip(quantized, 0, 255) - 128
    deltas = quantized.astype(np.int8).tolist()
    return {
        "encoding": "delta_int8",
        "fft_ref_db": ref,
        "fft_step_db": step,
        "fft_delta": deltas,
    }


def decode_delta_int8(fft_ref_db, fft_step_db, fft_delta):
    if not fft_delta:
        return []
    ref = float(fft_ref_db)
    step = float(fft_step_db)
    deltas = np.array(fft_delta, dtype=np.int16)
    values = ref + ((deltas + 128) * step)
    return values.astype(np.float32).tolist()
