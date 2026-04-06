# Propagation Scoring Reference — Validation & Design

> **Document version**: 1.1 — 2026-04-06  
> **Author**: CT7BFV / 4ham-spectrum-analysis project  
> **Purpose**: Reference document for the 3-formula propagation scoring system, validated against industry standards and scientific research.

---

## 1. Context & Problem Statement

The previous propagation scoring formula used a single calculation for all modes:

```
score = snr_norm × confidence × base_weight × recency_weight
```

Where `snr_norm = (SNR + 20) / 40` and `base_weight = 1.0` (callsign) or `0.55` (occupancy).

### Identified Flaws

1. **No decode_rate metric** — Many FT8 signal detections with few decoded callsigns incorrectly produced a "Good" propagation score. Example: 100 FT8 events with only 3 callsigns decoded at -15 dB SNR scored ~55 (Good), when real propagation was Poor.
2. **Occupancy weight too generous** — `base_weight = 0.55` for occupancy events inflated scores when the band had energy but signals were too weak to decode.
3. **SNR normalization too generic** — `(SNR + 20) / 40` did not account for mode-specific decode thresholds. An FT8 signal at -18 dB (barely decodable) was treated the same as a CW signal at -18 dB (which would be quite weak).
4. **No mode differentiation** — CW and SSB use sequential narrowband scanning with short dwell times. Unlike FT8/FT4/WSPR (parallel wideband decode), not capturing a callsign in CW/SSB doesn't mean weak signal — the operator may not have been transmitting their callsign during the short listening window.

---

## 2. Industry Analysis — How Existing Tools Assess Propagation

### 2.1 Key Finding

**No existing tool calculates a single "propagation score" from real-time measurements as 4HAM-Spectrum-Analysis.** Every major tool provides raw data and lets users/researchers interpret:

| Tool | Data Collected | Propagation Assessment Method |
|---|---|---|
| **PSK Reporter** | Callsign, frequency, SNR, mode, time | Spot map: geographic spread + spot count + SNR |
| **WSPRnet / wspr.live** | Callsign, grid, power, SNR, distance, drift | Spot existence = path open; SNR + distance = quality |
| **WSJT-X** | Decoded callsigns with SNR (dB/2500 Hz) | SNR report per QSO; no aggregate score |
| **VOACAP** | Predicted path loss, MUF, reliability | **Reliability %** (0-100%) based on ionospheric model |
| **HamSCI** (Frissell et al. 2014) | PSK Reporter spots for ionospheric research | Spot density + geographic distribution + temporal patterns |
| **GridTracker** | PSK Reporter data visualization | Visual spot density on map; no score |
| **Reverse Beacon Network (RBN)** | CW/RTTY spots with SNR | Spot existence + SNR; completely separate from digital modes |

**VOACAP's "reliability percentage"** is the closest existing concept to our propagation score — it produces a 0-100% value per band. However, it is a forward-looking **prediction** based on solar indices, not a real-time **measurement** from received signals.

### 2.2 PSK Reporter — Key Design Principle

From the PSK Reporter developer specification (Philip Gladstone, N1DQ):

> *"Each callsign should be reported no more than once per five minute period. Ideally, a callsign should be reported only once per hour if it has not 'changed'."*

This explicitly separates "raw signal detections" from "successfully decoded callsigns" — the exact distinction our `decode_rate` metric captures.

### 2.3 WSPRnet Philosophy

Every spot in the WSPRnet database IS a successful decode. If energy is detected but cannot be decoded, no spot is created. The ratio of "energy detected" vs "spots created" is precisely our `decode_rate` concept.

### 2.4 HamSCI Scientific Research

The HamSCI project (Frissell et al., "Ionospheric Sounding Using Real-Time Amateur Radio Reporting Networks", Space Weather, 2014) uses PSK Reporter data for ionospheric research. Their methodology considers:

- Spot density per band/time window
- Geographic distribution of reception paths
- Temporal patterns of propagation changes
- Unique callsigns as independent data points

---

## 3. Confirmed Decode Thresholds (WSJT-X v2.6 Documentation)

Source: WSJT-X User Guide, Protocol Specifications §17.2.10 (Table 7)

