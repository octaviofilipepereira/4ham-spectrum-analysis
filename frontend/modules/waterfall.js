// ─────────────────────────────────────────────────────────────────────────────
// WaterfallController — all waterfall canvas, spectrum graph, explorer,
// ruler, mode overlay, callsign cache, VFO display and drag interaction logic.
//
// Instantiate once with DOM refs and callbacks after DOMContentLoaded.
// Pass isScanRunning and selectedDecoderMode before each processLiveFrame()
// call so markers are built against the latest app state.
// ─────────────────────────────────────────────────────────────────────────────

import {
  WATERFALL_EXPLORER_KEY,
  WATERFALL_EXPLORER_ZOOM_KEY,
  WATERFALL_SEGMENT_COUNT,
  WATERFALL_GENERIC_STATUS,
  WATERFALL_CW_FOCUS_FREQUENCIES,
  WATERFALL_DIAL_FREQUENCIES,
  WATERFALL_SIMULATE_MODE_MARKERS,
  FFT_HISTORY_MAX,
  _SPEC_SMOOTH_ALPHA,
  WATERFALL_MARKER_TTL_MS,
  WATERFALL_MARKER_TTL_CW_MS,
  WATERFALL_MARKER_TTL_SSB_MS,
  WATERFALL_MARKER_TTL_SSB_VOICE_MS,
  WATERFALL_MARKER_TTL_SSB_PASSES,
  WATERFALL_MARKER_BUCKET_HZ,
  WATERFALL_MARKER_BUCKET_SSB_HZ,
  WATERFALL_DECODED_MARKER_TTL_FT8_MS,
  WATERFALL_DECODED_MARKER_TTL_FT4_MS,
  WATERFALL_DECODED_MARKER_TTL_WSPR_MS,
  WATERFALL_DECODED_MARKER_TTL_SSB_VOICE_MS,
  WATERFALL_CALLSIGN_TTL_MS,
  WATERFALL_CALLSIGN_MAX_DELTA_HZ,
} from "./constants.js";

import {
  formatRulerFrequencyLabel,
  normalizeModeLabel,
  modeMatchesSelectedMode,
  isValidCallsign,
  extractCallsignFromRaw,
  findDialFrequency,
  formatLastSeenTime,
} from "./utils.js";

// ── FT-DX10 "jet" palette ─────────────────────────────────────────────────
// Colour stops match Yaesu FT-DX10 waterfall display.
const _FTDX10_STOPS = [
  { t: 0.00, r:   0, g:   0, b:   0 },
  { t: 0.12, r:   0, g:  10, b: 160 },
  { t: 0.32, r:  20, g:  80, b: 255 },
  { t: 0.48, r:   0, g: 235, b: 255 },
  { t: 0.63, r:  30, g: 220, b:   0 },
  { t: 0.76, r: 255, g: 242, b:   0 },
  { t: 0.88, r: 255, g: 115, b:   0 },
  { t: 0.93, r: 255, g:  38, b:   0 },
  { t: 1.00, r: 200, g:   0, b:   0 },
];

function colorMap(value) {
  const v = value < 0 ? 0 : value > 1 ? 1 : value;
  const stops = _FTDX10_STOPS;
  for (let i = 1; i < stops.length; i++) {
    if (v <= stops[i].t) {
      const a = stops[i - 1], b = stops[i];
      const f = (v - a.t) / (b.t - a.t);
      return [
        Math.round(a.r + f * (b.r - a.r)),
        Math.round(a.g + f * (b.g - a.g)),
        Math.round(a.b + f * (b.b - a.b)),
      ];
    }
  }
  return [200, 0, 0];
}

// ─────────────────────────────────────────────────────────────────────────────

export class WaterfallController {
  // ── Canvas / renderer ──
  #canvas;
  #ctx = null;
  #webglWaterfall = null;
  #renderer = "2d";
  #specSmooth = null;

  // ── History / frame ──
  #row = 0;
  #fftHistoryFrames = [];
  #lastFrame = null;
  #lastFrameTs = 0;

  // ── Drag ──
  #dragRafPending = false;
  #dragActive = false;
  #dragStartX = 0;
  #dragStartPan = 0;

  // ── Marker caches ──
  #markerCache = new Map();
  #decodedMarkerCache = new Map();

  // ── Callsign cache ──
  #callsignCache = new Map();
  #latestCallsign = { callsign: "", seenAtMs: null };

  // ── Hover tooltip ──
  #hoverTooltip = null;
  #hoverActive = false;
  #lastTooltipText = "";
  #lastTooltipX = 0;
  #lastTooltipY = 0;

  // ── Overlay fingerprint (skip-redraw optimisation) ──
  #overlayFingerprint = "";

  // ── Explorer ──
  #explorerEnabled;
  #explorerZoom;
  #explorerPan = 0;

  // ── VFO ──
  #vfoDisplayHz = 0;

  // ── DOM refs and app callbacks ──
  #dom;
  #cb;

  // ── Public app-state properties (set by app.js before each frame) ──
  isScanRunning = false;
  selectedDecoderMode = null;

