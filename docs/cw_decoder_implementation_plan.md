# CW Decoder Implementation Plan
**Date:** 2026-03-01  
**Project:** 4ham-spectrum-analysis  
**Author:** CT7BFV Development Team

---

## 1. Executive Summary

This document outlines the implementation plan for adding **Morse Code (CW) decoding** capabilities to the 4ham-spectrum-analysis system. The proposed solution follows the proven architecture pattern established for FT8/FT4/WSPR modes, leveraging external decoder tools with Python integration.

**Recommendation:** Implement CW decoder using **unixcw library** (moderate complexity, high reliability) with fallback to **pure Python DSP** (high complexity, full control).

---

## 2. Current State Analysis

### 2.1 Existing Infrastructure ✅

**Already Implemented:**
- ✅ CW data ingestion endpoint: `POST /api/decoders/cw`
- ✅ CW parser: `parse_cw_text()` extracts callsigns from decoded text
- ✅ Mode classification heuristic: identifies CW signals (~150-500 Hz bandwidth)
- ✅ Events storage with CW mode support
- ✅ Frontend display with CW filter in events panel
- ✅ Mode switching UI (CW button in quick mode selector)
- ✅ Event schema documentation for CW type

**Missing Component:**
- ❌ **Actual CW decoder**: IQ/Audio → Morse text conversion

### 2.2 System Context

```
┌─────────────────────────────────────────────────────────┐
│  SDR Device (RTL-SDR, HackRF, Airspy)                   │
└───────────────────────┬─────────────────────────────────┘
                        │ IQ samples @ 2.048 MHz
                        ↓
┌─────────────────────────────────────────────────────────┐
│  IQ Processing Pipeline                                  │
│  - Frequency tuning                                      │
│  - Downsampling                                          │
│  - Filtering                                             │
└───────────────────────┬─────────────────────────────────┘
                        │ IQ samples @ target rate
                        ↓
┌─────────────────────────────────────────────────────────┐
│  ⚠️  CW DECODER (TO BE IMPLEMENTED)                     │
│  - Signal detection                                      │
│  - Demodulation (envelope/BFO)                           │
│  - Morse timing analysis                                 │
│  - Character decoding                                    │
└───────────────────────┬─────────────────────────────────┘
                        │ Decoded text
                        ↓
┌─────────────────────────────────────────────────────────┐
│  parse_cw_text() → callsign extraction → DB storage     │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Available Technologies

### 3.1 External Decoder Tools

| Tool | Status | Pros | Cons | Recommendation |
|------|--------|------|------|----------------|
| **unixcw** (`cw`, `cwcp`) | Available in apt (`cw`) | Mature, reliable, active development | Requires installation, CLI-only | ⭐ **Primary choice** |
| **cwdaemon** | Available in apt | Network daemon, parallel/serial port support | Designed for keying, not decoding | ❌ Not suitable |
| **multimon-ng** | Available in apt | Multi-mode decoder (AFSK, DTMF, etc.) | No CW support | ❌ Not suitable |
| **fldigi** | Available in apt | Full GUI SDR suite with CW | Heavy dependency, GUI-focused | ⚠️ Backup option |

### 3.2 Python Libraries

| Library | PyPI | Pros | Cons | Recommendation |
|---------|------|------|------|----------------|
| **PyMorse** | ❓ Needs verification | Pure Python, lightweight | May lack DSP capabilities | ⚠️ Investigate |
| **Custom DSP** | N/A | Full control, no dependencies | High development time | ⚠️ Fallback |

### 3.3 DSP Algorithms (Pure Python Implementation)

**Pipeline:**
1. **Signal Detection:** FFT peak detection (~500-1000 Hz)
2. **Demodulation:** Envelope detector or BFO (beat frequency oscillator)
3. **Binarization:** Adaptive threshold with AGC
4. **Timing Analysis:** Measure dit/dah durations, estimate WPM
5. **Morse Decoding:** Lookup table (dit/dah patterns → characters)
6. **Callsign Extraction:** Regex matching with validation

**Complexity:** High (2-3 days development + testing)  
**Reliability:** Medium (requires extensive tuning)

---

## 4. Proposed Architecture

### 4.1 Recommended Approach: **External Decoder (unixcw)**

```python
# File: backend/app/decoders/cw_external.py

