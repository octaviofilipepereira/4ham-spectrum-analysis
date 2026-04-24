/*
 * © 2026 Octávio Filipe Gonçalves
 * Callsign: CT7BFV
 * License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
 */
/**
 * waterfall_callsign.test.mjs
 * Full unit tests for the waterfall marker + callsign tooltip logic.
 * Run with:  node --test frontend/tests/waterfall_callsign.test.mjs
 */

import { strict as assert } from "assert";
import { describe, it, before } from "node:test";

// ─── replicate the constants / pure functions from app.js ───────────────────

const DIAL_FREQUENCIES = {
  "160m": { FT8: 1_840_000, FT4: 1_840_000 },
  "80m":  { FT8: 3_573_000, FT4: 3_575_500 },
  "40m":  { FT8: 7_074_000, FT4: 7_047_500 },
  "20m":  { FT8: 14_074_000, FT4: 14_080_000 },
  "17m":  { FT8: 18_100_000, FT4: 18_104_000 },
  "15m":  { FT8: 21_074_000, FT4: 21_140_000 },
  "12m":  { FT8: 24_915_000, FT4: 24_919_000 },
  "10m":  { FT8: 28_074_000, FT4: 28_180_000 },
  "2m":   { FT8: 144_174_000, FT4: 144_170_000 },
};

// How close a decoded frequency must be to a dial frequency to be assigned
const FT_DIAL_SNAP_HZ = 4000; // FT8 audio range is 0-3000 Hz, use 4 kHz to be safe

function findDialFrequency(frequencyHz, mode) {
  let best = null;
  let bestDelta = Infinity;
  for (const bandFreqs of Object.values(DIAL_FREQUENCIES)) {
    const dialHz = bandFreqs[mode];
    if (!dialHz) continue;
    const delta = Math.abs(frequencyHz - dialHz);
    if (delta < bestDelta) {
      bestDelta = delta;
      best = dialHz;
    }
  }
  return bestDelta <= FT_DIAL_SNAP_HZ ? best : null;
}

const WATERFALL_CALLSIGN_TTL_MS = 15 * 60 * 1000;
const WATERFALL_CALLSIGN_MAX_DELTA_HZ = 4000;
const WATERFALL_DECODED_MARKER_TTL_MS = 15 * 60 * 1000;
const WATERFALL_MARKER_TTL_MS = 12_000;

function isValidCallsign(value) {
  const text = String(value || "").trim().toUpperCase();
  if (!text) return true;
  return /^[A-Z0-9]{1,3}[0-9][A-Z0-9]{1,4}(\/[A-Z0-9]{1,4})?$/.test(text);
}

/**
 * Create fresh in-memory caches (simulating a page load).
 * Returns an object with all cache maps + helper functions.
 */