  /**
   * @param {object} dom  - DOM element refs
   * @param {object} cb   - Callbacks: getScanRange(bandName), onVFOUpdate(), showToast(msg)
   */
  constructor(dom, cb = {}) {
    this.#dom = dom;
    this.#cb = cb;
    this.#canvas = dom.canvas;

    // Restore explorer state from localStorage
    this.#explorerEnabled = localStorage.getItem(WATERFALL_EXPLORER_KEY) !== "0";
    this.#explorerZoom = Number(localStorage.getItem(WATERFALL_EXPLORER_ZOOM_KEY) || 1);
    if (!Number.isFinite(this.#explorerZoom)) this.#explorerZoom = 1;
    this.#explorerZoom = Math.max(1, Math.min(16, Math.round(this.#explorerZoom)));
    if (this.#explorerZoom > 1) {
      const maxPan = Math.max(0, 1 - 1 / this.#explorerZoom);
      this.#explorerPan = maxPan / 2;
    }

    this.#initRenderer();
    this.resize();
    this.#initEventListeners();
  }

  // ── Public getters ────────────────────────────────────────────────────────

  get renderer()      { return this.#renderer; }
  get lastFrame()     { return this.#lastFrame; }
  get lastFrameTs()   { return this.#lastFrameTs; }
  get explorerEnabled() { return this.#explorerEnabled; }
  get explorerZoom()  { return this.#explorerZoom; }
  get explorerPan()   { return this.#explorerPan; }

  // ── Resize ───────────────────────────────────────────────────────────────

  resize() {
    const canvas = this.#canvas;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (this.#webglWaterfall) {
      this.#webglWaterfall.resize(rect.width, rect.height);
      return;
    }
    canvas.width  = Math.floor(rect.width  * window.devicePixelRatio);
    canvas.height = Math.floor(rect.height * window.devicePixelRatio);
    if (!this.#ctx) this.#ctx = canvas.getContext("2d");
    this.#ctx.setTransform(1, 0, 0, 1, 0, 0);
    this.#ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
  }

  // ── Live frame processing (called from connectSpectrum) ──────────────────

  /**
   * Store the frame, draw waterfall + spectrum, build markers + ruler + overlay.
   * Returns { viewport, rulerRange } for the caller to build the status line.
   */
  processLiveFrame(frame) {
    this.#lastFrame  = frame;
    this.#lastFrameTs = Date.now();
    const viewport = this.getViewport(frame);
    this.drawWaterfall(frame, viewport, false);
    this.drawSpectrum(viewport.fftDb);
    const stableMarkers = this.buildStableMarkers(frame);
    const rulerRange = this.resolveRulerRange(
      frame, viewport, stableMarkers.rangeStartHz, stableMarkers.rangeEndHz
    );
    this.renderRuler(rulerRange.startHz, rulerRange.endHz);
    this.updateVFODisplay(rulerRange.startHz, rulerRange.endHz);
    const simulatedMarkers = this.buildSimulatedMarkers(
      viewport.visibleSpanHz, rulerRange.startHz, rulerRange.endHz
    );
    const modeMarkers = WATERFALL_SIMULATE_MODE_MARKERS
      ? [...stableMarkers.markers, ...simulatedMarkers]
      : stableMarkers.markers;
    this.renderModeOverlay(modeMarkers, viewport.visibleSpanHz, rulerRange.startHz, rulerRange.endHz);
    return { viewport, rulerRange };
  }

  // ── Status helpers ───────────────────────────────────────────────────────

  setGenericStatus(message = WATERFALL_GENERIC_STATUS) {
    const { waterfallStatus, waterfallRuler, waterfallModeOverlay } = this.#dom;
    if (!waterfallStatus) return;
    waterfallStatus.textContent = message;
    waterfallStatus.classList.add("is-generic");
    if (waterfallRuler) waterfallRuler.innerHTML = "";
    if (waterfallModeOverlay) waterfallModeOverlay.innerHTML = "";
  }

  clearGenericStatus() {
    const { waterfallStatus } = this.#dom;
    if (!waterfallStatus) return;
    waterfallStatus.classList.remove("is-generic");
  }

  showTransition(message) {
    const { waterfallTransition, waterfallTransitionMsg } = this.#dom;
    if (!waterfallTransition || !waterfallTransitionMsg) return;
    waterfallTransitionMsg.textContent = message;
    waterfallTransition.hidden = false;
  }

  hideTransition() {
    const { waterfallTransition, waterfallTransitionMsg } = this.#dom;
    if (!waterfallTransition) return;
    waterfallTransition.hidden = true;
    if (waterfallTransitionMsg) waterfallTransitionMsg.textContent = "";
  }

  updateModeBadge() {
    const { waterfallModeBadge } = this.#dom;
    if (!waterfallModeBadge) return;
    waterfallModeBadge.textContent = "LIVE";
    waterfallModeBadge.classList.remove("is-fake");
    waterfallModeBadge.classList.add("is-live");
  }

  // ── Explorer UI ──────────────────────────────────────────────────────────

  applyExplorerUi() {
    const { waterfallExplorerToggle, waterfallZoomInput, waterfallResetViewBtn, waterfallEl } = this.#dom;
    if (waterfallExplorerToggle) {
      waterfallExplorerToggle.textContent = `Explorer SIM: ${this.#explorerEnabled ? "ON" : "OFF"}`;
    }
    if (waterfallZoomInput) {
      waterfallZoomInput.value = String(this.#explorerZoom);
      waterfallZoomInput.disabled = !this.#explorerEnabled;
    }
    if (waterfallResetViewBtn) {
      waterfallResetViewBtn.disabled = !this.#explorerEnabled;
    }
    if (waterfallEl) {
      waterfallEl.classList.toggle("is-draggable", this.#explorerEnabled);
      waterfallEl.classList.remove("is-dragging");
    }
  }

  resetExplorerView() {
    this.#explorerZoom = 1;
    this.#explorerPan  = 0;
    localStorage.setItem(WATERFALL_EXPLORER_ZOOM_KEY, "1");
    this.applyExplorerUi();
    this.redrawFromHistory();
  }

  // ── Frequency range helpers ──────────────────────────────────────────────

  getFullRangeHz() {
    const frame = this.#lastFrame;
    const displayStartHz = Number(frame?.band_display_start_hz || 0);
    const displayEndHz   = Number(frame?.band_display_end_hz   || 0);
    const scanStartHz    = Number(frame?.scan_start_hz || 0);
    const scanEndHz      = Number(frame?.scan_end_hz   || 0);
    const centerHz       = Number(frame?.center_hz     || 0);
    const spanHz         = Number(frame?.span_hz       || 0);
    const hasDisplayRange = Number.isFinite(displayStartHz) && Number.isFinite(displayEndHz)
                            && displayStartHz > 0 && displayEndHz > displayStartHz;
    const hasScanRange    = Number.isFinite(scanStartHz) && Number.isFinite(scanEndHz)
                            && scanStartHz > 0 && scanEndHz > scanStartHz;
    if (hasDisplayRange) return { startHz: displayStartHz, spanHz: displayEndHz - displayStartHz };
    if (hasScanRange)    return { startHz: scanStartHz,    spanHz: scanEndHz - scanStartHz };
    if (Number.isFinite(centerHz) && Number.isFinite(spanHz) && centerHz > 0 && spanHz > 0) {
      const fullSpanHz = spanHz * WATERFALL_SEGMENT_COUNT;
      return { startHz: centerHz - fullSpanHz / 2, spanHz: fullSpanHz };
    }
    const fallbackBand  = this.#dom.bandSelect?.value || "20m";
    const fallbackRange = this.#cb.getScanRange?.(fallbackBand) || { start_hz: 14000000, end_hz: 14350000 };
    const startHz = Number(fallbackRange.start_hz || 0);
    const endHz   = Number(fallbackRange.end_hz   || 0);
    if (startHz > 0 && endHz > startHz) return { startHz, spanHz: endHz - startHz };
    return null;
  }

  #getModeFocusHz(mode) {
    const normalizedMode = String(mode || "").trim().toUpperCase();
    const selectedBand   = String(this.#dom.bandSelect?.value || "").trim().toLowerCase();
    if (normalizedMode === "CW" || normalizedMode === "CW_CANDIDATE") {
      const cwFocusHz = Number(WATERFALL_CW_FOCUS_FREQUENCIES[selectedBand]);
      if (Number.isFinite(cwFocusHz) && cwFocusHz > 0) return cwFocusHz;
    }
    const bandDialFrequencies = WATERFALL_DIAL_FREQUENCIES[selectedBand] || null;
    if (bandDialFrequencies && Number.isFinite(Number(bandDialFrequencies[normalizedMode]))) {
      return Number(bandDialFrequencies[normalizedMode]);
    }
    const bandRange = this.#cb.getScanRange?.(this.#dom.bandSelect?.value || "20m")
                      || { start_hz: 14000000, end_hz: 14350000 };
    const startHz = Number(bandRange.start_hz || 0);
    const endHz   = Number(bandRange.end_hz   || 0);
    if (startHz > 0 && endHz > startHz) return Math.round((startHz + endHz) / 2);
    return null;
  }

  recenterForMode(mode) {
    if (!this.#explorerEnabled) {
      this.#explorerEnabled = true;
      localStorage.setItem(WATERFALL_EXPLORER_KEY, "1");
    }
    if (this.#explorerZoom <= 1) {
      this.#explorerZoom = 4;
      localStorage.setItem(WATERFALL_EXPLORER_ZOOM_KEY, "4");
      this.applyExplorerUi();
    }
    if (this.#explorerZoom <= 1) return;
    const targetHz = Number(this.#getModeFocusHz(mode));
    if (!Number.isFinite(targetHz) || targetHz <= 0) return;
    const fullRange = this.getFullRangeHz();
    if (!fullRange) return;
    const fullStartHz = Number(fullRange.startHz || 0);
    const fullSpanHz  = Number(fullRange.spanHz  || 0);
    if (!Number.isFinite(fullStartHz) || !Number.isFinite(fullSpanHz) || fullSpanHz <= 0) return;
    const clampedTargetHz = Math.max(fullStartHz, Math.min(fullStartHz + fullSpanHz, targetHz));
    const zoom = Math.max(1, Number(this.#explorerZoom || 1));
    const visibleSpanHz  = fullSpanHz / zoom;
    const desiredStartHz = clampedTargetHz - visibleSpanHz / 2;
    const maxPan = Math.max(0, 1 - 1 / zoom);
    this.#explorerPan = Math.max(0, Math.min(maxPan, (desiredStartHz - fullStartHz) / fullSpanHz));
    this.redrawFromHistory();
  }

  /** Called from VFO goto handler in app.js after validation. */
  gotoMhz(mhz, fullStartHz, fullSpanHz) {
    const targetHz = Math.round(mhz * 1_000_000);
    if (!this.#explorerEnabled) {
      this.#explorerEnabled = true;
      localStorage.setItem(WATERFALL_EXPLORER_KEY, "1");
    }
    if (this.#explorerZoom <= 1) {
      this.#explorerZoom = 4;
      localStorage.setItem(WATERFALL_EXPLORER_ZOOM_KEY, "4");
    }
    const zoom = this.#explorerZoom;
    const visibleSpanHz  = fullSpanHz / zoom;
    const desiredStartHz = targetHz - visibleSpanHz / 2;
    const maxPan = Math.max(0, 1 - 1 / zoom);
    this.#explorerPan = Math.max(0, Math.min(maxPan, (desiredStartHz - fullStartHz) / fullSpanHz));
    this.applyExplorerUi();
    this.redrawFromHistory();
  }

  // ── Viewport ─────────────────────────────────────────────────────────────

  getViewport(frame) {
    const base        = Array.isArray(frame?.fft_db) ? frame.fft_db : [];
    const centerHz    = Number(frame?.center_hz || 0);
    const spanHz      = Number(frame?.span_hz   || 0);
    const displayStartHz = Number(frame?.band_display_start_hz || 0);
    const displayEndHz   = Number(frame?.band_display_end_hz   || 0);
    const scanStartHz    = Number(frame?.scan_start_hz || 0);
    const scanEndHz      = Number(frame?.scan_end_hz   || 0);
    const hasDisplayRange = Number.isFinite(displayStartHz) && Number.isFinite(displayEndHz)
                            && displayStartHz > 0 && displayEndHz > displayStartHz;
    const hasScanRange    = Number.isFinite(scanStartHz) && Number.isFinite(scanEndHz)
                            && scanStartHz > 0 && scanEndHz > scanStartHz;
    if (!base.length || spanHz <= 0 || !this.#explorerEnabled) {
      return {
        fftDb: base,
        startHz: centerHz - spanHz / 2,
        endHz:   centerHz + spanHz / 2,
        visibleSpanHz: spanHz,
        simulated: false,
      };
    }

    const stitched = this.#buildSegmentedSimulation(frame);
    const zoom = Math.max(1, this.#explorerZoom);
    const totalBins  = stitched.length;
    const visibleBins = Math.max(256, Math.floor(totalBins / zoom));
    const maxPan = Math.max(0, 1 - 1 / zoom);
    this.#explorerPan = Math.max(0, Math.min(maxPan, this.#explorerPan));
    const startBin = Math.max(0, Math.min(totalBins - visibleBins, Math.round(this.#explorerPan * totalBins)));
    const fftDb = stitched.slice(startBin, startBin + visibleBins);

    const fullSpanHz  = hasDisplayRange
      ? (displayEndHz - displayStartHz)
      : (hasScanRange ? (scanEndHz - scanStartHz) : (spanHz * WATERFALL_SEGMENT_COUNT));
    const visibleSpanHz = fullSpanHz / zoom;
    const fullStartHz   = hasDisplayRange
      ? displayStartHz
      : (hasScanRange ? scanStartHz : (centerHz - fullSpanHz / 2));
    const startHz = fullStartHz + this.#explorerPan * fullSpanHz;
    const endHz   = startHz + visibleSpanHz;

    return { fftDb, startHz, endHz, visibleSpanHz, simulated: true };
  }

  #buildSegmentedSimulation(frame) {
    const base = Array.isArray(frame?.fft_db) ? frame.fft_db : [];
    if (!base.length) return [];
    const now  = Date.now() / 1000;
    const bins = base.length;
    const stitched = [];
    for (let seg = 0; seg < WATERFALL_SEGMENT_COUNT; seg++) {
      const shift = Math.floor(((seg * 0.67) % 1) * bins);
      const gain  = 0.9 + 0.25 * Math.sin(now * 0.2 + seg * 0.6);
      for (let idx = 0; idx < bins; idx++) {
        const source = base[(idx + shift) % bins];
        const ripple = Math.sin((idx / bins) * Math.PI * 6 + seg + now * 0.45) * 2.2;
        stitched.push(source * gain + ripple);
      }
    }
    return stitched;
  }

  // ── Canvas clear ─────────────────────────────────────────────────────────

  clearFrame() {
    this.#row = 0;
    this.#lastFrame  = null;
    this.#lastFrameTs = 0;
    this.#fftHistoryFrames.length = 0;
    if (this.#webglWaterfall) {
      this.resize();
      return;
    }
    if (!this.#ctx) this.#ctx = this.#canvas?.getContext("2d");
    if (!this.#ctx) return;
    const width  = this.#canvas.width  / window.devicePixelRatio;
    const height = this.#canvas.height / window.devicePixelRatio;
    this.#ctx.clearRect(0, 0, width, height);
  }

  // ── Hover tooltip ────────────────────────────────────────────────────────

  #ensureHoverTooltip() {
    const waterfallEl = this.#dom.waterfallEl;
    if (this.#hoverTooltip || !waterfallEl) return this.#hoverTooltip;
    const tooltip = document.createElement("div");
    tooltip.className = "waterfall-hover-tooltip";
    tooltip.setAttribute("role", "tooltip");
    tooltip.classList.add("is-hidden");
    waterfallEl.appendChild(tooltip);
    this.#hoverTooltip = tooltip;
    return this.#hoverTooltip;
  }

  #hideHoverTooltip() {
    const tooltip = this.#ensureHoverTooltip();
    if (!tooltip) return;
    tooltip.classList.add("is-hidden");
    this.#hoverActive = false;
  }

  #showHoverTooltip(text, clientX, clientY) {
    const tooltip = this.#ensureHoverTooltip();
    const waterfallEl = this.#dom.waterfallEl;
    if (!tooltip || !text) return;
    tooltip.textContent = text;
    const rect = waterfallEl.getBoundingClientRect();
    const x = Math.max(10, Math.min(rect.width  - 10, clientX - rect.left));
    const y = Math.max(10, Math.min(rect.height - 10, clientY - rect.top));
    tooltip.style.left = `${x}px`;
    tooltip.style.top  = `${y}px`;
    tooltip.classList.remove("is-hidden");
    this.#hoverActive       = true;
    this.#lastTooltipText   = text;
    this.#lastTooltipX      = clientX;
    this.#lastTooltipY      = clientY;
  }

  // ── Ruler ────────────────────────────────────────────────────────────────

  #computeRulerStepHz(spanHz, rulerWidthPx = 0) {
    const span = Number(spanHz);
    if (!Number.isFinite(span) || span <= 0) return 100_000;
    const widthPx    = Number.isFinite(rulerWidthPx) && rulerWidthPx > 0 ? rulerWidthPx : 960;
    const targetTicks = Math.max(4, Math.min(16, Math.round(widthPx / 110)));
    const rawStepHz  = span / targetTicks;
    if (!Number.isFinite(rawStepHz) || rawStepHz <= 0) return 100_000;
    const magnitude  = 10 ** Math.floor(Math.log10(rawStepHz));
    const normalized = rawStepHz / magnitude;
    let niceFactor = 10;
    if      (normalized <= 1) niceFactor = 1;
    else if (normalized <= 2) niceFactor = 2;
    else if (normalized <= 5) niceFactor = 5;
    const stepHz = niceFactor * magnitude;
    return Math.max(1_000, Math.round(stepHz));
  }

  renderRuler(startHz, endHz) {
    const { waterfallRuler, bandSelect } = this.#dom;
    if (!waterfallRuler) return;
    const start = Number(startHz);
    const end   = Number(endHz);
    const span  = end - start;
    if (!Number.isFinite(start) || !Number.isFinite(end) || span <= 0) {
      waterfallRuler.innerHTML = "";
      return;
    }
    const stepHz = this.#computeRulerStepHz(span, waterfallRuler.clientWidth);
    const selectedBandRange = this.#cb.getScanRange?.(bandSelect?.value || "20m")
                              || { start_hz: start, end_hz: end };
    const gridOriginHz = Number(selectedBandRange?.start_hz || start);
    const firstTick    = gridOriginHz + Math.ceil((start - gridOriginHz) / stepHz) * stepHz;
    const maxTicks = 500;
    let count = 0;
    waterfallRuler.innerHTML = "";
    for (let tickHz = firstTick; tickHz <= end && count < maxTicks; tickHz += stepHz) {
      const normalized = (tickHz - start) / span;
      if (normalized < 0 || normalized > 1) continue;
      const left = `${(normalized * 100).toFixed(2)}%`;
      const tick  = document.createElement("span");
      tick.className  = "waterfall-ruler__tick";
      tick.style.left = left;
      const label = document.createElement("span");
      label.className  = "waterfall-ruler__label";
      label.style.left = left;
      label.textContent = formatRulerFrequencyLabel(tickHz);
      waterfallRuler.appendChild(tick);
      waterfallRuler.appendChild(label);
      count++;
    }
  }

  resolveRulerRange(frame, viewport, stableRangeStartHz = null, stableRangeEndHz = null) {
    const { bandSelect } = this.#dom;
    const isValidRange = (s, e) => {
      const start = Number(s), end = Number(e);
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return false;
      return ((start + end) / 2) > 1_000_000;
    };
    if (isValidRange(stableRangeStartHz, stableRangeEndHz)) {
      if (viewport?.simulated && isValidRange(viewport?.startHz, viewport?.endHz)) {
        return { startHz: Number(viewport.startHz), endHz: Number(viewport.endHz) };
      }
      return { startHz: Number(stableRangeStartHz), endHz: Number(stableRangeEndHz) };
    }
    if (isValidRange(frame?.band_display_start_hz, frame?.band_display_end_hz)) {
      return { startHz: Number(frame.band_display_start_hz), endHz: Number(frame.band_display_end_hz) };
    }
    if (isValidRange(frame?.scan_start_hz, frame?.scan_end_hz)) {
      return { startHz: Number(frame.scan_start_hz), endHz: Number(frame.scan_end_hz) };
    }
    if (isValidRange(viewport?.startHz, viewport?.endHz)) {
      return { startHz: Number(viewport.startHz), endHz: Number(viewport.endHz) };
    }
    const bandRange = this.#cb.getScanRange?.(bandSelect?.value || "20m")
                      || { start_hz: 14000000, end_hz: 14350000 };
    return { startHz: Number(bandRange.start_hz), endHz: Number(bandRange.end_hz) };
  }

  // ── Stable markers ───────────────────────────────────────────────────────

  buildStableMarkers(frame) {
    const currentPassCount    = Number(frame?.pass_count);
    const hasCurrentPassCount = Number.isFinite(currentPassCount) && currentPassCount >= 0;
    const displayStartHz = Number(frame?.band_display_start_hz || 0);
    const displayEndHz   = Number(frame?.band_display_end_hz   || 0);
    const hasDisplayRange = Number.isFinite(displayStartHz) && Number.isFinite(displayEndHz)
                            && displayStartHz > 0 && displayEndHz > displayStartHz;
    const scanStartHz = Number(frame?.scan_start_hz || 0);
    const scanEndHz   = Number(frame?.scan_end_hz   || 0);
    const hasScanRange = Number.isFinite(scanStartHz) && Number.isFinite(scanEndHz)
                         && scanStartHz > 0 && scanEndHz > scanStartHz;
    const defaultStartHz = Number(frame?.center_hz || 0) - Number(frame?.span_hz || 0) / 2;
    const defaultEndHz   = Number(frame?.center_hz || 0) + Number(frame?.span_hz || 0) / 2;
    const rangeStartHz = hasDisplayRange ? displayStartHz : (hasScanRange ? scanStartHz : defaultStartHz);
    const rangeEndHz   = hasDisplayRange ? displayEndHz   : (hasScanRange ? scanEndHz   : defaultEndHz);

    if (!this.isScanRunning || !this.selectedDecoderMode) {
      return { markers: [], rangeStartHz, rangeEndHz };
    }

    const now  = Date.now();
    const selectedMode = String(this.selectedDecoderMode).toUpperCase();

    if (Array.isArray(frame?.mode_markers)) {
      frame.mode_markers.forEach((marker) => {
        const markerModeRaw = String(marker?.mode || "").trim().toUpperCase();
        if (!modeMatchesSelectedMode(markerModeRaw, selectedMode)) return;
        const markerFreq    = Number(marker?.frequency_hz);
        const markerOffset  = Number(marker?.offset_hz ?? 0);
        const inferredFreq  = Number(frame?.center_hz || 0) + markerOffset;
        const frequencyHz   = Number.isFinite(markerFreq) && markerFreq > 0 ? markerFreq : inferredFreq;
        if (!Number.isFinite(frequencyHz) || frequencyHz <= 0) return;
        if (frequencyHz < rangeStartHz || frequencyHz > rangeEndHz) return;
        const isSsbMarker = markerModeRaw === "SSB" || markerModeRaw === "SSB_TRAFFIC";
        const isSsbVoice  = markerModeRaw === "SSB_VOICE";
        const bucketHz = (isSsbMarker || isSsbVoice) ? WATERFALL_MARKER_BUCKET_SSB_HZ : WATERFALL_MARKER_BUCKET_HZ;
        const key = isSsbVoice
          ? `${Math.round(frequencyHz / bucketHz) * bucketHz}_VOICE`
          : `${Math.round(frequencyHz / bucketHz) * bucketHz}`;
        this.#markerCache.set(key, {
          frequency_hz: frequencyHz,
          mode: markerModeRaw,
          snr_db: Number(marker?.snr_db),
          crest_db: Number(marker?.crest_db),
          seen_at: now,
          seen_pass_count: isSsbMarker && hasCurrentPassCount ? currentPassCount : null,
        });
      });
    }

    for (const [key, marker] of this.#markerCache.entries()) {
      const markerModeText = String(marker?.mode || "").trim().toUpperCase();
      const isCw  = markerModeText === "CW" || markerModeText === "CW_CANDIDATE";
      const isSsb = markerModeText === "SSB" || markerModeText === "SSB_TRAFFIC";
      const isSsbVoice = markerModeText === "SSB_VOICE";
      const seenAt = Number(marker?.seen_at || 0);
      if (!Number.isFinite(seenAt) || seenAt <= 0) { this.#markerCache.delete(key); continue; }
      if (isSsb && hasCurrentPassCount) {
        const seenPassCount = Number(marker?.seen_pass_count);
        if (Number.isFinite(seenPassCount) && (currentPassCount - seenPassCount) <= WATERFALL_MARKER_TTL_SSB_PASSES) continue;
        if (Number.isFinite(seenPassCount) && (currentPassCount - seenPassCount) > WATERFALL_MARKER_TTL_SSB_PASSES) {
          this.#markerCache.delete(key); continue;
        }
      }
      const ttl = isCw ? WATERFALL_MARKER_TTL_CW_MS
        : isSsbVoice ? WATERFALL_MARKER_TTL_SSB_VOICE_MS
        : (isSsb ? WATERFALL_MARKER_TTL_SSB_MS : WATERFALL_MARKER_TTL_MS);
      if ((now - seenAt) > ttl) this.#markerCache.delete(key);
    }

    for (const [key, marker] of this.#decodedMarkerCache.entries()) {
      let ttl;
      if      (key.endsWith("_WSPR"))      ttl = WATERFALL_DECODED_MARKER_TTL_WSPR_MS;
      else if (key.endsWith("_FT4"))       ttl = WATERFALL_DECODED_MARKER_TTL_FT4_MS;
      else if (key.endsWith("_SSB_VOICE")) ttl = WATERFALL_DECODED_MARKER_TTL_SSB_VOICE_MS;
      else                                  ttl = WATERFALL_DECODED_MARKER_TTL_FT8_MS;
      if ((now - Number(marker?.seen_at || 0)) > ttl) this.#decodedMarkerCache.delete(key);
    }

    const mergedMarkerMap = new Map();
    for (const [key, marker] of this.#decodedMarkerCache.entries()) mergedMarkerMap.set(key, marker);
    for (const [key, marker] of this.#markerCache.entries())        mergedMarkerMap.set(key, marker);

    const markers = Array.from(mergedMarkerMap.values())
      .filter((marker) => {
        const frequencyHz = Number(marker?.frequency_hz);
        const m = String(marker?.mode || "").toUpperCase();
        if (!modeMatchesSelectedMode(m, selectedMode)) return false;
        return Number.isFinite(frequencyHz) && frequencyHz >= rangeStartHz && frequencyHz <= rangeEndHz;
      })
      .sort((a, b) => Number(a.frequency_hz) - Number(b.frequency_hz));

    return { markers, rangeStartHz, rangeEndHz };
  }

  clearMarkerCaches() {
    this.#markerCache.clear();
    this.#decodedMarkerCache.clear();
    this.#callsignCache.clear();
    this.#overlayFingerprint = "";
  }

  // ── Simulated markers ────────────────────────────────────────────────────

  buildSimulatedMarkers(spanHz, rangeStartHz = null, rangeEndHz = null) {
    if (!WATERFALL_SIMULATE_MODE_MARKERS || !this.selectedDecoderMode) return [];
    const nextSpanHz = Number(spanHz || 0);
    if (nextSpanHz <= 0) return [];
    const hasRange = Number.isFinite(rangeStartHz) && Number.isFinite(rangeEndHz)
                     && Number(rangeEndHz) > Number(rangeStartHz);
    const startHz = hasRange ? Number(rangeStartHz) : -nextSpanHz / 2;
    const endHz   = hasRange ? Number(rangeEndHz)   : nextSpanHz / 2;
    const spanForPlacementHz = endHz - startHz;
    const buildModeSet = (mode, count, snrBase, segStartRatio, segEndRatio) => {
      const items = [];
      const modeSpanRatio = Math.max(0.01, segEndRatio - segStartRatio);
      for (let i = 0; i < count; i++) {
        const ratio = segStartRatio + ((i + 0.5) / count) * modeSpanRatio;
        const frequencyHz = startHz + ratio * spanForPlacementHz;
        const centeredOffsetHz = frequencyHz - (startHz + spanForPlacementHz / 2);
        items.push({ mode, offset_hz: centeredOffsetHz, frequency_hz: hasRange ? frequencyHz : undefined, snr_db: snrBase + (i % 5) * 0.8 });
      }
      return items;
    };
    const selectedMode = String(this.selectedDecoderMode || "").toUpperCase();
    switch (selectedMode) {
      case "FT8": case "FT4": return buildModeSet(selectedMode, 10, 8.0, 0.0, 1.0);
      case "CW":              return buildModeSet("CW", 20, 10.0, 0.0, 1.0);
      case "SSB":             return buildModeSet("SSB", 30, 12.0, 0.0, 1.0);
      case "WSPR":            return buildModeSet("WSPR", 8, 6.0, 0.0, 1.0);
      case "APRS":            return buildModeSet("APRS", 12, 9.0, 0.0, 1.0);
      default:                return [];
    }
  }

  // ── Mode overlay ─────────────────────────────────────────────────────────

  #buildOverlayFingerprint(modeMarkers, rangeStartHz, rangeEndHz) {
    if (!Array.isArray(modeMarkers) || !modeMarkers.length) return "";
    return modeMarkers.map((m) =>
      `${m.frequency_hz}|${m.mode}|${m.callsign || ""}|${m.snr_db ?? ""}|${rangeStartHz}|${rangeEndHz}`
    ).join(";");
  }

  renderModeOverlay(modeMarkers, spanHz, rangeStartHz = null, rangeEndHz = null) {
    const { waterfallModeOverlay } = this.#dom;
    if (!waterfallModeOverlay) return;
    const span = Number(spanHz || 0);
    if (!Array.isArray(modeMarkers) || !modeMarkers.length || span <= 0) {
      if (waterfallModeOverlay.innerHTML !== "") {
        waterfallModeOverlay.innerHTML = "";
        this.#hideHoverTooltip();
      }
      this.#overlayFingerprint = "";
      return;
    }
    const fingerprint = this.#buildOverlayFingerprint(modeMarkers, rangeStartHz, rangeEndHz);
    if (fingerprint === this.#overlayFingerprint) return;
    this.#overlayFingerprint = fingerprint;

    waterfallModeOverlay.innerHTML = "";
    const sortedMarkers = modeMarkers.slice().sort((a, b) => {
      const aFreq = Number(a?.frequency_hz || 0);
      const bFreq = Number(b?.frequency_hz || 0);
      if (aFreq && bFreq) return aFreq - bFreq;
      return Number(a?.offset_hz || 0) - Number(b?.offset_hz || 0);
    });
    const lanes = [[], [], []];
    const hasRange = Number.isFinite(rangeStartHz) && Number.isFinite(rangeEndHz)
                     && Number(rangeEndHz) > Number(rangeStartHz);
    const safeRangeStartHz = hasRange ? Number(rangeStartHz) : null;
    const safeRangeEndHz   = hasRange ? Number(rangeEndHz)   : null;
    const callsignMap = this.#assignCallsignsToMarkers(sortedMarkers.filter((m) => !m?.decoded));

    sortedMarkers.forEach((marker) => {
      const offsetHz   = Number(marker?.offset_hz ?? 0);
      const markerFreq = Number(marker?.frequency_hz);
      let normalized   = 0.5;
      if (hasRange && Number.isFinite(markerFreq)) {
        normalized = (markerFreq - safeRangeStartHz) / (safeRangeEndHz - safeRangeStartHz);
      } else {
        normalized = (offsetHz + span / 2) / span;
      }
      normalized = Math.max(0, Math.min(1, normalized));
      let laneIndex = 0;
      const minDistance = 0.06;
      for (let idx = 0; idx < lanes.length; idx++) {
        if (!lanes[idx].some((pos) => Math.abs(pos - normalized) < minDistance)) { laneIndex = idx; break; }
      }
      lanes[laneIndex].push(normalized);

      const label = document.createElement("span");
      label.className = "waterfall-mode-label";
      if (String(marker?.mode || "").toUpperCase() === "SSB_VOICE") label.classList.add("is-ssb-voice");
      label.style.left = `${(normalized * 100).toFixed(2)}%`;
      label.style.setProperty("--lane-top", `${laneIndex * 22}px`);
      label.textContent = normalizeModeLabel(marker?.mode);

      const snr  = Number(marker?.snr_db);
      const crest = Number(marker?.crest_db);
      const markerKey = String(Math.round(markerFreq / 50) * 50);
      const embeddedCallsign = String(marker?.callsign || "");
      const embeddedSeenAtMs = marker?.seenAtMs || null;
      const proximityMatch   = callsignMap.get(markerKey) || { callsign: "", seenAtMs: null };
      const markerCallsign   = embeddedCallsign || proximityMatch?.callsign || "";
      const markerModeText   = String(marker?.mode || "").trim().toUpperCase();
      const missingCallsignLabel = markerModeText === "CW_CANDIDATE"
        ? "CW TRAFFIC" : markerModeText === "CW" ? "CW"
        : markerModeText === "SSB_VOICE" ? "VOICE SIGNATURE" : "-";
      const markerSeenAtText = formatLastSeenTime(embeddedSeenAtMs || proximityMatch?.seenAtMs);
      const isCwMarker       = markerModeText === "CW" || markerModeText === "CW_CANDIDATE";
      const freqText         = Number.isFinite(markerFreq) && markerFreq > 0
        ? ` | ${(markerFreq / 1_000_000).toFixed(3)} MHz` : "";
      const callsignText     = markerCallsign ? ` | callsign ${markerCallsign}` : ` | ${missingCallsignLabel}`;
      const crestText        = Number.isFinite(crest) ? ` | Crest ${crest.toFixed(1)} dB` : "";
      const statusText       = isCwMarker
        ? `${Number.isFinite(snr) ? ` | SNR(tone) ${snr.toFixed(1)} dB` : " | SNR(tone) -"}${crestText}`
        : ` | last ${markerSeenAtText}`;
      const tooltipText = Number.isFinite(snr)
        ? `${label.textContent}${freqText}${callsignText}${statusText}${isCwMarker ? "" : ` | ${snr.toFixed(1)} dB`}`
        : `${label.textContent}${freqText}${callsignText}${statusText}`;
      label.title = tooltipText;
      label.setAttribute("aria-label", tooltipText);
      label.addEventListener("mouseenter", (e) => { this.#showHoverTooltip(tooltipText, e.clientX, e.clientY); });
      label.addEventListener("mousemove",  (e) => { this.#showHoverTooltip(tooltipText, e.clientX, e.clientY); });
      label.addEventListener("mouseleave", ()  => { this.#hideHoverTooltip(); });
      waterfallModeOverlay.appendChild(label);
    });

    if (this.#hoverActive && this.#lastTooltipText) {
      this.#showHoverTooltip(this.#lastTooltipText, this.#lastTooltipX, this.#lastTooltipY);
    }
  }

  // ── Callsign cache ───────────────────────────────────────────────────────

  #cacheCallsignByFrequency(callsign, frequencyHz, seenAtMs = Date.now(), mode = "") {
    const normalizedCallsign = String(callsign || "").trim().toUpperCase();
    const numericFrequency   = Number(frequencyHz);
    if (!normalizedCallsign || !isValidCallsign(normalizedCallsign)) return;
    if (!Number.isFinite(numericFrequency) || numericFrequency <= 0) return;
    const bucketHz     = Math.round(numericFrequency / 50) * 50;
    const normalizedMode = String(mode || "").toUpperCase();
    this.#callsignCache.set(String(bucketHz), {
      callsign: normalizedCallsign,
      frequency_hz: numericFrequency,
      seen_at: Date.now(),
      seenAtMs,
      mode: normalizedMode,
    });
    if (normalizedMode !== "FT8" && normalizedMode !== "FT4") return;
    const dialHz = findDialFrequency(numericFrequency, normalizedMode);
    if (!dialHz) return;
    const markerKey = `${dialHz}_${normalizedMode}`;
    const existing  = this.#decodedMarkerCache.get(markerKey);
    const ts = Number(seenAtMs);
    if (!existing || ts >= Number(existing.seenAtMs || 0)) {
      this.#decodedMarkerCache.set(markerKey, {
        frequency_hz: dialHz,
        mode: normalizedMode,
        snr_db: null,
        seen_at: Date.now(),
        callsign: normalizedCallsign,
        seenAtMs: ts,
        decoded: true,
      });
    }
  }

  #cacheLatestCallsign(callsign, seenAtMs = Date.now()) {
    const normalizedCallsign = String(callsign || "").trim().toUpperCase();
    const timestampMs        = Number(seenAtMs);
    if (!normalizedCallsign || !isValidCallsign(normalizedCallsign)) return;
    if (!Number.isFinite(timestampMs) || timestampMs <= 0) return;
    const currentSeenAt = Number(this.#latestCallsign?.seenAtMs || 0);
    if (timestampMs >= currentSeenAt) {
      this.#latestCallsign = { callsign: normalizedCallsign, seenAtMs: timestampMs };
    }
  }

  #cleanupCallsignCache() {
    const now = Date.now();
    for (const [key, entry] of this.#callsignCache.entries()) {
      if ((now - Number(entry?.seen_at || 0)) > WATERFALL_CALLSIGN_TTL_MS) {
        this.#callsignCache.delete(key);
      }
    }
  }

  #assignCallsignsToMarkers(markers) {
    this.#cleanupCallsignCache();
    const result = new Map();
    if (!Array.isArray(markers) || !markers.length) return result;
    const pairs = [];
    const cacheEntries = Array.from(this.#callsignCache.values());
    for (const marker of markers) {
      const mFreq = Number(marker?.frequency_hz);
      const mMode = String(marker?.mode || "").toUpperCase();
      if (!Number.isFinite(mFreq) || mFreq <= 0) continue;
      for (const entry of cacheEntries) {
        const eFreq  = Number(entry?.frequency_hz);
        const eMode  = String(entry?.mode || "").toUpperCase();
        const eCall  = String(entry?.callsign || "");
        if (!eCall) continue;
        if (!Number.isFinite(eFreq) || eFreq <= 0) continue;
        if (mMode && eMode && eMode !== mMode) continue;
        const delta = Math.abs(eFreq - mFreq);
        if (delta > WATERFALL_CALLSIGN_MAX_DELTA_HZ) continue;
        pairs.push({ markerKey: String(Math.round(mFreq / 50) * 50), callsign: eCall, seenAt: Number(entry?.seen_at || 0), delta, entryKey: String(Math.round(eFreq / 50) * 50) });
      }
    }
    pairs.sort((a, b) => a.delta - b.delta || b.seenAt - a.seenAt);
    const usedMarkers   = new Set();
    const usedCallsigns = new Set();
    for (const p of pairs) {
      if (usedMarkers.has(p.markerKey) || usedCallsigns.has(p.callsign)) continue;
      usedMarkers.add(p.markerKey);
      usedCallsigns.add(p.callsign);
      result.set(p.markerKey, { callsign: p.callsign, seenAtMs: Number.isFinite(p.seenAt) ? p.seenAt : null });
    }
    return result;
  }

  updateCallsignCacheFromEvent(eventItem) {
    if (!eventItem || typeof eventItem !== "object") return;
    const eventMode = String(eventItem.mode || "").toUpperCase();
    if (this.selectedDecoderMode) {
      const selectedMode = String(this.selectedDecoderMode).toUpperCase();
      if (!modeMatchesSelectedMode(eventMode, selectedMode)) return;
    }
    const allowRawCallsignInference = eventMode !== "SSB";
    const callsign = String(
      eventItem.callsign || (allowRawCallsignInference ? extractCallsignFromRaw(eventItem.raw) : "") || ""
    ).trim().toUpperCase();
    const frequencyHz  = Number(eventItem.frequency_hz);
    const timestampMs  = eventItem.timestamp ? Date.parse(eventItem.timestamp) : Date.now();
    const seenAtMs     = Number.isFinite(timestampMs) ? timestampMs : Date.now();
    this.#cacheLatestCallsign(callsign, seenAtMs);
    this.#cacheCallsignByFrequency(callsign, frequencyHz, seenAtMs, eventMode);

    // SSB Voice Signature: confirmed SSB event with no callsign → waterfall marker
    const isVoiceSignature = /^SSB/i.test(eventMode) && !callsign;
    if (isVoiceSignature && Number.isFinite(frequencyHz) && frequencyHz > 0) {
      const bucketHz  = Math.round(frequencyHz / WATERFALL_MARKER_BUCKET_SSB_HZ) * WATERFALL_MARKER_BUCKET_SSB_HZ;
      const markerKey = `${bucketHz}_SSB_VOICE`;
      const existing  = this.#decodedMarkerCache.get(markerKey);
      const ts = Number(seenAtMs);
      if (!existing || ts >= Number(existing.seenAtMs || 0)) {
        this.#decodedMarkerCache.set(markerKey, {
          frequency_hz: frequencyHz,
          mode: "SSB_VOICE",
          snr_db: eventItem.snr_db ?? null,
          seen_at: Date.now(),
          callsign: "",
          seenAtMs: ts,
          decoded: true,
        });
      }
    }

    this.#cleanupCallsignCache();
  }

  updateCallsignCacheFromEvents(items) {
    if (!Array.isArray(items)) return;
    items.forEach((item) => this.updateCallsignCacheFromEvent(item));
  }

  // ── Draw methods ─────────────────────────────────────────────────────────

  drawSpectrum(fftDb) {
    const { spectrumCtx, spectrumCanvas } = this.#dom;
    if (!spectrumCtx || !Array.isArray(fftDb) || !fftDb.length) return;
    const sc = spectrumCanvas;
    const W  = sc.offsetWidth > 0 ? sc.offsetWidth : (sc.width || 640);
    const H  = sc.height || 80;
    if (sc.width !== W) sc.width = W;
    let minDb = Infinity, maxDb = -Infinity;
    for (let i = 0; i < fftDb.length; i++) {
      if (fftDb[i] < minDb) minDb = fftDb[i];
      if (fftDb[i] > maxDb) maxDb = fftDb[i];
    }
    const scale = maxDb - minDb || 1;
    if (!this.#specSmooth || this.#specSmooth.length !== W) {
      this.#specSmooth = new Float32Array(W);
      for (let x = 0; x < W; x++) {
        const idx = Math.min(fftDb.length - 1, Math.floor((x / (W - 1)) * (fftDb.length - 1)));
        this.#specSmooth[x] = (fftDb[idx] - minDb) / scale;
      }
    }
    for (let x = 0; x < W; x++) {
      const idx = Math.min(fftDb.length - 1, Math.floor((x / (W - 1)) * (fftDb.length - 1)));
      const v   = (fftDb[idx] - minDb) / scale;
      this.#specSmooth[x] = this.#specSmooth[x] * (1 - _SPEC_SMOOTH_ALPHA) + v * _SPEC_SMOOTH_ALPHA;
    }
    spectrumCtx.fillStyle = "#080c14";
    spectrumCtx.fillRect(0, 0, W, H);
    spectrumCtx.strokeStyle = "rgba(255,255,255,0.04)";
    spectrumCtx.lineWidth = 1;
    for (let g = 1; g <= 3; g++) {
      const y = Math.round(H * g / 4) + 0.5;
      spectrumCtx.beginPath(); spectrumCtx.moveTo(0, y); spectrumCtx.lineTo(W, y); spectrumCtx.stroke();
    }
    const grad = spectrumCtx.createLinearGradient(0, 0, 0, H);
    for (let s = 0; s <= 8; s++) {
      const [r, g, b] = colorMap(1 - s / 8);
      grad.addColorStop(s / 8, `rgba(${r},${g},${b},${Math.max(0, 0.48 - s * 0.05)})`);
    }
    spectrumCtx.beginPath();
    spectrumCtx.moveTo(0, H);
    for (let x = 0; x < W; x++) spectrumCtx.lineTo(x, H - this.#specSmooth[x] * (H - 3));
    spectrumCtx.lineTo(W - 1, H);
    spectrumCtx.closePath();
    spectrumCtx.fillStyle = grad;
    spectrumCtx.fill();
    spectrumCtx.beginPath();
    for (let x = 0; x < W; x++) {
      const y = H - this.#specSmooth[x] * (H - 3);
      x === 0 ? spectrumCtx.moveTo(x, y) : spectrumCtx.lineTo(x, y);
    }
    const [lr, lg, lb] = colorMap(0.85);
    spectrumCtx.strokeStyle = `rgba(${lr},${lg},${lb},0.88)`;
    spectrumCtx.lineWidth   = 1.5;
    spectrumCtx.stroke();
  }

  drawSpectrumIdle(message) {
    const { spectrumCtx, spectrumCanvas } = this.#dom;
    if (!spectrumCtx || !spectrumCanvas) return;
    const sc = spectrumCanvas;
    const W  = sc.offsetWidth > 0 ? sc.offsetWidth : (sc.width || 640);
    const H  = sc.height || 80;
    if (sc.width !== W) sc.width = W;
    spectrumCtx.fillStyle = "#080c14";
    spectrumCtx.fillRect(0, 0, W, H);
    spectrumCtx.save();
    spectrumCtx.font          = "13px 'Courier New', monospace";
    spectrumCtx.fillStyle     = "rgba(255,255,255,0.35)";
    spectrumCtx.textAlign     = "center";
    spectrumCtx.textBaseline  = "middle";
    spectrumCtx.fillText(message || "No live spectrum available. Check SDR device connection and scan status.", W / 2, H / 2);
    spectrumCtx.restore();
  }

  drawWaterfall(frame, viewport = null, _historyReplay = false) {
    if (!_historyReplay && frame && frame.fft_db) {
      this.#fftHistoryFrames.push(frame);
      if (this.#fftHistoryFrames.length > FFT_HISTORY_MAX) this.#fftHistoryFrames.shift();
    }
    const resolvedViewport = viewport || this.getViewport(frame);
    const fftDb = resolvedViewport.fftDb || [];
    if (this.#webglWaterfall) { this.#webglWaterfall.render(fftDb); return; }
    const canvas = this.#canvas;
    const width  = canvas.width  / window.devicePixelRatio;
    const height = canvas.height / window.devicePixelRatio;
    if (!fftDb.length) return;
    let minDb = Infinity, maxDb = -Infinity;
    for (let i = 0; i < fftDb.length; i++) {
      const v = fftDb[i];
      if (v < minDb) minDb = v;
      if (v > maxDb) maxDb = v;
    }
    const scale   = maxDb - minDb || 1;
    const rowData = this.#ctx.createImageData(Math.floor(width), 1);
    for (let x = 0; x < width; x++) {
      const idx    = Math.floor((x / width) * fftDb.length);
      const value  = (fftDb[idx] - minDb) / scale;
      const color  = colorMap(value);
      const offset = x * 4;
      rowData.data[offset]     = color[0];
      rowData.data[offset + 1] = color[1];
      rowData.data[offset + 2] = color[2];
      rowData.data[offset + 3] = 255;
    }
    this.#ctx.putImageData(rowData, 0, this.#row);
    if (!resolvedViewport.simulated && Array.isArray(frame?.peaks) && frame.peaks.length && frame.span_hz) {
      this.#ctx.save();
      this.#ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
      const span = frame.span_hz;
      frame.peaks.forEach((peak) => {
        const offset = peak.offset_hz ?? 0;
        const x = Math.round(((offset + span / 2) / span) * width);
        this.#ctx.fillRect(x, this.#row, 2, 1);
      });
      this.#ctx.restore();
    }
    this.#row = (this.#row + 1) % height;
    if (this.#row === 0) this.#ctx.clearRect(0, 0, width, height);
  }

  // ── Redraw helpers ───────────────────────────────────────────────────────

  redrawFromLastFrame() {
    if (!this.#lastFrame || !this.#lastFrame.fft_db) return;
    const viewport = this.getViewport(this.#lastFrame);
    this.drawWaterfall(this.#lastFrame, viewport, true);
    const stableMarkers = this.buildStableMarkers(this.#lastFrame);
    const rulerRange = this.resolveRulerRange(
      this.#lastFrame, viewport, stableMarkers.rangeStartHz, stableMarkers.rangeEndHz
    );
    this.renderRuler(rulerRange.startHz, rulerRange.endHz);
    const simulatedMarkers = this.buildSimulatedMarkers(
      viewport.visibleSpanHz, rulerRange.startHz, rulerRange.endHz
    );
    const modeMarkers = WATERFALL_SIMULATE_MODE_MARKERS
      ? [...stableMarkers.markers, ...simulatedMarkers]
      : stableMarkers.markers;
    this.renderModeOverlay(modeMarkers, viewport.visibleSpanHz, rulerRange.startHz, rulerRange.endHz);
  }

  redrawFromHistory() {
    if (this.#webglWaterfall) { this.redrawFromLastFrame(); return; }
    if (!this.#fftHistoryFrames.length) return;
    this.#row = 0;
    if (this.#ctx) {
      const w = this.#canvas.width  / window.devicePixelRatio;
      const h = this.#canvas.height / window.devicePixelRatio;
      this.#ctx.clearRect(0, 0, w, h);
    }
    for (const hFrame of this.#fftHistoryFrames) {
      const vp = this.getViewport(hFrame);
      this.drawWaterfall(hFrame, vp, true);
    }
    const lastFrame = this.#fftHistoryFrames[this.#fftHistoryFrames.length - 1];
    const lastVp    = this.getViewport(lastFrame);
    const stableMarkers = this.buildStableMarkers(lastFrame);
    const rulerRange = this.resolveRulerRange(
      lastFrame, lastVp, stableMarkers.rangeStartHz, stableMarkers.rangeEndHz
    );
    this.renderRuler(rulerRange.startHz, rulerRange.endHz);
    const simulatedMarkers = this.buildSimulatedMarkers(
      lastVp.visibleSpanHz, rulerRange.startHz, rulerRange.endHz
    );
    const modeMarkers = WATERFALL_SIMULATE_MODE_MARKERS
      ? [...stableMarkers.markers, ...simulatedMarkers]
      : stableMarkers.markers;
    this.renderModeOverlay(modeMarkers, lastVp.visibleSpanHz, rulerRange.startHz, rulerRange.endHz);
  }

  // ── VFO display ──────────────────────────────────────────────────────────

  #formatVFOFreq(hz) {
    const mhz = Math.floor(hz / 1_000_000);
    const khz = Math.floor((hz % 1_000_000) / 1000).toString().padStart(3, "0");
    const hz3 = (hz % 1000).toString().padStart(3, "0");
    return `${mhz}<span class="vfo-sep">.</span>${khz}<span class="vfo-sep">.</span>${hz3}`;
  }

  updateVFODisplay(startHz, endHz) {
    const vfoFreqEl = this.#dom.vfoFreqEl;
    if (!vfoFreqEl || !Number.isFinite(startHz) || !Number.isFinite(endHz)) return;
    const centre = Math.round((startHz + endHz) / 2);
    if (centre === this.#vfoDisplayHz) return;
    this.#vfoDisplayHz = centre;
    vfoFreqEl.innerHTML = this.#formatVFOFreq(centre);
    this.#cb.onVFOUpdate?.();
  }

  // ── Debug ────────────────────────────────────────────────────────────────

  debug() {
    console.group("=== waterfall callsign cache (exact-freq buckets) ===");
    if (this.#callsignCache.size === 0) {
      console.warn("  (empty)");
    } else {
      for (const [k, v] of this.#callsignCache.entries()) {
        console.log(`  ${k}: ${v.callsign}  mode=${v.mode}  freq=${v.frequency_hz}  age=${Math.round((Date.now() - v.seen_at) / 1000)}s`);
      }
    }
    console.groupEnd();
    console.group("=== waterfall decoded marker cache (one per dial-freq/mode) ===");
    if (this.#decodedMarkerCache.size === 0) {
      console.warn("  (empty — no jt9 decodes yet, or all expired)");
    } else {
      for (const [k, v] of this.#decodedMarkerCache.entries()) {
        console.log(`  ${k}: callsign=${v.callsign}  dialFreq=${v.frequency_hz} Hz  mode=${v.mode}  age=${Math.round((Date.now() - v.seen_at) / 1000)}s`);
      }
    }
    console.groupEnd();
    console.group("=== waterfall DSP marker cache ===");
    if (this.#markerCache.size === 0) {
      console.warn("  (empty — DSP quality gate has not fired yet)");
    } else {
      for (const [k, v] of this.#markerCache.entries()) {
        console.log(`  ${k}: mode=${v.mode}  freq=${v.frequency_hz}  snr=${v.snr_db}  age=${Math.round((Date.now() - v.seen_at) / 1000)}s`);
      }
    }
    console.groupEnd();
    console.log("WATERFALL_CALLSIGN_MAX_DELTA_HZ (DSP fallback) =", WATERFALL_CALLSIGN_MAX_DELTA_HZ);
    const last = window._lastSpectrumFrame || this.#lastFrame;
    if (last) {
      const built = this.buildStableMarkers(last);
      console.group(`=== built markers (${built.markers.length}) for range ${built.rangeStartHz}-${built.rangeEndHz} Hz ===`);
      for (const m of built.markers) {
        console.log(`  ${m.mode}  ${m.frequency_hz} Hz  callsign=${m.callsign || "(DSP, no callsign)"}  decoded=${!!m.decoded}`);
      }
      console.groupEnd();
    } else {
      console.warn("No spectrum frame received yet — cannot compute built markers.");
    }
  }

  // ── Private: renderer init ────────────────────────────────────────────────

  #initRenderer() {
    const canvas = this.#canvas;
    if (!canvas) return;
    this.#webglWaterfall = this.#createWebglRenderer(canvas);
    if (this.#webglWaterfall) {
      this.#renderer = "webgl";
      return;
    }
    this.#ctx      = canvas.getContext("2d");
    this.#renderer = "2d";
  }

  #createWebglRenderer(targetCanvas) {
    const gl = targetCanvas.getContext("webgl", {
      alpha: false, antialias: false, preserveDrawingBuffer: true, powerPreference: "high-performance",
    }) || targetCanvas.getContext("experimental-webgl");
    if (!gl) return null;

    const vertexSource = `
      attribute vec2 a_pos;
      attribute vec2 a_uv;
      varying vec2 v_uv;
      void main() { gl_Position = vec4(a_pos, 0.0, 1.0); v_uv = a_uv; }
    `;
    const fragmentSource = `
      precision mediump float;
      varying vec2 v_uv;
      uniform sampler2D u_tex;
      void main() { gl_FragColor = texture2D(u_tex, vec2(v_uv.x, 1.0 - v_uv.y)); }
    `;

    function compileShader(type, source) {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        const info = gl.getShaderInfoLog(shader) || "shader_compile_failed";
        gl.deleteShader(shader);
        throw new Error(info);
      }
      return shader;
    }

    let program;
    try {
      const vs = compileShader(gl.VERTEX_SHADER,   vertexSource);
      const fs = compileShader(gl.FRAGMENT_SHADER, fragmentSource);
      program  = gl.createProgram();
      gl.attachShader(program, vs); gl.attachShader(program, fs);
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(program) || "program_link_failed");
    } catch (err) { return null; }

    const vertices = new Float32Array([-1,-1,0,0, 1,-1,1,0, -1,1,0,1, 1,1,1,1]);
    const buffer   = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW);
    const aPos = gl.getAttribLocation(program, "a_pos");
    const aUv  = gl.getAttribLocation(program, "a_uv");
    gl.enableVertexAttribArray(aPos); gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 16, 0);
    gl.enableVertexAttribArray(aUv);  gl.vertexAttribPointer(aUv,  2, gl.FLOAT, false, 16, 8);

    const texture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.useProgram(program);
    gl.uniform1i(gl.getUniformLocation(program, "u_tex"), 0);

    let width = 0, height = 0, pixels = null;

    function resize(displayWidth, displayHeight) {
      width  = Math.max(2, Math.floor(displayWidth));
      height = Math.max(2, Math.floor(displayHeight));
      targetCanvas.width  = width;
      targetCanvas.height = height;
      gl.viewport(0, 0, width, height);
      pixels = new Uint8Array(width * height * 4);
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    }

    function render(fftDb) {
      if (!Array.isArray(fftDb) || !fftDb.length || !pixels) return;
      let minDb = Infinity, maxDb = -Infinity;
      for (let i = 0; i < fftDb.length; i++) {
        if (fftDb[i] < minDb) minDb = fftDb[i];
        if (fftDb[i] > maxDb) maxDb = fftDb[i];
      }
      const scale    = maxDb - minDb || 1;
      const rowBytes = width * 4;
      pixels.copyWithin(0, rowBytes);
      const rowOffset = (height - 1) * rowBytes;
      for (let x = 0; x < width; x++) {
        const idx    = Math.floor((x / width) * fftDb.length);
        const value  = (fftDb[idx] - minDb) / scale;
        const color  = colorMap(value);
        const offset = rowOffset + x * 4;
        pixels[offset] = color[0]; pixels[offset + 1] = color[1];
        pixels[offset + 2] = color[2]; pixels[offset + 3] = 255;
      }
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }

    return { resize, render };
  }

  // ── Private: event listeners ─────────────────────────────────────────────

  #initEventListeners() {
    const { waterfallExplorerToggle, waterfallZoomInput, waterfallResetViewBtn, waterfallEl } = this.#dom;

    if (waterfallExplorerToggle) {
      waterfallExplorerToggle.addEventListener("click", () => {
        this.#explorerEnabled = !this.#explorerEnabled;
        localStorage.setItem(WATERFALL_EXPLORER_KEY, this.#explorerEnabled ? "1" : "0");
        if (!this.#explorerEnabled) {
          this.#explorerZoom = 1;
          this.#explorerPan  = 0;
          localStorage.setItem(WATERFALL_EXPLORER_ZOOM_KEY, "1");
        }
        this.applyExplorerUi();
        this.redrawFromLastFrame();
      });
    }

    if (waterfallZoomInput) {
      waterfallZoomInput.addEventListener("input", () => {
        const nextZoom = Math.max(1, Math.min(16, Math.round(Number(waterfallZoomInput.value) || 1)));
        const currentCenter = this.#explorerPan + 0.5 / this.#explorerZoom;
        this.#explorerZoom  = nextZoom;
        const maxPan = Math.max(0, 1 - 1 / this.#explorerZoom);
        this.#explorerPan = Math.max(0, Math.min(maxPan, currentCenter - 0.5 / this.#explorerZoom));
        localStorage.setItem(WATERFALL_EXPLORER_ZOOM_KEY, String(this.#explorerZoom));
        this.applyExplorerUi();
        this.redrawFromHistory();
      });
    }

    if (waterfallResetViewBtn) {
      waterfallResetViewBtn.addEventListener("click", () => { this.resetExplorerView(); });
    }

    if (waterfallEl) {
      waterfallEl.addEventListener("pointerdown", (event) => {
        if (!this.#explorerEnabled) return;
        this.#dragActive   = true;
        this.#dragStartX   = event.clientX;
        this.#dragStartPan = this.#explorerPan;
        waterfallEl.classList.add("is-dragging");
      });
    }

    document.addEventListener("pointermove", (event) => {
      if (!this.#dragActive || !this.#explorerEnabled || !waterfallEl) return;
      const rect = waterfallEl.getBoundingClientRect();
      if (!rect.width) return;
      const deltaNorm = ((event.clientX - this.#dragStartX) / rect.width) * (1 / this.#explorerZoom);
      const maxPan    = Math.max(0, 1 - 1 / this.#explorerZoom);
      this.#explorerPan = Math.max(0, Math.min(maxPan, this.#dragStartPan - deltaNorm));
      if (!this.#dragRafPending) {
        this.#dragRafPending = true;
        requestAnimationFrame(() => { this.#dragRafPending = false; this.redrawFromHistory(); });
      }
    });

    document.addEventListener("pointerup", () => {
      if (!this.#dragActive) return;
      this.#dragActive = false;
      if (waterfallEl) waterfallEl.classList.remove("is-dragging");
    });

    this.#initVFOControls();
  }

  #initVFOControls() {
    const { vfoGotoInput, vfoApplyBtn } = this.#dom;
    const applyGoto = () => {
      const raw = (vfoGotoInput?.value || "").trim().replace(",", ".");
      const mhz = parseFloat(raw);
      if (isNaN(mhz) || mhz <= 0) {
        if (vfoGotoInput) {
          vfoGotoInput.style.borderColor = "rgba(180,40,40,0.8)";
          setTimeout(() => { vfoGotoInput.style.borderColor = ""; }, 700);
        }
        return;
      }
      const targetHz  = Math.round(mhz * 1_000_000);
      const fullRange = this.getFullRangeHz();
      const fullStartHz = Number(fullRange?.startHz || 0);
      const fullSpanHz  = Number(fullRange?.spanHz  || 0);
      if (!Number.isFinite(fullStartHz) || !Number.isFinite(fullSpanHz) || fullSpanHz <= 0
          || targetHz < fullStartHz || targetHz > fullStartHz + fullSpanHz) {
        this.#cb.showToast?.(`${mhz.toFixed(3)} MHz is outside the current band`);
        return;
      }
      this.gotoMhz(mhz, fullStartHz, fullSpanHz);
      if (vfoGotoInput) vfoGotoInput.value = "";
      this.#cb.showToast?.(`Centred on ${mhz.toFixed(3)} MHz`);
    };
    vfoApplyBtn?.addEventListener("click", applyGoto);
    vfoGotoInput?.addEventListener("keydown", (e) => { if (e.key === "Enter") applyGoto(); });
  }
}
