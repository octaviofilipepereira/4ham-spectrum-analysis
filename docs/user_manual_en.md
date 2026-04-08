# 4HAM Spectrum Analysis - User Manual

## Table of Contents

1. [SSB Events — Voice Signature](#ssb-events--voice-signature)
2. [Understanding the Metrics](#understanding-the-metrics)
   - [SNR vs Propagation Score](#snr-vs-propagation-score)
3. [Academic Analytics Dashboard](#academic-analytics-dashboard)
4. [Scan Rotation](#scan-rotation)
5. [Propagation Map — Time Window Selector](#propagation-map--time-window-selector)
6. [Initial Setup](#initial-setup)
7. [User Interface](#user-interface)
8. [Spectrogram Interpretation](#spectrogram-interpretation)
9. [Data Export](#data-export)
10. [Troubleshooting](#troubleshooting)

---

## SSB Events — Voice Signature

### What is a Voice Signature event?

Starting with **v0.8.0**, the system detects and transcribes SSB transmissions in real time using voice demodulation and ASR (Automatic Speech Recognition — Whisper).

There are three types of result for SSB signals:

| Label | Meaning |
|-------|---------|
| **Voice Confirmed** | SSB detected, no transcription available — only confirmation of voice activity |
| **Voice Transcript** | SSB detected with Whisper transcription, but no callsign resolved — the **TXT** button shows the transcribed text |
| **Callsign** | SSB detected **and** callsign successfully resolved by ASR |

### SSB detection pipeline

1. The scanner detects band occupancy with typical SSB bandwidth (2.4–3 kHz).
2. The DSP block demodulates USB or LSB according to the band and frequency segment.
3. VAD (Voice Activity Detection) segments the transmission into voice chunks.
4. Whisper transcribes the audio — all tokens matching a valid callsign (IARU regex) are extracted.
5. If a callsign is found → event with the resolved callsign.
6. If there is a transcription but no callsign → label **Voice Transcript** with a **TXT** button showing the text.
7. If only voice is detected without transcription → label **Voice Confirmed**.

### Occupancy flood protection

During long SSB transmissions, the system applies several mechanisms to prevent the events panel and waterfall from becoming saturated:

- **Per 2 kHz segment debounce** — suppresses repeated occupancy events for the same segment for **30 seconds** (v0.8.4; was 8 s).
- **SNR gate** — signals below **8 dB SNR** are rejected and do not generate events.
- **Conditional SSB_VOICE markers** — "VOICE DETECTED" markers on the waterfall are only created when Whisper ASR confirms active voice; occupancy-only detections do not generate markers.

### ASR configuration in the Admin panel

1. Open the web interface and log in.
2. Go to **Admin** → **Settings**.
3. Enable **SSB ASR** and select the Whisper model (`tiny` recommended, `base` for higher accuracy).
4. The model is downloaded automatically on first use (~75 MB for `tiny`).

> **Note:** Whisper requires `openai-whisper` installed (included if selected during `./install.sh`, or manually installable: `pip install openai-whisper`).

---

## Understanding the Metrics

### SNR vs Propagation Score

The system presents two important metrics that may seem contradictory at first glance:

#### 📡 SNR (Signal-to-Noise Ratio)

**What it is**: An **instantaneous** measurement of an **individual signal**.

**Calculation**:
```
SNR = signal_level_dB - noise_floor_dB
```

**How to interpret**:
- **< 8 dB**: Signal rejected (too weak to decode)
- **8-15 dB**: Weak but decodable signal
- **15-25 dB**: Strong signal
- **> 25 dB**: Very strong signal

**Where it appears**: The SNR value shown next to each band represents the **peak maximum (max_snr_db)** recorded on that band in the last 60 minutes.

---

#### 🌍 Propagation Score

**What it is**: An **aggregated** assessment of propagation conditions based on **multiple recent events**.

**How it is calculated (v0.9.0 — 3 formulas by mode category)**:

Since v0.9.0, the system uses **three distinct formulas** tailored to the characteristics of each mode type. Each formula combines weighted metrics, normalised between 0 and 1, and produces a final score between 0 and 100.

##### Category 1 — Digital (FT8 / FT4 / WSPR / JT65 / JT9 / FST4 / FST4W / Q65)

These modes decode the entire passband in parallel. The decode rate (ratio of callsigns to total events) is the primary metric.

| Component | Weight | Description |
|---|---|---|
| `decode_rate` | **40%** | Ratio of events with callsign vs. total detections |
| `median_snr` | **35%** | Median SNR normalised by mode-specific threshold |
| `unique_callsigns` | **15%** | Number of unique callsigns (diversity) |
| `recency` | **10%** | More recent events carry more weight |

**SNR Normalisation (mode-specific)**:

| Mode | Floor (decode threshold) | Ceiling | Range |
|---|---|---|---|
| FT8 | −20 dB | +10 dB | 30 dB |
| FT4 | −17.5 dB | +10 dB | 27.5 dB |
| WSPR | −31 dB | 0 dB | 31 dB |

```
snr_norm = clamp((SNR - floor) / range, 0, 1)
```

##### Category 2 — CW (Morse)

CW uses sequential narrowband scanning with short dwell times. Not capturing a callsign **does not indicate weak propagation** — the operator may simply not have been transmitting their callsign during the short listening window.

| Component | Weight | Description |
|---|---|---|
| `traffic_volume` | **30%** | CW_TRAFFIC detected = band is active |
| `snr_quality` | **30%** | Normalised SNR (floor −15 dB, ceiling +20 dB) |
| `signal_strength` | **15%** | RF signal level as propagation indicator |
| `callsign_bonus` | **15%** | Bonus when callsign IS captured (not penalty when absent) |
| `recency` | **10%** | More recent events carry more weight |

##### Category 3 — SSB (Voice)

SSB shares CW's sequential scanning limitation. Assessment relies on voice detection quality, SNR, and signal strength.

| Component | Weight | Description |
|---|---|---|
| `traffic_volume` | **20%** | SSB_TRAFFIC / VOICE_DETECTION = band is active |
| `snr_quality` | **25%** | Normalised SNR (floor +3 dB, ceiling +30 dB) |
| `signal_strength` | **15%** | RF signal level |
| `voice_quality` | **20%** | Quality of voice detection (clarity) |
| `transcript` | **10%** | Successful speech-to-text = intelligible signal |
| `callsign_bonus` | **5%** | Bonus when callsign IS captured |
| `recency` | **5%** | More recent events carry more weight |

**Classification (common to all categories)**:
- **≥ 70**: Excellent 🟢
- **≥ 50**: Good 🟡
- **≥ 30**: Fair 🟠
- **< 30**: Poor 🔴

> Full reference with scientific validation and sources: [docs/propagation_scoring_reference.md](propagation_scoring_reference.md)

---

#### 🤔 Why can a high SNR have a low Score?

It is common to observe seemingly contradictory situations such as:

| Band | max_snr_db | Score | Status |
|------|-----------|-------|--------|
| **20m** | 32 dB ⚡ | 30.8/100 | Fair |
| **40m** | 28.1 dB | 60.7/100 | Good |

**Explanation**:

The **displayed SNR is the maximum value** recorded on the band, but the **Propagation Score represents the weighted average of ALL events** on that band.

**Typical scenario - 20m (SNR 32 dB → Score 30.8/100)**:
- Had **one peak** of 32 dB 55 minutes ago
- But only **3-4 events** in total
- Events are **old** (low time-based weight)
- Most have **low SNR** (9-15 dB)
- Result: **inconsistent band** → Score Fair

**Typical scenario - 40m (SNR 28.1 dB → Score 60.7/100)**:
- **Many events** (25+ total)
- Events are **recent** (high time-based weight)
- SNR **consistently high** (18-28 dB)
- Most are **callsigns** (weight 1.0)
- **High confidence** in decodings
- Result: **stable and active band** → Score Good

---

#### 💡 Restaurant Analogy

**Restaurant A (20m)**: 
- Served **one excellent dish** yesterday (32 dB)
- But today only 2-3 mediocre dishes
- **Average rating**: 3/5 ⭐⭐⭐ (Fair)

**Restaurant B (40m)**:
- Every dish today was **very good** (25-28 dB)
- Served 25+ consistent dishes
- **Average rating**: 4/5 ⭐⭐⭐⭐ (Good)

The "best dish" was at Restaurant A, but the **overall experience** is better at Restaurant B!

---

#### 🎯 Conclusion

- **SNR** = quality of **one specific signal** (the best recorded)
- **Propagation Score** = **overall band quality** over the last 60 minutes

**A single high SNR does not guarantee an "Excellent" score** because the system evaluates:
- ✅ **Consistency** of SNR over time
- ✅ **Number** of events
- ✅ **Age** of events (more recent events carry more weight)
- ✅ **Type** of events (callsigns vs occupancy)
- ✅ **Confidence** in decodings

The Propagation Score provides a **holistic view of propagation quality** on each band, not just the peak instantaneous value.

---

---

## Initial Setup

### Prerequisites
- SDR: RTL-SDR (recommended), HackRF, Airspy or other SoapySDR-compatible hardware
- Operating system: Linux Ubuntu 20.04+ / Debian 11+ / Linux Mint 20+ / Raspberry Pi OS 11+ (64-bit)
- Python 3.10+
- NTP time synchronisation (mandatory for FT8/FT4)

### Quick installation (graphical installer)
Starting with v0.7.1, the project includes an interactive TUI installer:

```bash
git clone https://github.com/octaviofilipepereira/4ham-spectrum-analysis.git
cd 4ham-spectrum-analysis
chmod +x install.sh && ./install.sh
```

The installer configures: system packages, RTL-SDR Blog v4 driver (optional), Python virtual environment, administrator account (bcrypt password in SQLite) and systemd service.

### Starting the server
```bash
source .venv/bin/activate
python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

Or via the development script:
```bash
./scripts/run_dev.sh start
```

Open the interface in the browser: `http://localhost:8000/`

---

## Academic Analytics Dashboard

### Purpose

Academic Analytics is an aggregated analysis tool designed to answer concrete questions about amateur radio activity:

- **Which bands are most active** right now, today, or over the last 30 days?
- **At what UTC hours does propagation peak** on each band? (essential for planning DX operations)
- **What is the real quality of propagation** — not just a single SNR peak, but consistency over time?
- **Which stations are most active** in the analysed period?
- **How has propagation evolved** over hours or days?

Unlike the main dashboard (which shows real-time, event-by-event data), Academic Analytics **aggregates and synthesises** large volumes of data to reveal patterns and trends that are not visible in the individual event stream.

It is especially useful for:
- Amateur radio operators who want to **identify the best times and bands** for operation
- Post-session analysis of an evening's operation or a contest
- Academic work or reports on HF propagation conditions
- Comparing activity across bands and modes over days or weeks

### Access

- **Data Analysis** button in the toolbar (opens in a new tab)
- Or directly at `http://localhost:8000/4ham_academic_analytics.html`

Data is fetched from the server and **auto-refreshes every 60 seconds**. The header shows the timestamp of the last query and a countdown timer for the next refresh.

### Period selector

| Preset | Period | Time resolution |
|---|---|---|
| **1h** | Last hour (default on first visit) | Minute |
| **12h** | Last 12 hours | Hour |
| **24h** | Last 24 hours | Hour |
| **7d** | Last 7 days | Hour |
| **30d** | Last 30 days | Day |
| **Custom** | Custom range (start/end date and time) | Automatic |

The active preset is remembered in the browser session. Time resolution (minute, hour, day) is chosen automatically to ensure charts have sufficient detail without becoming overloaded.

> **Tip:** Use **1h** to follow the current operating session in near-real time. Use **7d** or **30d** to study seasonal propagation patterns.

### Band and mode filters

- **Band** — filter by individual band (160m … 70cm) or **All** to see everything
- **Mode** — filter by mode (SSB, FT8, FT4, CW, WSPR) or **All** to see everything
- Click **Apply Filters** after changing filters or the custom range

Filters apply to **all charts and KPIs simultaneously**. This enables focused analysis — for example, viewing only FT8 on the 20m band to assess whether transatlantic propagation is active.

### KPI summary cards — how to interpret

Six cards at the top summarise the overall state for the selected period:

| Card | What it shows | How to interpret |
|---|---|---|
| **Total events** | Total number of events (occupancy + callsigns) | High values indicate active bands and favourable propagation conditions. Compare with earlier periods to assess trends |
| **Unique callsigns** | Number of distinct decoded callsigns | The more unique callsigns, the better the propagation — it means signals from multiple stations are arriving. A high value with high Total events indicates diversified propagation |
| **Average SNR** | Weighted-average SNR in dB | Values above 0 dB indicate generally strong signals. Negative values (e.g. -8 dB) indicate weak but decodable signals. Compare with the mode threshold: FT8 decodes down to -20 dB, SSB needs at least +3 dB |
| **Time coverage** | Percentage of UTC hours that had activity | 100% = activity in every hour of the window. Low values (e.g. 30%) indicate sporadic propagation — the band was only open during some hours |
| **Overall Propagation** | Composite score (0–100) | Global assessment using the 3 formulas (Digital/CW/SSB). **≥ 70** Excellent (🟢), **≥ 50** Good (🟡), **≥ 30** Fair (🟠), **< 30** Poor (🔴). The coloured badge gives a quick visual reading. Reference: [propagation_scoring_reference.md](propagation_scoring_reference.md) |
| **Best band** | Band with best propagation score | Shows which band offered the best conditions in the period. The sub-text shows the score and stability (%) — high stability means consistent propagation, not just isolated peaks |

### Charts — how to interpret

Each chart has an **"i"** icon in the corner of its header. Hovering over the icon reveals a detailed description. Hovering over chart elements (bars, cells, points) shows a tooltip with exact values.

#### Event Time Series

**What it shows**: Event volume over time, aggregated by hour (or minute/day depending on the selected period's resolution).

**How to interpret**:
- **Peaks** indicate moments of high activity — likely a propagation opening or contest
- **Valleys** indicate periods without activity — propagation closed or scan stopped
- **Cyclic patterns** (repeated peaks at the same hours on different days) reveal the normal daily solar cycle — HF propagation increases after sunrise and decreases at night
- **Rising trend** over several days may indicate improving solar conditions

#### Distribution by Band and Mode

**What it shows**: Stacked bar chart — one bar per band, divided by mode colours. Colours: SSB (blue), FT8 (green), FT4 (purple), CW (amber), WSPR (pink).

**How to interpret**:
- **Tall bars** = very active bands in the period
- **Missing bars** = that band had no activity (propagation closed, or simply not monitored)
- **Bar composition**: if a band is dominated by one colour (e.g. all green = FT8), the other modes were not active on that band
- **Compare bar heights** between bands to decide where to operate — for example, if 20m has a tall bar and 15m has a short one, propagation is better on 20m

> **Note:** Only band+mode pairs that had a decoder running will appear in this chart. If you never ran an SSB scan on 12m, no SSB events will appear for 12m — this is not a bug, it is intelligent filtering.

#### Hour of Day × Band — Heatmap Pro

**What it shows**: Interactive matrix of 24 rows (UTC hours 0–23) × columns (bands). Colour intensity = event volume at that hour+band intersection.

**How to interpret**:
- **Light/white cells** = lots of activity at that hour+band combination
- **Dark/black cells** = little or no activity
- **Bright horizontal rows** = hours with high activity across all bands (e.g. 14h–18h UTC on 20m = high Europe→America propagation)
- **Bright vertical columns** = bands active across many hours of the day (bands with consistent propagation)
- **Marginal bars**: at the top (**Σ band**) shows the total per band; on the right (**Σ hour**) shows the total per hour
- **Cross-highlighting**: hovering on a cell highlights its row and column for easy cross-reading

**Practical use**: Identify at which UTC hours your preferred band is most active. Example: if the cell [15h UTC, 20m] is very bright, that is a good time to operate 20m.

#### Top Callsigns in Period

**What it shows**: The 20 most frequently detected callsigns in the period, sorted by number of appearances.

**How to interpret**:
- Callsigns with many appearances are stations that were consistently active and had good propagation to your receiver
- Useful for identifying beacons, contest stations, or DX super-stations
- If your own callsign appears (because you are monitoring another station that sees you), it confirms your signal is getting through

#### Propagation Score by Band

**What it shows**: Vertical bar with propagation score (0–100) for each band in the selected period.

**How to interpret**:
- **Tall bars** (≥ 70) = excellent propagation — consistent decoding, good SNR, many callsigns
- **Medium bars** (50–69) = good propagation — reliable conditions for operation
- **Short bars** (30–49) = fair propagation — marginal signals, intermittent decoding
- **Very short bars** (< 30) = poor propagation — few or no decodes
- **Compare bars across bands** to choose the best band to operate right now
- The numeric label above each bar gives the exact value

#### Propagation Time Trend

**What it shows**: Continuous line showing how the global propagation score varied over time. Dashed horizontal line = period average.

**How to interpret**:
- **Line above average** = conditions better than usual at that moment
- **Line below average** = conditions worse than usual
- **Rising trend** through the day = propagation improving (typical from morning hours until solar peak)
- **Falling trend** = propagation deteriorating (typical after sunset on HF)
- **Frequent oscillations** = unstable propagation
- **Near-flat line, high value** = stable and good conditions — ideal for operation

### How to export data

The dashboard allows exporting the analysed data in three formats. To export:

1. Select the desired **period** and **filters** (band, mode)
2. Click the **Export ▾** button (top-right corner of the controls bar)
3. Choose the format from the dropdown menu:

| Format | Best for | Content |
|---|---|---|
| **CSV** | Opening in Excel/LibreOffice, importing into other tools | Simple table with columns: band, mode, total events, peak SNR, average SNR |
| **JSON** | Programmatic processing (Python, JavaScript, etc.) | Complete object with: aggregated series by band+mode, events per time bucket, all individual events (with callsign, grid, SNR, frequency), propagation scores per band, and time range |
| **XLSX** | Professional reports, detailed analysis in Excel | Workbook with **4 separate sheets**: |

**XLSX file sheets:**

| Sheet | Content | Use |
|---|---|---|
| **Events by Band-Mode** | Data aggregated by band+mode combination | Overview: how many events in each band and mode |
| **Aggregated Events** | Events grouped by time bucket (hour/day) | Temporal trend analysis |
| **All Events** | Every individual event with: timestamp, callsign, band, mode, frequency, SNR, grid locator | Detailed event-by-event analysis, complete log |
| **Propagation by Band** | Propagation score and event count per band | Propagation quality summary |

The file is generated in the browser and downloaded automatically with the name `4ham-analytics_{start}_{end}.{ext}` (e.g. `4ham-analytics_2026-04-07-14-00_2026-04-08-14-00.xlsx`).

### Metadata (footer)

Four informational fields at the bottom of the page:

| Field | Information |
|---|---|
| **Data snapshot** | UTC timestamp of the last server query |
| **Update frequency** | Auto-refresh frequency (every 1 minute) |
| **Analysed period** | Full time range of the current analysis |
| **Data quality** | Data consistency indicator |

---

## Scan Rotation

### What is it?

Scan Rotation lets you define a **sequence of slots (band + mode)** that the system cycles through automatically, switching band/mode at configurable intervals. It is ideal for monitoring multiple bands and modes over long periods without manual intervention.

### How to configure

1. Click **Config Scan Rotation** (button in the scan toolbar).
2. The rotation panel expands with the following controls:
   - **Rotation mode** — `Band + Mode` (each slot defines band and mode) or `Band only` (rotates through bands, keeping the current mode).
   - **Band and Mode** — select the band and mode for the next slot.
   - **Dwell** — time spent on each slot before switching (30 s, 1 min, 2 min, 5 min, 10 min, 15 min, 30 min).
   - **Loop** — if enabled, rotation restarts after the last slot; if disabled, stops at the end.
3. Click **+ Add New Slot** to add each band/mode combination to the list.
4. Slots appear as editable badges — click **×** to remove a slot.
5. Click **Start Rotation** to begin.

### During rotation

- The status bar shows in real time: current slot (band + mode), remaining countdown time, and the next slot.
- A red pulsing dot confirms that rotation is active.
- The **Stop scanning** button stops the rotation (and the current scan).
- Data from all scanned bands/modes accumulates in the database and appears in the analytics dashboards.

---

## Propagation Map — Time Window Selector

The propagation map includes a time window selector controlling which events appear on the globe:

| Option | Period |
|---|---|
| **1h** | Last hour |
| **2h** | Last 2 hours |
| **4h** | Last 4 hours |
| **8h** | Last 8 hours |
| **24h** | Last 24 hours (default) |

Events outside the selected window are not shown on the map. This allows focusing on recent activity or expanding to a full-day view.

---

## User Interface

### Toolbar

| Button | Function |
|--------|----------|
| **Band Config** | Configure bands, frequency ranges, enable/disable individually |
| **Logs & Reports** | Decoder status, Session summary, Logs, Search & Export panel |
| **Admin Config** | SDR, gain, data retention, authentication. Requires administrator login |
| **Help** | User manual (this document) |

### Admin Config panel — Configuration sections

| Section | What it configures |
|---------|-------------------|
| **SDR** | Device selection, gain (dB), sample rate, PPM correction, frequency offset, gain profile |
| **Device Configuration** | Device class (RTL / HackRF / AirSpy / other), PPM correction, frequency offset (Hz), gain profile (auto/manual) |
| **Audio Configuration** | Audio input/output device name (sound card), sample rate (Hz), RX gain multiplier, TX gain multiplier. Reserved for sound card SDR modes |
| **Scan** | Default dwell time, FFT size, overlap |
| **Retention** | Maximum event limit before auto-export+purge; number of recent events to keep; export directory |
| **Authentication** | Change administrator password |
| **SSB Voice Transcription** | Enable/disable Whisper ASR for SSB voice-to-text. Requires `openai-whisper` package |

### Admin Config panel — Buttons

| Button | Function |
|--------|----------|
| **Refresh Devices** | Forces new SoapySDR enumeration bypassing the 300 s cache. Updates the device dropdown and automatically applies the correct gain and sample rate values for the detected device (RTL-SDR: gain 30, 2.048 MS/s; HackRF: gain 20, 2 MS/s; AirSpy: gain 20, 2.5 MS/s) |
| **Save device** | Persists the Device Configuration fields (class, PPM, offset, gain profile) to the database. Form changes are temporary until this button is pressed |
| **Save audio** | Persists the Audio Configuration fields (input/output device, sample rate, RX/TX gain) to the database |
| **Test Config** | Validates the current configuration without saving. Checks: SoapySDR device availability, system audio tools present (`arecord`, `aplay`, `pactl`, `pw-cli`), and that sample rate and gain values are within accepted limits. Reports pass/fail with detail in a toast |
| **Auto-detect Device** | Two-step automatic configuration wizard. Step 1 (dry run): queries the backend for required packages, shows confirmation dialogue with current status and missing dependencies. Step 2 (if approved): installs missing system packages via `sudo`/`pkexec`, detects the SDR device, applies the recommended profile (gain, sample rate, PPM, gain profile) to the form fields, and saves the configuration to the database |
| **Auto-detect Audio** | Queries the backend for available audio devices (PipeWire / PulseAudio / ALSA). Fills in the Audio Configuration fields with detected device names and sample rate. **Does not save automatically** — click **Save audio** afterwards to persist |
| **Purge invalid events** | Prompts for confirmation and deletes all incomplete or malformed occupancy and callsign events from the database (missing timestamp, invalid frequency, null/unknown callsign, etc.). Updates counters in the UI after completion |
| **Reset defaults** | Prompts for confirmation and restores the application's default settings (active modes, summary options and other general settings). **Does not affect** saved events, custom bands, device configuration or audio configuration |
| **Reset total** | ⚠️ Destructive. Prompts for confirmation and deletes **all** settings and custom bands from the database (`DELETE FROM settings`, `DELETE FROM bands`), clears the browser's localStorage and reloads the page. Equivalent to a clean installation state. Events are not affected |

### Scan controls
- **Start scanning / Stop scanning** — starts or stops the active scan
- **Band buttons** (160m … 10m) — switch band immediately, even with scan running
- **Mode buttons** (CW / WSPR / FT4 / FT8 / SSB) — select the decoder or switch the scan in real time; the events panel synchronises immediately on mode change (v0.8.4)
- **SSB Max Holds** (SSB mode, default `0` = auto) — maximum number of *pauses* per full band sweep on active SSB frequencies. `0` = adaptive calculation (~1 hold per 50 kHz of bandwidth, min 4, max 12). Only applied when starting the scan; has no effect with scan already running.

### Event filter (dropdown)

| Option | Shows |
|--------|-------|
| **Show All** | All events with callsign: FT8/FT4, WSPR, CW, APRS, SSB Voice Signature |
| **Callsign Only** | Only events with decoded callsign (excludes Voice Signature) |
| **SSB Callsign Detected** | SSB with callsign resolved by Whisper ASR |
| **SSB Traffic Only** | SSB occupancy (voice detected, no callsign) |
| **CW Only** | CW decodes |
| **All + Occupancy (raw)** | Everything, including raw occupancy — useful for diagnostics |

---

## Spectrogram Interpretation

### Waterfall
- **Horizontal axis**: frequency in MHz
- **Vertical axis**: time (most recent at top, flows downward)
- **Colour**: signal intensity — dark blue = noise floor, yellow/red = strong signal
- **Mode markers**: fixed coloured labels at known dial frequencies (e.g., FT8 14.074 MHz)

### Marker colours

| Colour | Mode |
|--------|------|
| Blue | FT8 |
| Green | FT4 |
| Orange | WSPR |
| Pink/Purple | CW |
| Light blue | SSB / Voice Signature |

### Marker TTL

| Mode | TTL | Decode window |
|------|-----|--------------|
| FT8  | 45 s | 15 s |
| FT4  | 23 s | 7.5 s |
| WSPR | 360 s | 120 s |
| CW   | 45 s | dwell 30 s |
| SSB  | 20 s | continuous |

### Waterfall interaction
- **Horizontal drag** — pan when zoom > ×1
- **Zoom slider** — horizontal zoom from ×1 (full band) to ×16
- **Hover** — VFO bar shows the frequency under the cursor and real-time SNR
- **"Go to" field** — type the frequency in MHz and press `Enter` to centre the view

---

## Data Export

### Search & Export Data panel
Accessed via **Logs & Reports → Search & Export Data**.

**Available filters:**
- Date/time range (from / to)
- Band
- Mode
- Callsign (partial search)
- Country / DXCC prefix
- Minimum SNR

**Export formats:**
- **CSV** — compatible with Excel, LibreOffice Calc
- **JSON** — structured data for programmatic processing
- **PNG** — capture of the current events table state

Files are saved to `data/exports/`.

### Automatic export (retention)
When the total number of events exceeds the configured limit (default: 500,000), the system:
1. Exports all events to CSV in `data/exports/`
2. Keeps only the 50,000 most recent events (configurable)

Retention runs at most once per day and can be triggered manually in the Admin panel.

---

## Troubleshooting

### Waterfall is blank / "No live spectrum data"
This appears only when the scan is active but no FFT frames are arriving. Check:
- The SDR is connected and recognised (`rtl_test` or `SoapySDRUtil --find`)
- No other programme (GQRX, SDR#) is using the device
- The backend is running — check in **Logs & Reports → Server logs**

### No FT8/FT4 callsigns appearing
- Verify that `jt9` (from the WSJT-X package) is installed and in the system PATH
- In **Decoder Status**: the jt9 pipeline should show "running"
- Weak propagation may result in zero decodes even with visible spectrum

### RTL-SDR v4 is not detected
- Confirm that the `rtlsdrblog/rtl-sdr-blog` driver was compiled (the `apt rtl-sdr` package does not support the v4 version)
- Check the kernel module blacklist: `cat /etc/modprobe.d/blacklist-rtl.conf`
- Restart and reconnect the USB dongle

### Too many SSB_TRAFFIC / Voice Signature events in the panel
Since v0.8.4 the system has built-in protection: 30 s debounce per segment, SNR gate (8 dB minimum) and SSB_VOICE markers only with ASR confirmation. If there is still too much activity:
- Use the **Callsign Only** filter to show only events with resolved callsign
- Use the **SSB Callsign Detected** filter for only Whisper events with confirmed callsign

### The server stopped / is not responding
- Check system logs: `journalctl -u 4ham-spectrum-analysis -n 50`
- If the RTL-SDR had an unstable USB connection, reconnect the dongle and restart the service
- The system uses a device enumeration cache (TTL 30 s) to reduce USB calls under unstable hardware conditions
- SoapySDR enumeration runs in a child process since v0.8.4 — if the `libuhd` library causes a native crash (SIGSEGV), only the child process terminates and the server continues running

### Where is the data stored?
- Events: `data/events.sqlite`
- Automatic and manual exports: `data/exports/`
- Server logs: `logs/`