function createCaches() {
  const waterfallCallsignCache = new Map();   // bucket → {callsign, frequency_hz, seen_at, mode}
  const waterfallDecodedMarkerCache = new Map(); // dialFreq → {frequency_hz, mode, seen_at, callsign, seenAtMs}
  const waterfallMarkerCache = new Map();       // bucket → DSP marker

  /**
   * Cache a decoded callsign.  Also upserts the decoded-marker entry
   * at the MODE's dial frequency (one marker per dial freq, not per station).
   */
  function cacheCallsignByFrequency(callsign, frequencyHz, seenAtMs, mode) {
    const normalizedCallsign = String(callsign || "").trim().toUpperCase();
    const numericFrequency = Number(frequencyHz);
    const normalizedMode = String(mode || "").toUpperCase();
    if (!normalizedCallsign || !isValidCallsign(normalizedCallsign)) return;
    if (!Number.isFinite(numericFrequency) || numericFrequency <= 0) return;

    const bucketHz = Math.round(numericFrequency / 50) * 50;
    waterfallCallsignCache.set(String(bucketHz), {
      callsign: normalizedCallsign,
      frequency_hz: numericFrequency,
      seen_at: seenAtMs,
      mode: normalizedMode,
    });

    // Only snap to dial freq for FT8/FT4 — DSP handles other modes
    if (normalizedMode !== "FT8" && normalizedMode !== "FT4") return;

    const dialHz = findDialFrequency(numericFrequency, normalizedMode);
    if (!dialHz) return;

    const key = `${dialHz}_${normalizedMode}`;
    const existing = waterfallDecodedMarkerCache.get(key);
    const ts = Number(seenAtMs);
    // Keep the MOST RECENT callsign at this dial frequency
    if (!existing || ts >= Number(existing.seen_at || 0)) {
      waterfallDecodedMarkerCache.set(key, {
        frequency_hz: dialHz,   // position at dial freq, not audio-offset freq
        mode: normalizedMode,
        snr_db: null,
        seen_at: ts,
        callsign: normalizedCallsign,
        seenAtMs: ts,
        decoded: true,
      });
    }
  }

  function cleanupCallsignCache() {
    const now = Date.now();
    for (const [k, v] of waterfallCallsignCache.entries()) {
      if (now - Number(v?.seen_at || 0) > WATERFALL_CALLSIGN_TTL_MS)
        waterfallCallsignCache.delete(k);
    }
    for (const [k, v] of waterfallDecodedMarkerCache.entries()) {
      if (now - Number(v?.seen_at || 0) > WATERFALL_DECODED_MARKER_TTL_MS)
        waterfallDecodedMarkerCache.delete(k);
    }
  }

  /**
   * Build the final markers array from both caches.
   * Returns markers where each has {frequency_hz, mode, callsign, seenAtMs}.
   * DSP markers win over decoded markers on the same freq.
   */
  function buildMarkers(rangeStartHz, rangeEndHz) {
    const now = Date.now();
    // Expire DSP markers
    for (const [k, v] of waterfallMarkerCache.entries()) {
      if (now - Number(v?.seen_at || 0) > WATERFALL_MARKER_TTL_MS)
        waterfallMarkerCache.delete(k);
    }
    cleanupCallsignCache();

    const merged = new Map();
    // 1. decoded markers (lowest priority)
    for (const [k, v] of waterfallDecodedMarkerCache.entries()) {
      merged.set(k, v);
    }
    // 2. DSP markers override (key = bucket string, different namespace from decoded)
    for (const [k, v] of waterfallMarkerCache.entries()) {
      merged.set(`dsp_${k}`, v);
    }

    return Array.from(merged.values()).filter((m) => {
      const freq = Number(m?.frequency_hz);
      const mode = String(m?.mode || "").toUpperCase();
      if (mode !== "FT8" && mode !== "FT4") return false;
      return Number.isFinite(freq) && freq >= rangeStartHz && freq <= rangeEndHz;
    }).sort((a, b) => Number(a.frequency_hz) - Number(b.frequency_hz));
  }

  /**
   * For a given marker, return the tooltip string.
   * Callsign is already embedded in decoded markers.
   * For DSP markers we fall back to the proximity-based cache lookup.
   */
  function buildTooltip(marker) {
    const freq = Number(marker?.frequency_hz);
    const mode = String(marker?.mode || "").toUpperCase();
    const freqMHz = Number.isFinite(freq) ? (freq / 1e6).toFixed(3) : "?";

    // Decoded markers carry the callsign directly
    const callsign = String(marker?.callsign || "");
    const seenAtMs = Number(marker?.seenAtMs || 0);
    const ageMin = seenAtMs ? Math.round((Date.now() - seenAtMs) / 60000) : null;
    const timeText = ageMin !== null ? `${ageMin}m ago` : "-";

    return `${mode} | ${freqMHz} MHz | callsign ${callsign || "-"} | last ${timeText}`;
  }

  return {
    waterfallCallsignCache,
    waterfallDecodedMarkerCache,
    waterfallMarkerCache,
    cacheCallsignByFrequency,
    buildMarkers,
    buildTooltip,
    cleanupCallsignCache,
  };
}

// ─── helpers ────────────────────────────────────────────────────────────────

/** Build a fake jt9-style event as returned by /api/events */
function makeEvent(callsign, frequencyHz, mode = "FT8", snr = -12, daysAgo = 0) {
  const ts = new Date(Date.now() - daysAgo * 86400000).toISOString();
  return { type: "callsign", callsign, frequency_hz: frequencyHz, mode, snr_db: snr, timestamp: ts };
}

/** Simulate fetchCallsignCacheUpdate processing events into the caches */
function ingestEvents(caches, events) {
  for (const e of events) {
    if (!e || e.type !== "callsign" || !e.callsign || !e.frequency_hz) continue;
    const callsign = String(e.callsign).trim().toUpperCase();
    const frequencyHz = Number(e.frequency_hz);
    const mode = String(e.mode || "").toUpperCase();
    const seenAtMs = e.timestamp ? Date.parse(e.timestamp) : Date.now();
    caches.cacheCallsignByFrequency(callsign, frequencyHz, seenAtMs, mode);
  }
}

// ─── tests ──────────────────────────────────────────────────────────────────

