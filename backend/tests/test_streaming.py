import numpy as np

from app.streaming import decode_delta_int8, encode_delta_int8


def test_encode_delta_int8_empty():
    payload = encode_delta_int8([])
    assert payload["encoding"] == "delta_int8"
    assert payload["fft_delta"] == []


def test_encode_decode_delta_int8_roundtrip_shape_and_error_bound():
    source = np.linspace(-120.0, -15.0, num=128, dtype=np.float32).tolist()
    encoded = encode_delta_int8(source, step_db=0.5)
    restored = decode_delta_int8(
        encoded["fft_ref_db"],
        encoded["fft_step_db"],
        encoded["fft_delta"],
    )

    assert len(restored) == len(source)
    max_err = max(abs(a - b) for a, b in zip(source, restored))
    assert max_err <= 0.51
