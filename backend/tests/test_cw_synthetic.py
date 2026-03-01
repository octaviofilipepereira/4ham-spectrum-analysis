# © 2026 Octávio Filipe Gonçalves
# Test CW decoder with synthetic signal

import numpy as np
import pytest
from app.decoders.cw.decoder import CWDecoder

# Morse code timing (ITU standard)
# At 20 WPM: 1 unit = 60ms
MORSE_CODE = {
    'A': '.-',    'B': '-...',  'C': '-.-.',  'D': '-..',   'E': '.',
    'F': '..-.',  'G': '--.',   'H': '....',  'I': '..',    'J': '.---',
    'K': '-.-',   'L': '.-..',  'M': '--',    'N': '-.',    'O': '---',
    'P': '.--.',  'Q': '--.-',  'R': '.-.',   'S': '...',   'T': '-',
    'U': '..-',   'V': '...-',  'W': '.--',   'X': '-..-',  'Y': '-.--',
    'Z': '--..',  '0': '-----', '1': '.----', '2': '..---', '3': '...--',
    '4': '....-', '5': '.....', '6': '-....', '7': '--...', '8': '---..',
    '9': '----.'
}

def generate_cw_tone(text: str, wpm: int = 20, freq_hz: int = 700, sample_rate: int = 8000):
    """
    Generate synthetic CW audio signal.
    
    Args:
        text: Text to encode in morse
        wpm: Words per minute
        freq_hz: Tone frequency in Hz
        sample_rate: Audio sample rate
        
    Returns:
        Audio samples as numpy array
    """
    # Calculate unit duration (dot length) in seconds
    # PARIS standard: 50 units per word, 60 seconds per minute
    unit_duration = 60.0 / (wpm * 50)
    
    # Duration in samples for each element
    dot_samples = int(unit_duration * sample_rate)
    dash_samples = int(3 * unit_duration * sample_rate)
    element_space_samples = int(unit_duration * sample_rate)
    letter_space_samples = int(3 * unit_duration * sample_rate)
    word_space_samples = int(7 * unit_duration * sample_rate)
    
    # Generate time array for tone
    def make_tone(duration_samples):
        t = np.arange(duration_samples) / sample_rate
        # Add envelope to reduce key clicks
        envelope = np.ones(duration_samples)
        rise_samples = min(int(0.005 * sample_rate), duration_samples // 4)
        envelope[:rise_samples] = np.linspace(0, 1, rise_samples)
        envelope[-rise_samples:] = np.linspace(1, 0, rise_samples)
        return np.sin(2 * np.pi * freq_hz * t) * envelope
    
    def make_silence(duration_samples):
        return np.zeros(duration_samples)
    
    # Convert text to morse and generate audio
    audio_parts = []
    
    for char in text.upper():
        if char == ' ':
            audio_parts.append(make_silence(word_space_samples))
        elif char in MORSE_CODE:
            morse = MORSE_CODE[char]
            for i, symbol in enumerate(morse):
                if symbol == '.':
                    audio_parts.append(make_tone(dot_samples))
                elif symbol == '-':
                    audio_parts.append(make_tone(dash_samples))
                
                # Add element space (except after last element)
                if i < len(morse) - 1:
                    audio_parts.append(make_silence(element_space_samples))
            
            # Add letter space
            audio_parts.append(make_silence(letter_space_samples))
    
    # Concatenate all parts
    audio = np.concatenate(audio_parts) if audio_parts else np.array([])
    
    # Normalize to [-1, 1]
    if len(audio) > 0:
        audio = audio / np.max(np.abs(audio))
    
    return audio.astype(np.float32)


def test_cw_decoder_with_synthetic_signal():
    """Test CW decoder with clean synthetic signal."""
    decoder = CWDecoder(sample_rate=8000)
    
    # Generate clean CW signal with known callsign
    callsign = "CT7BFV"
    wpm = 20
    audio = generate_cw_tone(callsign, wpm=wpm, freq_hz=700, sample_rate=8000)
    
    # Add some padding
    padding = np.zeros(int(0.5 * 8000), dtype=np.float32)
    audio = np.concatenate([padding, audio, padding])
    
    # Decode
    result = decoder.decode(audio)
    
    print(f"\n=== Synthetic CW Test ===")
    print(f"Input: {callsign} @ {wpm} WPM")
    print(f"Decoded text: {result.text}")
    print(f"WPM: {result.wpm:.1f}")

    print(f"Confidence: {result.confidence:.2f}")
    print(f"Callsigns: {result.callsigns}")
    
    # Verify results
    assert callsign in result.text.replace(' ', ''), f"Expected {callsign} in decoded text"
    assert 15 <= result.wpm <= 25, f"WPM should be ~20, got {result.wpm}"
    assert result.confidence > 0.5, f"Confidence should be > 0.5, got {result.confidence}"
    assert callsign in result.callsigns, f"Expected {callsign} in callsigns list"


def test_cw_decoder_with_noise():
    """Test CW decoder with signal + noise."""
    decoder = CWDecoder(sample_rate=8000)
    
    # Generate CW signal
    callsign = "W1AW"
    audio = generate_cw_tone(callsign, wpm=25, freq_hz=700, sample_rate=8000)
    
    # Add white noise (SNR = 10 dB)
    noise = np.random.normal(0, 0.1, len(audio)).astype(np.float32)
    audio_noisy = audio + noise
    
    # Decode
    result = decoder.decode(audio_noisy)
    
    print(f"\n=== Noisy CW Test ===")
    print(f"Input: {callsign} @ 25 WPM + noise")
    print(f"Decoded text: {result.text}")
    print(f"WPM: {result.wpm:.1f}")
    print(f"Confidence: {result.confidence:.2f}")
    print(f"Callsigns: {result.callsigns}")
    
    # With noise, we expect lower confidence but should still decode
    assert len(result.text) > 0, "Should decode something even with noise"


def test_cw_decoder_high_speed():
    """Test CW decoder with 60 WPM signal (high speed contest)."""
    decoder = CWDecoder(sample_rate=8000)
    
    # Generate high-speed CW signal
    callsign = "CT7BFV"
    audio = generate_cw_tone(callsign, wpm=60, freq_hz=700, sample_rate=8000)
    
    # Add padding
    padding = np.zeros(4000, dtype=np.float32)
    audio = np.concatenate([padding, audio, padding])
    
    # Decode
    result = decoder.decode(audio)
    
    print(f"\n=== High-Speed CW Test ===")
    print(f"Input: {callsign} @ 60 WPM")
    print(f"Decoded text: {result.text}")
    print(f"WPM: {result.wpm:.1f}")
    print(f"Confidence: {result.confidence:.2f}")
    print(f"Callsigns: {result.callsigns}")
    
    # Verify results - at high speed, WPM estimation has wider tolerance
    assert callsign in result.text.replace(' ', ''), f"Expected {callsign} in decoded text"
    assert 40 <= result.wpm <= 100, f"WPM should be 40-100, got {result.wpm}"
    assert result.confidence > 0.4, f"Confidence should be > 0.4, got {result.confidence}"


def test_cw_decoder_rejects_pure_noise():
    """Test that decoder rejects pure noise (no CW signal) when validations enabled."""
    # Enable quality validations
    decoder = CWDecoder(
        sample_rate=8000,
        min_snr_db=3.0,  # Reject low SNR
        min_audio_duration=1.0,  # Apply to signals >= 1s
    )
    
    # Generate 2 seconds of pure white noise
    noise = np.random.normal(0, 0.3, 16000).astype(np.float32)
    
    # Decode
    result = decoder.decode(noise)
    
    print(f"\n=== Pure Noise Test ===")
    print(f"Input: Pure white noise")
    print(f"Decoded text: '{result.text}'")
    print(f"WPM: {result.wpm:.1f}")
    print(f"Confidence: {result.confidence:.2f}")
    
    # Should reject noise - expect empty result
    assert result.text == "", f"Should reject noise, got text: '{result.text}'"
    assert result.wpm == 0.0, f"Should have WPM=0, got {result.wpm}"
    assert result.confidence == 0.0, f"Should have confidence=0, got {result.confidence}"


if __name__ == "__main__":
    # Run tests directly
    test_cw_decoder_with_synthetic_signal()
    test_cw_decoder_with_noise()
    test_cw_decoder_high_speed()
    test_cw_decoder_rejects_pure_noise()