describe("findDialFrequency", () => {
  it("maps 40m FT8 audio-offset freq to 7.074 MHz", () => {
    // df_hz range for FT8 is ~100-3000 Hz above dial
    assert.equal(findDialFrequency(7_074_608, "FT8"), 7_074_000);
    assert.equal(findDialFrequency(7_076_466, "FT8"), 7_074_000);
    assert.equal(findDialFrequency(7_075_000, "FT8"), 7_074_000);
    assert.equal(findDialFrequency(7_077_000, "FT8"), 7_074_000); // edge: 3 kHz above
  });

  it("maps 40m FT4 to 7.0475 MHz", () => {
    assert.equal(findDialFrequency(7_047_500, "FT4"), 7_047_500);
    assert.equal(findDialFrequency(7_048_814, "FT4"), 7_047_500);
  });

  it("returns null for unknown freqs far from any dial", () => {
    assert.equal(findDialFrequency(7_080_000, "FT8"), null); // >4 kHz from 7.074
    assert.equal(findDialFrequency(7_068_000, "FT4"), null);
  });

  it("maps 20m FT8 to 14.074 MHz", () => {
    assert.equal(findDialFrequency(14_074_500, "FT8"), 14_074_000);
  });
});

describe("cacheCallsignByFrequency — one marker per dial freq", () => {
  it("40m FT8: 30 different stations → only ONE decoded marker at 7.074 MHz", () => {
    const C = createCaches();
    // Simulate 30 FT8 stations decoded on 40m, each at a different audio offset
    for (let i = 0; i < 30; i++) {
      C.cacheCallsignByFrequency(`AA${i}AAA`, 7_074_000 + (i + 1) * 80, Date.now(), "FT8");
    }
    assert.equal(C.waterfallDecodedMarkerCache.size, 1, "should be exactly 1 FT8 marker");
    const [key] = C.waterfallDecodedMarkerCache.keys();
    assert.ok(key.includes("7074000"), `key should contain dial freq, got: ${key}`);
    const marker = [...C.waterfallDecodedMarkerCache.values()][0];
    assert.equal(marker.frequency_hz, 7_074_000, "marker positioned at dial freq");
    assert.equal(marker.mode, "FT8");
  });

  it("keeps the MOST RECENT callsign at each dial frequency", () => {
    const C = createCaches();
    const older = Date.now() - 5000;
    const newer = Date.now();
    C.cacheCallsignByFrequency("CT7OLD", 7_074_800, older, "FT8");  // valid: CT7 + 7(digit in prefix)... wait: CT7OLD = C(1)+T(2)+7(digit)+O+L+D — YES, matches {1,2}[A-Z]+[0-9]+{1-4}: CT + 7 + OLD
    C.cacheCallsignByFrequency("CT7NEW", 7_075_200, newer, "FT8");
    const marker = [...C.waterfallDecodedMarkerCache.values()][0];
    assert.ok(marker, "marker should exist");
    assert.equal(marker.callsign, "CT7NEW", "newer callsign should win");
  });

  it("FT4 and FT8 on the same band create two separate markers", () => {
    const C = createCaches();
    C.cacheCallsignByFrequency("CT7BFV", 7_074_500, Date.now(), "FT8"); // 40m FT8
    C.cacheCallsignByFrequency("KS4S",   7_047_800, Date.now(), "FT4"); // 40m FT4
    assert.equal(C.waterfallDecodedMarkerCache.size, 2);
    const modes = new Set([...C.waterfallDecodedMarkerCache.values()].map(m => m.mode));
    assert.ok(modes.has("FT8") && modes.has("FT4"), "both FT8 and FT4 markers present");
  });

  it("callsign with invalid format is rejected", () => {
    const C = createCaches();
    C.cacheCallsignByFrequency("INVALID!!!", 7_074_500, Date.now(), "FT8");
    assert.equal(C.waterfallDecodedMarkerCache.size, 0);
  });
});