class ExternalCwDecoder:
    """
    CW decoder using unixcw library (cw command).
    Architecture mirrors ExternalFtDecoder for consistency.
    """
    
    def __init__(self, 
                 command_template: str = "cw -f {audio_file} -o {output_file}",
                 window_seconds: float = 10.0,
                 sample_rate: int = 8000,
                 **kwargs):
        self.command_template = command_template
        self.window_seconds = window_seconds
        self.sample_rate = sample_rate
        # ... initialization

    async def decode_loop(self, iq_queue, event_callback):
        """Main decode loop - collect IQ, convert to audio, run decoder"""
        while not self.stop_event.is_set():
            # Collect IQ window (e.g., 10 seconds)
            iq_buffer = await self._collect_iq_window()
            
            # Convert IQ → Audio (mono, 8 kHz)
            audio = self._iq_to_audio(iq_buffer)
            
            # Save to temporary WAV file
            wav_path = self._save_wav(audio)
            
            # Run external decoder
            result = self._run_decoder(wav_path)
            
            # Parse output, extract callsigns
            events = self._parse_decoder_output(result.stdout)
            
            # Emit events via callback
            for event in events:
                await event_callback(event)
            
            await asyncio.sleep(1.0)
```

### 4.2 Alternative: Pure Python DSP

```python
# File: backend/app/decoders/cw_internal.py

class InternalCwDecoder:
    """
    Pure Python CW decoder using NumPy DSP.
    No external dependencies beyond NumPy/SciPy.
    """
    
    def __init__(self, wpm_min=10, wpm_max=40, **kwargs):
        self.wpm_min = wpm_min
        self.wpm_max = wpm_max
        self.morse_table = self._build_morse_table()
    
    def decode_audio(self, audio: np.ndarray, sample_rate: int):
        """
        Decode CW from audio samples.
        Returns list of decoded characters/words.
        """
        # 1. Bandpass filter (300-800 Hz)
        filtered = self._bandpass_filter(audio, 300, 800, sample_rate)
        
        # 2. Envelope detection (Hilbert transform or rectification)
        envelope = self._envelope_detector(filtered)
        
        # 3. Adaptive binarization (AGC + threshold)
        binary_signal = self._binarize(envelope)
        
        # 4. Timing analysis (dit/dah detection)
        timing = self._analyze_timing(binary_signal, sample_rate)
        
        # 5. Morse decoding
        text = self._decode_morse(timing)
        
        return text