| Mode | FEC Code | S/N Threshold (dB/2500 Hz) | Bandwidth (Hz) | Duration (s) |
|---|---|---|---|---|
| **FT8** | LDPC (174,91) | **-20** (confirmed: -21 in earlier versions) | 50.0 | 12.6 |
| **FT4** | LDPC (174,91) | **-17.5** | 83.3 | 5.04 |
| **WSPR** | K=32, r=1/2 | **-31** | 5.9 | 110.6 |
| **FST4W-120** | LDPC (240,74) | **-32.8** | 5.9 | 109.3 |
| **JT65A** | RS (63,12) | **-25** | 177.6 | 46.8 |
| **JT9A** | K=32, r=1/2 | **-26** | 15.6 | 49.0 |
| **Q65-15A** | QRA (63,13) | **-22.2** | 433 | 12.8 |

Additional practical thresholds (not from WSJT-X, estimated from operational experience):
- **CW**: ~-15 dB (practical decode by ear/software)
- **SSB**: ~+3 dB (practical intelligibility threshold)

WSJT-X User Guide §7.1 also states:
> *"Signals become visible on the waterfall around S/N = -26 dB and audible (to someone with very good hearing) around -15 dB. Thresholds for decodability are around -20 dB for FT8, -23 dB for JT4, -25 dB for JT65, and -27 dB for JT9."*

---

## 4. Validated 3-Formula Approach

### 4.1 Category 1: FT8 / FT4 / WSPR (Parallel Wideband Decode)

These modes decode the **entire passband simultaneously**. Every signal in the 2500 Hz bandwidth is processed in parallel. A successful decode produces a callsign + SNR report. If energy is detected but the signal is too weak to decode, it appears as an occupancy event without a callsign.

**Therefore**: `decode_rate` (ratio of callsigns to total events) is a direct measure of signal quality and propagation.

| Component | Weight | Rationale |
|---|---|---|
| `decode_rate` | **40%** | Primary metric. Supported by PSK Reporter and WSPRnet philosophy |
| `median_snr` | **35%** | Universal metric across all tools. Normalized per mode threshold |
| `unique_callsigns` | **15%** | Supported by HamSCI methodology |
| `recency` | **10%** | Real-time dashboard relevance |

**SNR Normalization** (mode-specific):

| Mode | Floor (decode threshold) | Ceiling | Range |
|---|---|---|---|
| FT8 | -20 dB | +10 dB | 30 dB |
| FT4 | -17.5 dB | +10 dB | 27.5 dB |
| WSPR | -31 dB | +0 dB | 31 dB |

Formula: `snr_norm = clamp((SNR - floor) / range, 0, 1)`

### 4.2 Category 2: CW (Sequential Narrowband Scan)

CW uses sequential narrowband scanning with short dwell times. The scanner listens to each frequency segment briefly. **Not capturing a callsign does NOT indicate weak propagation** — the operator may simply not have been transmitting their callsign during the short listening window.

CW callsign decoding is inherently less reliable than FT8/FT4/WSPR due to:
- Sequential (not parallel) scanning
- Short dwell time per frequency
- Callsign only transmitted during specific parts of CQ calls
- Variable operator timing

| Component | Weight | Rationale |
|---|---|---|
| `traffic_volume` | **30%** | CW_TRAFFIC detection = band is active |
| `snr_quality` | **30%** | SNR remains universal quality metric |
| `signal_strength` | **15%** | RF signal level as propagation indicator |
| `callsign_bonus` | **15%** | Bonus when callsign IS captured (not penalty when absent) |
| `recency` | **10%** | Real-time dashboard relevance |

**SNR Normalization**: Floor = -15 dB, Ceiling = +20 dB, Range = 35 dB

### 4.3 Category 3: SSB (Sequential Narrowband Scan + Voice)

SSB shares CW's sequential scanning limitation. Additionally, SSB has no structured digital message — propagation assessment relies on voice detection quality, SNR, and signal strength.

**No external tool provides automated SSB propagation scoring as 4HAM-Spectrum-Analysis.**

