/*
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

Application-wide constants — no DOM, no state, no side-effects.
Extracted from app.js as part of the ES6 module migration.
*/

// ---------------------------------------------------------------------------
// UI / panel sizing
// ---------------------------------------------------------------------------
export const EVENTS_PANEL_PAGE_SIZE = 50;
export const SEARCH_PAGE_SIZE = 50;
export const AUTH_PASSWORD_MASK = "********";

// ---------------------------------------------------------------------------
// Spectrum / waterfall signal processing
// ---------------------------------------------------------------------------
export const _SPEC_SMOOTH_ALPHA = 0.2;
export const FFT_HISTORY_MAX = 300;

// ---------------------------------------------------------------------------
// localStorage keys
// ---------------------------------------------------------------------------
export const SHOW_NON_SDR_DEVICES_KEY = "showNonSdrDevices";
export const WATERFALL_EXPLORER_KEY = "waterfallExplorerEnabled";
export const WATERFALL_EXPLORER_ZOOM_KEY = "waterfallExplorerZoom";

// ---------------------------------------------------------------------------
// Waterfall marker TTLs and buckets
// ---------------------------------------------------------------------------
export const WATERFALL_GENERIC_STATUS = "No live spectrum data available. Check SDR device connection and scan status.";
export const WATERFALL_SIMULATE_MODE_MARKERS = false;

export const WATERFALL_MARKER_TTL_MS = 12000;        // generic DSP markers
export const WATERFALL_MARKER_TTL_CW_MS = 45000;     // CW: matches backend cw_sweep_dwell_s(30) × 1.5
export const WATERFALL_MARKER_TTL_SSB_MS = 20000;    // SSB fallback when pass_count is unavailable
export const WATERFALL_MARKER_TTL_SSB_VOICE_MS = 45000; // SSB VOICE: Whisper-confirmed voice markers (45 s)
export const WATERFALL_MARKER_TTL_SSB_PASSES = 2;    // expire SSB markers after 2 passes
export const WATERFALL_MARKER_BUCKET_HZ = 50;
export const WATERFALL_MARKER_BUCKET_SSB_HZ = 1000;

// TTL = 3 × mode_window; allows 2 consecutive missed decode cycles.
// FT8:  3 × 15 s  =  45 s
// FT4:  3 × 7.5 s =  23 s (rounded up)
// WSPR: 3 × 120 s = 360 s
export const WATERFALL_DECODED_MARKER_TTL_FT8_MS  =  45 * 1000;
export const WATERFALL_DECODED_MARKER_TTL_FT4_MS  =  23 * 1000;
export const WATERFALL_DECODED_MARKER_TTL_WSPR_MS = 360 * 1000;
export const WATERFALL_DECODED_MARKER_TTL_SSB_VOICE_MS = 30 * 1000;

export const WATERFALL_CALLSIGN_TTL_MS = 45 * 1000;       // match FT8 TTL (dominant mode)
export const WATERFALL_CALLSIGN_MAX_DELTA_HZ = 1500;       // DSP-marker to callsign proximity

// Maximum distance from a decoded freq to a known dial freq.
// FT8 audio range is 0-3000 Hz; +1 kHz margin for direct-sampling offset.
export const WATERFALL_DIAL_SNAP_HZ = 4000;

export const WATERFALL_SEGMENT_COUNT = 12;

// ---------------------------------------------------------------------------
// Standard dial frequencies (FT8 / FT4 / WSPR), mirrored from the backend.
// Used to snap decoded callsigns to a single marker position per band/mode.
// ---------------------------------------------------------------------------
export const WATERFALL_DIAL_FREQUENCIES = {
  "160m": { FT8: 1_840_000, FT4: 1_840_000, WSPR: 1_836_600 },
  "80m":  { FT8: 3_573_000, FT4: 3_575_500, WSPR: 3_592_600 },
  "60m":  { FT8: 5_357_000, FT4: 5_357_000, WSPR: 5_287_200 },
  "40m":  { FT8: 7_074_000, FT4: 7_047_500, WSPR: 7_040_100 },
  "30m":  { FT8: 10_136_000, FT4: 10_140_000, WSPR: 10_140_200 },
  "20m":  { FT8: 14_074_000, FT4: 14_080_000, WSPR: 14_095_600 },
  "17m":  { FT8: 18_100_000, FT4: 18_104_000, WSPR: 18_104_600 },
  "15m":  { FT8: 21_074_000, FT4: 21_140_000, WSPR: 21_094_600 },
  "12m":  { FT8: 24_915_000, FT4: 24_919_000, WSPR: 24_924_600 },
  "10m":  { FT8: 28_074_000, FT4: 28_180_000, WSPR: 28_124_600 },
  "6m":   { FT8: 50_313_000, FT4: 50_318_000, WSPR: 50_293_000 },
  "2m":   { FT8: 144_174_000, FT4: 144_170_000, WSPR: 144_489_000 },
};