describe("buildMarkers — correct output for rendering", () => {
  it("returns markers within band range only", () => {
    const C = createCaches();
    C.cacheCallsignByFrequency("CT7BFV",  7_074_500, Date.now(), "FT8"); // 40m ✓
    C.cacheCallsignByFrequency("PY3WZ",  14_075_000, Date.now(), "FT8"); // 20m ✗ (out of 40m range)
    const markers = C.buildMarkers(7_000_000, 7_200_000);
    assert.equal(markers.length, 1);
    assert.equal(markers[0].frequency_hz, 7_074_000);
  });

  it("markers have callsign embedded", () => {
    const C = createCaches();
    C.cacheCallsignByFrequency("HK3TY", 7_076_466, Date.now(), "FT8");
    const markers = C.buildMarkers(7_000_000, 7_200_000);
    assert.equal(markers.length, 1);
    assert.equal(markers[0].callsign, "HK3TY");
  });

  it("multiple FT8 callsigns: one marker with the newest callsign", () => {
    const C = createCaches();
    const now = Date.now();
    C.cacheCallsignByFrequency("CT7EA1", 7_074_200, now - 10000, "FT8");
    C.cacheCallsignByFrequency("CT7EA2", 7_075_000, now - 5000,  "FT8");
    C.cacheCallsignByFrequency("CT7NEW", 7_074_800, now,          "FT8");
    const markers = C.buildMarkers(7_000_000, 7_200_000);
    assert.equal(markers.length, 1, `only one FT8 marker, got ${markers.length}`);
    assert.equal(markers[0].callsign, "CT7NEW", "shows newest callsign");
  });
});

describe("ingestEvents (simulated fetchCallsignCacheUpdate)", () => {
  it("processes 100 FT8 events → exactly 1 FT8 marker on 40m", () => {
    const C = createCaches();
    const events = [];
    for (let i = 0; i < 100; i++) {
      // Simulate different audio offsets (100-3000 Hz) over 7074 kHz
      const df = 100 + i * 29;
      events.push(makeEvent(`AA${i < 10 ? "0" : ""}${i}AAA`, 7_074_000 + df, "FT8"));
    }
    ingestEvents(C, events);
    const markers = C.buildMarkers(7_000_000, 7_200_000);
    assert.equal(markers.length, 1, `expected 1 marker, got ${markers.length}`);
    assert.equal(markers[0].frequency_hz, 7_074_000);
    assert.equal(markers[0].mode, "FT8");
    assert.ok(markers[0].callsign, "callsign should be set");
  });

  it("tooltip text contains the callsign and frequency", () => {
    const C = createCaches();
    const events = [
      makeEvent("ZV5PR", 7_074_353, "FT8"),
      makeEvent("KS4S",  7_047_800, "FT4"),
    ];
    ingestEvents(C, events);
    const markers = C.buildMarkers(7_000_000, 7_200_000);
    assert.equal(markers.length, 2, `expected 2 markers, got ${markers.length}`);
    for (const m of markers) {
      const tooltip = C.buildTooltip(m);
      assert.ok(tooltip.includes(m.callsign), `tooltip missing callsign: ${tooltip}`);
      assert.ok(tooltip.includes("MHz"), `tooltip missing freq: ${tooltip}`);
    }
  });

  it("skips events with missing callsign or freq", () => {
    const C = createCaches();
    ingestEvents(C, [
      { type: "callsign", callsign: "", frequency_hz: 7_074_500, mode: "FT8" },
      { type: "callsign", callsign: "CT7BFV", frequency_hz: null,  mode: "FT8" },
      { type: "occupancy", callsign: "PY3WZ", frequency_hz: 7_074_500, mode: "FT8" },
    ]);
    assert.equal(C.waterfallDecodedMarkerCache.size, 0);
  });

  it("FT4 event outside known dial range is not injected as a marker", () => {
    const C = createCaches();
    // A freq far from any known FT4 dial
    ingestEvents(C, [makeEvent("CT7BFV", 7_060_000, "FT4")]);
    assert.equal(C.waterfallDecodedMarkerCache.size, 0, "no marker for unknown dial");
    // But callsign cache should still have it (for proximity fallback)
    assert.equal(C.waterfallCallsignCache.size, 1);
  });
});

describe("buildTooltip", () => {
  it("shows dash when callsign is missing", () => {
    const C = createCaches();
    const fakeMarker = { frequency_hz: 7_074_000, mode: "FT8", callsign: "", seenAtMs: null };
    const t = C.buildTooltip(fakeMarker);
    assert.ok(t.includes("callsign -"), `expected 'callsign -' in: ${t}`);
  });

  it("shows callsign and time when present", () => {
    const C = createCaches();
    const marker = { frequency_hz: 7_074_000, mode: "FT8", callsign: "HK3TY", seenAtMs: Date.now() - 60000 };
    const t = C.buildTooltip(marker);
    assert.ok(t.includes("HK3TY"), `callsign missing: ${t}`);
    assert.ok(t.includes("7.074 MHz"), `freq missing: ${t}`);
    assert.ok(t.includes("ago"), `time missing: ${t}`);
  });
});