| Component | Weight | Rationale |
|---|---|---|
| `traffic_volume` | **20%** | SSB_TRAFFIC / VOICE_DETECTION = band is active |
| `snr_quality` | **25%** | SNR quality metric |
| `signal_strength` | **15%** | RF signal level as propagation indicator |
| `voice_quality` | **20%** | Quality of voice detection (clarity) |
| `transcript` | **10%** | Successful speech-to-text = intelligible signal |
| `callsign_bonus` | **5%** | Bonus when callsign IS captured |
| `recency` | **5%** | Real-time dashboard relevance |

**SNR Normalization**: Floor = +3 dB, Ceiling = +30 dB, Range = 27 dB

---

## 5. Score Thresholds

| Score Range | State | Description |
|---|---|---|
| ≥ 70 | **Excellent** | Strong signals, high decode rates, multiple callsigns |
| ≥ 50 | **Good** | Reliable decodes, decent SNR |
| ≥ 30 | **Fair** | Some activity, marginal signals |
| < 30 | **Poor** | Minimal or no useful propagation |

---

## 6. Implementation Locations

### 6.1 Backend (canonical implementation)

| File | Function | Purpose |
|---|---|---|
| `backend/app/dependencies/helpers.py` | `build_propagation_summary()` | Main entry point — live dashboard propagation scoring |
| `backend/app/dependencies/helpers.py` | `_compute_band_propagation()` | Core per-band scoring engine (called by above) |
| `backend/app/dependencies/helpers.py` | `_normalise_snr()` | Mode-specific SNR normalization |
| `backend/app/dependencies/helpers.py` | `_mode_category()` | Mode → category classifier (digital / cw / ssb) |
| `backend/app/dependencies/helpers.py` | `_score_to_state()` | Score → label mapping (Excellent / Good / Fair / Poor) |
| `backend/app/api/analytics.py` | `_compute_category_score()` | Category-level scoring for academic analytics |
| `backend/app/api/analytics.py` | `_propagation_state()` | Score → label mapping (mirrors `_score_to_state`) |
| `backend/app/api/events.py` | `propagation_summary()` | REST endpoint `/api/propagation/summary` |

### 6.2 Frontend

| File | Function | Purpose |
|---|---|---|
| `frontend/app.js` | `renderPropagationSummary()` | Display rendering of backend-computed propagation data |
| `frontend/app.js` | `requestPropagationSummary()` | Fetches propagation data from API |
| `frontend/4ham_academic_analytics.html` | `computePropagationAnalytics()` | Client-side fallback propagation scoring |

> **Note**: The frontend `computePropagationAnalytics()` is a **simplified approximation** of the backend formulas, used only as a client-side fallback when the server endpoint is unavailable. It applies the correct weights but uses simplified inputs (e.g., log-normalized event counts instead of actual decode rates, hardcoded recency/quality values). The **backend implementation is canonical**.

---

## 7. Sources & References

1. **PSK Reporter Developer Specification** — Philip Gladstone, N1DQ  
   https://www.pskreporter.info/pskdev.html

2. **WSJT-X User Guide v2.6** — Joseph H. Taylor Jr., K1JT  
   https://wsjt.sourceforge.io/wsjtx-doc/wsjtx-main-2.6.1.html  
   Protocol Specifications §17.2.10 (decode threshold table)

3. **WSPR Protocol** — Wikipedia / Joe Taylor, K1JT  
   Minimum S/N for reception: -31 dB (WSPR), -28 dB (original spec)  
   https://en.wikipedia.org/wiki/WSPR_(amateur_radio_software)

4. **HamSCI** — Frissell, N. A. et al. (2014)  
   "Ionospheric Sounding Using Real-Time Amateur Radio Reporting Networks"  
   Space Weather, 12(12), 651-656. DOI: 10.1002/2014SW001132

5. **VOACAP** — Voice of America Coverage Analysis Program  
   https://www.voacap.com/

6. **PSK Reporter** — Wikipedia  
   https://en.wikipedia.org/wiki/PSK_Reporter  
   20+ billion reception reports as of 2021

7. **wspr.live** — WSPR spot database with ClickHouse backend  
   https://wspr.live/

8. **FT4 and FT8 Communication Protocols** — QEX publication  
   https://wsjt.sourceforge.io/FT4_FT8_QEX.pdf
