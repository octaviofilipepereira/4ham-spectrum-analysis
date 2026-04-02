/*
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

Pure utility functions — no DOM reads/writes, no global state mutations.
Functions that rely on constants import them from constants.js.
Extracted from app.js as part of the ES6 module migration.
*/

import {
  WATERFALL_DIAL_FREQUENCIES,
  WATERFALL_DIAL_SNAP_HZ,
} from "./constants.js";

// ---------------------------------------------------------------------------
// Number helpers
// ---------------------------------------------------------------------------

export function normalizeNumberInputValue(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

// ---------------------------------------------------------------------------
// Frequency formatting
// ---------------------------------------------------------------------------

export function formatRulerFrequencyLabel(frequencyHz) {
  const mhz = Number(frequencyHz) / 1_000_000;
  if (!Number.isFinite(mhz)) {
    return "-";
  }
  return `${mhz.toFixed(3)} MHz`;
}

export function formatScanRangeSummary(startHz, endHz) {
  const start = Number(startHz || 0);
  const end = Number(endHz || 0);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start <= 0 || end <= start) {
    return "--";
  }
  return `${formatRulerFrequencyLabel(start)} - ${formatRulerFrequencyLabel(end)}`;
}

// ---------------------------------------------------------------------------
// Dial frequency lookup
// ---------------------------------------------------------------------------

export function findDialFrequency(frequencyHz, mode) {
  const normMode = String(mode || "").toUpperCase();
  let best = null;
  let bestDelta = Infinity;
  for (const bandFreqs of Object.values(WATERFALL_DIAL_FREQUENCIES)) {
    const dialHz = bandFreqs[normMode];
    if (!dialHz) continue;
    const delta = Math.abs(Number(frequencyHz) - dialHz);
    if (delta < bestDelta) {
      bestDelta = delta;
      best = dialHz;
    }
  }
  return bestDelta <= WATERFALL_DIAL_SNAP_HZ ? best : null;
}

// ---------------------------------------------------------------------------
// Band inference (broader than BAND_PRESETS; includes 6m and wider ranges)
// ---------------------------------------------------------------------------

export function inferBandFromFrequency(frequencyHz) {
  const value = Number(frequencyHz);
  if (!Number.isFinite(value) || value <= 0) {
    return null;
  }
  const bandRanges = [
    { name: "160m", min: 1800000,   max: 2000000 },
    { name: "80m",  min: 3500000,   max: 4000000 },
    { name: "60m",  min: 5250000,   max: 5450000 },
    { name: "40m",  min: 7000000,   max: 7300000 },
    { name: "30m",  min: 10100000,  max: 10150000 },
    { name: "20m",  min: 14000000,  max: 14350000 },
    { name: "17m",  min: 18068000,  max: 18168000 },
    { name: "15m",  min: 21000000,  max: 21450000 },
    { name: "12m",  min: 24890000,  max: 24990000 },
    { name: "10m",  min: 28000000,  max: 29700000 },
    { name: "6m",   min: 50000000,  max: 54000000 },
    { name: "2m",   min: 144000000, max: 148000000 },
    { name: "70cm", min: 430000000, max: 440000000 },
  ];
  const match = bandRanges.find((range) => value >= range.min && value <= range.max);
  return match ? match.name : null;
}

// ---------------------------------------------------------------------------
// Mode label helpers
// ---------------------------------------------------------------------------

export function normalizeModeLabel(mode) {
  const text = String(mode || "").trim().toUpperCase();
  if (text === "CW_CANDIDATE") {
    return "CW TRAFFIC";
  }
  if (text === "SSB_TRAFFIC") {
    return "SSB TRAFFIC";
  }
  if (text === "SSB_VOICE") {
    return "Voice Signature";
  }
  return text || "SIG";
}

export function modeMatchesSelectedMode(modeValue, selectedModeValue) {
  const mode = String(modeValue || "").trim().toUpperCase();
  const selectedMode = String(selectedModeValue || "").trim().toUpperCase();
  if (!selectedMode) {
    return true;
  }
  if (selectedMode === "CW") {
    return mode === "CW" || mode === "CW_CANDIDATE";
  }
  if (selectedMode === "SSB") {
    return mode === "SSB" || mode === "SSB_TRAFFIC" || mode === "SSB_VOICE";
  }
  return mode === selectedMode;
}

// ---------------------------------------------------------------------------
// Time formatting
// ---------------------------------------------------------------------------

export function formatLastSeenTime(seenAtMs) {
  const timestamp = Number(seenAtMs);
  if (!Number.isFinite(timestamp) || timestamp <= 0) {
    return "-";
  }
  const date = new Date(timestamp);
  if (!Number.isFinite(date.getTime())) {
    return "-";
  }
  return date.toLocaleTimeString();
}

// ---------------------------------------------------------------------------
// Callsign / locator validation and extraction
// ---------------------------------------------------------------------------

export function isValidCallsign(value) {
  const text = String(value || "").trim().toUpperCase();
  if (!text) {
    return true;
  }
  return /^(?=.*[A-Z])[A-Z0-9]{1,3}[0-9][A-Z0-9]{1,4}(\/[A-Z0-9]{1,4})?$/.test(text);
}

export function extractCallsignFromRaw(value) {
  const text = String(value || "").toUpperCase();
  if (!text) {
    return "";
  }
  const match = text.match(/\b(?=[A-Z0-9]*[A-Z])[A-Z0-9]{1,3}[0-9][A-Z0-9]{1,4}(?:\/[A-Z0-9]{1,4})?\b/);
  return match ? match[0] : "";
}

export function isValidLocator(value) {
  const text = String(value || "").trim().toUpperCase();
  if (!text) {
    return true;
  }
  return /^[A-R]{2}[0-9]{2}([A-X]{2})?$/.test(text);
}

// ---------------------------------------------------------------------------
// SSB spectral proof detection
// ---------------------------------------------------------------------------

export function _isSsbSpectralProof(text) {
  if (!text) return false;
  return /Voice spectral signature/i.test(text)
      || /^BW \d/.test(text)
      || /^SSB voice confirmed/i.test(text);
}

// ---------------------------------------------------------------------------
// Decoded text extraction (mode-aware priority)
// ---------------------------------------------------------------------------

export function extractDecodedText(eventItem) {
  if (!eventItem || typeof eventItem !== "object") {
    return "";
  }
  const mode = String(eventItem.mode || "").toUpperCase();
  const isSsb = mode === "SSB" || mode === "SSB_TRAFFIC";
  // For SSB: prioritise raw (Whisper transcript) over msg (spectral summary)
  const candidates = isSsb
    ? [eventItem.raw, eventItem.text, eventItem.msg]
    : [eventItem.msg, eventItem.text, eventItem.raw];
  for (const candidate of candidates) {
    const value = String(candidate || "").trim();
    if (value) {
      return value.length > 220 ? `${value.slice(0, 220)}\u2026` : value;
    }
  }
  return "";
}

// ---------------------------------------------------------------------------
// Network helpers
// ---------------------------------------------------------------------------

/** Returns an empty object — actual auth is handled via session cookies. */
export function getAuthHeader() {
  return {};
}

export function wsUrl(path) {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}${path}`;
}