```

---

## 5. Implementation Plan

### Phase 1: External Decoder (unixcw) - **Recommended**

**Timeline:** 1-2 days

#### Step 1.1: Install & Test `unixcw`
```bash
sudo apt-get install cw libcw7
cw --help
```

**Deliverable:** Verify `cw` CLI works, understand input/output format

#### Step 1.2: Create `CwExternalDecoder` Class
**File:** `backend/app/decoders/cw_external.py`

**Features:**
- IQ capture window (10s default)
- IQ → Audio conversion (mono 8 kHz)
- WAV file generation
- External command execution (`cw` CLI)
- Output parsing (extract decoded text)
- Event emission

**Testing:** Unit tests with synthetic CW audio

#### Step 1.3: Integration with Scan Loop
**Files:**
- `backend/app/api/decoders.py` - Start/stop endpoints
- `backend/app/dependencies/state.py` - Decoder state management
- `backend/app/main.py` - Lifecycle hooks

**Deliverable:** CW decoder starts automatically when mode = "CW"

#### Step 1.4: Frontend Integration
**File:** `frontend/app.js`

**Changes:**
- Enable CW mode button (already present)
- Real-time event display
- Waterfall markers for CW signals

**Testing:** End-to-end test with real RTL-SDR on 40m CW band

---

### Phase 2: Pure Python DSP (Optional Fallback)

**Timeline:** 2-3 days (if Phase 1 fails)

#### Step 2.1: DSP Pipeline Implementation
**File:** `backend/app/decoders/cw_internal.py`

**Components:**
1. Bandpass filter (SciPy `butter` + `filtfilt`)
2. Envelope detector (Hilbert transform)
3. Adaptive threshold (histogram-based)
4. Timing analysis (measure pulse widths)
5. Morse decoder (lookup table)

#### Step 2.2: WPM Estimation
**Algorithm:** Measure average dit duration, calculate WPM = 1200 / dit_ms

#### Step 2.3: Callsign Extraction
**Reuse:** Existing `parse_cw_text()` function

---

## 6. Technical Specifications

### 6.1 Audio Requirements

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Sample Rate | 8000 Hz | Sufficient for CW (0-1000 Hz bandwidth) |
| Bit Depth | 16-bit PCM | Standard WAV format |
| Channels | Mono | CW is single-tone signal |
| Window Size | 10 seconds | Balance between latency and decode accuracy |

### 6.2 CW Signal Characteristics

| Property | Range | Notes |
|----------|-------|-------|
| Frequency | 300-1000 Hz (audio) | After demodulation or filter |
| Bandwidth | 150-500 Hz | Depends on keying speed |
| WPM Range | 10-40 WPM | 5-25 WPM typical for amateur radio |
| Dit Duration | 30-120 ms | Inversely proportional to WPM |
| Dah Duration | 3× dit | Standard Morse timing |

### 6.3 Event Schema (Already Defined)

```json
{
  "type": "callsign",
  "timestamp": "2026-03-01T10:30:00Z",
  "band": "40m",
  "frequency_hz": 7025000,
  "mode": "CW",
  "callsign": "CT7BFV",
  "raw": "CQ CQ DE CT7BFV CT7BFV K",
  "confidence": 0.72,
  "wpm": 18,
  "source": "cw_external",
  "device": "rtlsdr"
}
```

---

## 7. Risk Assessment

### 7.1 Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| `unixcw` not suitable for automation | Medium | High | Test early, fallback to Python DSP |
| Low SNR signals not decoded | High | Medium | Implement AGC, adaptive threshold |
| High CPU usage | Low | Medium | Optimize window size, throttle |
| False positives (noise decoded as CW) | Medium | Low | Require minimum signal strength |

### 7.2 Integration Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Conflicts with FT8/WSPR decoders | Low | High | Use separate IQ queues per mode |
| Memory leaks (large IQ buffers) | Medium | Medium | Reuse existing stride-based collection |
| Database performance (high event rate) | Low | Low | Batch insert, existing optimizations |

---

## 8. Testing Strategy

### 8.1 Unit Tests
**File:** `backend/tests/test_cw_decoder.py`

**Scenarios:**
- ✅ Synthetic CW audio → correct decoding
- ✅ Noise tolerance test (SNR 0-20 dB)
- ✅ WPM range test (10-40 WPM)
- ✅ Callsign extraction from raw text

### 8.2 Integration Tests
- ✅ Start/stop CW decoder via API
- ✅ Mode switching (FT8 ↔ CW ↔ WSPR)
- ✅ Event storage and retrieval
- ✅ Frontend display

### 8.3 Real-World Tests
- ✅ 40m CW band (7.000-7.040 MHz)
- ✅ 20m CW band (14.000-14.070 MHz)
- ✅ Low power QRP signals
- ✅ High-speed CW (>25 WPM)

---

## 9. Dependencies

### 9.1 System Packages (Phase 1)
```bash
sudo apt-get install cw libcw7
```

### 9.2 Python Packages (No changes)
- `numpy` (already installed)
- `scipy` (already installed)

### 9.3 Optional (Phase 2)
- None (pure Python/NumPy/SciPy)

---

## 10. Estimated Effort

| Phase | Tasks | Time | Complexity |
|-------|-------|------|------------|
| **Phase 1.1** | Install & test unixcw | 2 hours | Low |
| **Phase 1.2** | Implement `CwExternalDecoder` | 6-8 hours | Medium |
| **Phase 1.3** | Integration (API, state, scan) | 4 hours | Low |
| **Phase 1.4** | Frontend updates | 2 hours | Low |
| **Testing** | Unit + integration + real | 4 hours | Medium |
| **Total (Phase 1)** | | **16-20 hours** | **1-2 days** |

**Phase 2 (if needed):** +16-24 hours (2-3 days)

---

## 11. Success Criteria

### 11.1 Functional Requirements
- ✅ CW mode can be selected and started via UI
- ✅ CW signals are detected and decoded automatically
- ✅ Callsigns are extracted and stored in database
- ✅ Events appear in frontend Events panel
- ✅ Propagation map shows CW contacts
- ✅ WPM estimation displayed (optional bonus)

### 11.2 Performance Requirements
- ✅ Decode latency < 15 seconds (from signal to event)
- ✅ CPU usage < 20% (single core) on Raspberry Pi 4
- ✅ Memory usage < 250 MB (consistent with WSPR fix)
- ✅ Decode accuracy > 70% on SNR > 6 dB signals

### 11.3 Reliability Requirements
- ✅ No crashes or memory leaks in 24h operation
- ✅ Graceful handling of weak signals (no false positives)
- ✅ Mode switching does not require restart

---

## 12. Alternatives Considered

### 12.1 ❌ Multimon-ng
**Reason:** Does not support CW/Morse decoding (only AFSK, DTMF, POCSAG)

### 12.2 ⚠️ Fldigi Integration
**Pros:** Mature, full-featured SDR suite with excellent CW decoder  
**Cons:** Heavy GUI application, complex integration, overkill for our use case  
**Decision:** Reserve as last resort if unixcw and Python DSP both fail

### 12.3 ⚠️ Commercial APIs (E.g., Cloud CW Decoders)
**Pros:** Offload processing complexity  
**Cons:** Privacy concerns, latency, cost, internet dependency  
**Decision:** Not suitable for amateur radio monitoring system

---

## 13. Next Steps (Awaiting Approval)

### Upon Approval:
1. **Immediate:** Install `unixcw` and test CLI behavior
2. **Day 1 Morning:** Implement `CwExternalDecoder` class
3. **Day 1 Afternoon:** Integration with scan loop and API
4. **Day 2 Morning:** Frontend updates and testing
5. **Day 2 Afternoon:** Real-world validation on 40m band
6. **Deliverable:** Working CW decoder ready for production

### Fallback Plan:
- If Phase 1 encounters blockers, pivot to Phase 2 (Python DSP)
- Budget +2 days for pure DSP implementation

---

## 14. Recommendation

**Primary Recommendation:** ⭐ **Proceed with Phase 1 (unixcw external decoder)**

**Rationale:**
- ✅ Follows proven architecture (ExternalFtDecoder pattern)
- ✅ Minimal development time (1-2 days vs 2-3 days for pure Python)
- ✅ Leverages mature, community-tested decoder
- ✅ Lower risk than custom DSP implementation
- ✅ Consistent with project philosophy (external tools for modes)

**Approval Needed:**
- [ ] Approve Phase 1 implementation (unixcw)
- [ ] Approve system package installation (`cw`, `libcw7`)
- [ ] Approve 1-2 day development timeline
- [ ] Authorize real-world testing on live bands

---

## 15. Questions for Review

1. **Architecture:** Do you agree with following the `ExternalFtDecoder` pattern?
2. **Dependencies:** Is installing `unixcw` (apt package) acceptable?
3. **Timeline:** Is 1-2 days reasonable for initial implementation?
4. **Fallback:** Should we budget additional time for Phase 2 (Python DSP)?
5. **Testing:** Do you have preferred CW bands/frequencies for validation?

---

**Document Status:** ✅ Ready for Review  
**Next Action:** Awaiting approval to proceed with implementation  
**Contact:** CT7BFV Development Team