export const WATERFALL_CW_FOCUS_FREQUENCIES = {
  "160m": 1_830_000,
  "80m":  3_530_000,
  "60m":  5_355_000,
  "40m":  7_030_000,
  "30m":  10_120_000,
  "20m":  14_050_000,
  "17m":  18_086_000,
  "15m":  21_050_000,
  "12m":  24_900_000,
  "10m":  28_050_000,
  "6m":   50_100_000,
  "2m":   144_050_000,
};

// ---------------------------------------------------------------------------
// Band presets and CW sub-bands
// ---------------------------------------------------------------------------
export const BAND_PRESETS = {
  "160m": { start_hz: 1810000,   end_hz: 2000000 },
  "80m":  { start_hz: 3500000,   end_hz: 3800000 },
  "40m":  { start_hz: 7000000,   end_hz: 7200000 },
  "20m":  { start_hz: 14000000,  end_hz: 14350000 },
  "17m":  { start_hz: 18068000,  end_hz: 18168000 },
  "15m":  { start_hz: 21000000,  end_hz: 21450000 },
  "12m":  { start_hz: 24890000,  end_hz: 24990000 },
  "10m":  { start_hz: 28000000,  end_hz: 29700000 },
  "2m":   { start_hz: 144000000, end_hz: 146000000 },
  "70cm": { start_hz: 430000000, end_hz: 440000000 },
};

export const DEFAULT_BAND_OPTIONS = [
  { name: "160m", label: "160 m" },
  { name: "80m",  label: "80 m" },
  { name: "40m",  label: "40 m" },
  { name: "20m",  label: "20 m" },
  { name: "17m",  label: "17 m" },
  { name: "15m",  label: "15 m" },
  { name: "12m",  label: "12 m" },
  { name: "10m",  label: "10 m" },
  { name: "2m",   label: "2 m" },
  { name: "70cm", label: "70 cm" },
];

export const CW_DECODER_SUBBANDS = {
  "160m": { start_hz: 1_800_000,  end_hz: 1_840_000 },
  "80m":  { start_hz: 3_500_000,  end_hz: 3_600_000 },
  "40m":  { start_hz: 7_000_000,  end_hz: 7_040_000 },
  "30m":  { start_hz: 10_100_000, end_hz: 10_130_000 },
  "20m":  { start_hz: 14_000_000, end_hz: 14_070_000 },
  "17m":  { start_hz: 18_068_000, end_hz: 18_110_000 },
  "15m":  { start_hz: 21_000_000, end_hz: 21_150_000 },
  "12m":  { start_hz: 24_890_000, end_hz: 24_930_000 },
  "10m":  { start_hz: 28_000_000, end_hz: 28_300_000 },
};

// ---------------------------------------------------------------------------
// Device auto-config profiles
// ---------------------------------------------------------------------------
export const DEVICE_AUTO_PROFILES = {
  rtl:    { sample_rate: 2048000, gain: 30, ppm_correction: 0, frequency_offset_hz: 0, gain_profile: "auto" },
  hackrf: { sample_rate: 2000000, gain: 20, ppm_correction: 0, frequency_offset_hz: 0, gain_profile: "auto" },
  airspy: { sample_rate: 2500000, gain: 20, ppm_correction: 0, frequency_offset_hz: 0, gain_profile: "auto" },
  other:  { sample_rate: 48000,   gain: 20, ppm_correction: 0, frequency_offset_hz: 0, gain_profile: "auto" },
};
