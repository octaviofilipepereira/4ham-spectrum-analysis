/*
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
- No modo FT8 o decoder funciona? 2026-02-22 16:27:19 UTC
*/

import { loadPresetsFromJson } from "./utils/presets.js";

const statusEl = document.getElementById("status");
const eventsEl = document.getElementById("events");
const eventsSearchCallsignInput = document.getElementById("eventsSearchCallsign");
const eventsSearchModeInput = document.getElementById("eventsSearchMode");
const eventsSearchGridInput = document.getElementById("eventsSearchGrid");
const eventsSearchReportInput = document.getElementById("eventsSearchReport");
const eventsPrevBtn = document.getElementById("eventsPrev");
const eventsNextBtn = document.getElementById("eventsNext");
const eventsPageInfo = document.getElementById("eventsPageInfo");
const eventsSearchResultsEl = document.getElementById("eventsSearchResults");
const copyrightYearEl = document.getElementById("copyrightYear");
const waterfallEl = document.getElementById("waterfall");
const waterfallStatus = document.getElementById("waterfallStatus");
const waterfallModeBadge = document.getElementById("waterfallModeBadge");
const waterfallFullscreenBtn = document.getElementById("waterfallFullscreenBtn");
const waterfallExplorerToggle = document.getElementById("waterfallExplorerToggle");
const waterfallZoomInput = document.getElementById("waterfallZoom");
const waterfallResetViewBtn = document.getElementById("waterfallResetViewBtn");
const waterfallModeOverlay = document.getElementById("waterfallModeOverlay");
const waterfallRuler = document.getElementById("waterfallRuler");
const canvas = document.getElementById("waterfallCanvas");
let ctx = null;
let webglWaterfall = null;
let waterfallRenderer = "2d";
const gainInput = document.getElementById("gain");
const sampleRateInput = document.getElementById("sampleRate");
const recordPathInput = document.getElementById("recordPath");
const logsEl = document.getElementById("logs");
const bandFilter = document.getElementById("bandFilter");
const modeFilter = document.getElementById("modeFilter");
const callsignFilter = document.getElementById("callsignFilter");
const startFilter = document.getElementById("startFilter");
const endFilter = document.getElementById("endFilter");
const exportCsvBtn = document.getElementById("exportCsv");
const exportJsonBtn = document.getElementById("exportJson");
const exportPngBtn = document.getElementById("exportPng");
const deviceSelect = document.getElementById("deviceSelect");
const bandSelect = document.getElementById("bandSelect");
const authUserInput = document.getElementById("authUser");
const authPassInput = document.getElementById("authPass");
const saveSettingsBtn = document.getElementById("saveSettings");
const testConfigBtn = document.getElementById("testConfig");
const refreshDevicesBtn = document.getElementById("refreshDevices");
const adminDeviceSetupBtn = document.getElementById("adminDeviceSetup");
const adminAudioAutoDetectBtn = document.getElementById("adminAudioAutoDetect");
const purgeInvalidEventsBtn = document.getElementById("purgeInvalidEvents");
const resetDefaultsBtn = document.getElementById("resetDefaults");
const resetAllConfigBtn = document.getElementById("resetAllConfig");
const showNonSdrDevicesToggle = document.getElementById("showNonSdrDevices");
const stationCallsignInput = document.getElementById("stationCallsign");
const stationOperatorInput = document.getElementById("stationOperator");
const stationLocatorInput = document.getElementById("stationLocator");
const stationQthInput = document.getElementById("stationQth");
const deviceClassSelect = document.getElementById("deviceClass");
const devicePpmInput = document.getElementById("devicePpm");
const deviceOffsetHzInput = document.getElementById("deviceOffsetHz");
const deviceGainProfileSelect = document.getElementById("deviceGainProfile");
const saveDeviceConfigBtn = document.getElementById("saveDeviceConfig");
const saveAudioConfigBtn = document.getElementById("saveAudioConfig");
const audioInputDeviceInput = document.getElementById("audioInputDevice");
const audioOutputDeviceInput = document.getElementById("audioOutputDevice");
const audioSampleRateInput = document.getElementById("audioSampleRate");
const audioRxGainInput = document.getElementById("audioRxGain");
const audioTxGainInput = document.getElementById("audioTxGain");
const quickBandButtons = Array.from(document.querySelectorAll("[data-quick-band]"));
const adminSetupStatus = document.getElementById("adminSetupStatus");

function updateAdminAudioStatus(audioProfile, options = {}) {
  if (!adminSetupStatus) {
    return;
  }
  const profile = audioProfile || {};
  const inputDevice = String(profile.input_device || "").trim();
  const outputDevice = String(profile.output_device || "").trim();
  const sampleRate = Number(profile.sample_rate || 48000);
  const sourceLabel = options.sourceLabel || "guardado";
  const methods = options.methods || "defaults";
  const hasDetectedEndpoints = Boolean(inputDevice || outputDevice);

  adminSetupStatus.classList.remove("d-none", "alert-success", "alert-warning");
  if (hasDetectedEndpoints) {
    adminSetupStatus.classList.add("alert-success");
    adminSetupStatus.textContent = `Áudio ${sourceLabel}: entrada=${inputDevice || "não definido"} | saída=${outputDevice || "não definido"} | sample rate=${sampleRate} Hz (${methods})`;
  } else {
    adminSetupStatus.classList.add("alert-warning");
    adminSetupStatus.textContent = `Áudio não detetado automaticamente: entrada/saída por definir | sample rate=${sampleRate} Hz. Configure manualmente ou execute Auto-detect Device novamente.`;
  }
}

function normalizeNumberInputValue(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function applyDeviceConfigToForm(deviceConfig) {
  const config = deviceConfig || {};
  const nextClass = String(config.device_class || "auto").trim().toLowerCase() || "auto";
  const nextPpm = normalizeNumberInputValue(config.ppm_correction, 0);
  const nextOffset = normalizeNumberInputValue(config.frequency_offset_hz, 0);
  const nextGainProfile = String(config.gain_profile || "auto").trim().toLowerCase() || "auto";

  if (deviceClassSelect) {
    const validClass = Array.from(deviceClassSelect.options || []).some((option) => option.value === nextClass)
      ? nextClass
      : "auto";
    deviceClassSelect.value = validClass;
  }

  if (devicePpmInput) {
    devicePpmInput.value = String(nextPpm);
  }

  if (deviceOffsetHzInput) {
    deviceOffsetHzInput.value = String(nextOffset);
  }

  if (deviceGainProfileSelect) {
    const validGain = Array.from(deviceGainProfileSelect.options || []).some((option) => option.value === nextGainProfile)
      ? nextGainProfile
      : "auto";
    deviceGainProfileSelect.value = validGain;
  }
}

function buildDeviceConfigPayload() {
  return {
    device_class: deviceClassSelect.value,
    ppm_correction: Number(devicePpmInput.value || 0),
    frequency_offset_hz: Number(deviceOffsetHzInput.value || 0),
    gain_profile: deviceGainProfileSelect.value,
  };
}

function buildAudioConfigPayload() {
  return {
    input_device: audioInputDeviceInput.value.trim(),
    output_device: audioOutputDeviceInput.value.trim(),
    sample_rate: Number(audioSampleRateInput.value || 48000),
    rx_gain: Number(audioRxGainInput.value || 1),
    tx_gain: Number(audioTxGainInput.value || 1),
  };
}
const bandNameInput = document.getElementById("bandName");
const bandStartInput = document.getElementById("bandStart");
const bandEndInput = document.getElementById("bandEnd");
const saveBandBtn = document.getElementById("saveBand");
const presetNameInput = document.getElementById("presetName");
const savePresetBtn = document.getElementById("savePreset");
const deletePresetBtn = document.getElementById("deletePreset");
const presetSelect = document.getElementById("presetSelect");
const exportPresetsBtn = document.getElementById("exportPresets");
const importPresetsInput = document.getElementById("importPresets");
const favoriteBandsSelect = document.getElementById("favoriteBands");
const addFavoriteBtn = document.getElementById("addFavorite");
const removeFavoriteBtn = document.getElementById("removeFavorite");
const toast = document.getElementById("toast");
const favoriteFilter = document.getElementById("favoriteFilter");
const loginUserInput = document.getElementById("loginUser");
const loginPassInput = document.getElementById("loginPass");
const loginSaveBtn = document.getElementById("loginSave");
const loginStatus = document.getElementById("loginStatus");
const wsStatus = document.getElementById("wsStatus");
const onboarding = document.getElementById("onboarding");
const onboardingTitle = document.getElementById("onboardingTitle");
const onboardingText = document.getElementById("onboardingText");
const onboardingPrev = document.getElementById("onboardingPrev");
const onboardingNext = document.getElementById("onboardingNext");
const startBtn = document.getElementById("startScan");
const prevPageBtn = document.getElementById("prevPage");
const nextPageBtn = document.getElementById("nextPage");
const qualityBar = document.getElementById("qualityBar");
const qualityLabel = document.getElementById("qualityLabel");
const summaryMatrixTable = document.getElementById("summaryMatrixTable");
const summaryMatrixCaption = document.getElementById("summaryMatrixCaption");
const eventsTotal = document.getElementById("eventsTotal");
const propagationScore = document.getElementById("propagationScore");
const propagationBands = document.getElementById("propagationBands");
const compactToggle = document.getElementById("compactToggle");
let modeStatsCache = {};
const decoderStatusEl = document.getElementById("decoderStatus");
const wsjtxUdpStatusEl = document.getElementById("wsjtxUdpStatus");
const kissStatusEl = document.getElementById("kissStatus");
const decoderLastEventEl = document.getElementById("decoderLastEvent");
const agcStatusEl = document.getElementById("agcStatus");
const ft8Toggle = document.getElementById("ft8Toggle");
const aprsToggle = document.getElementById("aprsToggle");
const cwToggle = document.getElementById("cwToggle");
const ssbToggle = document.getElementById("ssbToggle");
const saveModesBtn = document.getElementById("saveModes");
const DEVICE_AUTO_PROFILES = {
  rtl: { sample_rate: 2048000, gain: 30, ppm_correction: 0, frequency_offset_hz: 0, gain_profile: "auto" },
  hackrf: { sample_rate: 2000000, gain: 20, ppm_correction: 0, frequency_offset_hz: 0, gain_profile: "auto" },
  airspy: { sample_rate: 2500000, gain: 20, ppm_correction: 0, frequency_offset_hz: 0, gain_profile: "auto" },
  other: { sample_rate: 48000, gain: 20, ppm_correction: 0, frequency_offset_hz: 0, gain_profile: "auto" }
};
const BAND_PRESETS = {
  "160m": { start_hz: 1810000, end_hz: 2000000 },
  "80m": { start_hz: 3500000, end_hz: 3800000 },
  "40m": { start_hz: 7000000, end_hz: 7200000 },
  "20m": { start_hz: 14000000, end_hz: 14350000 },
  "17m": { start_hz: 18068000, end_hz: 18168000 },
  "15m": { start_hz: 21000000, end_hz: 21450000 },
  "12m": { start_hz: 24890000, end_hz: 24990000 },
  "10m": { start_hz: 28000000, end_hz: 29700000 },
  "2m": { start_hz: 144000000, end_hz: 146000000 },
  "70cm": { start_hz: 430000000, end_hz: 440000000 },
};
const DEFAULT_BAND_OPTIONS = [
  { name: "160m", label: "160 m" },
  { name: "80m", label: "80 m" },
  { name: "40m", label: "40 m" },
  { name: "20m", label: "20 m" },
  { name: "17m", label: "17 m" },
  { name: "15m", label: "15 m" },
  { name: "12m", label: "12 m" },
  { name: "10m", label: "10 m" },
  { name: "2m", label: "2 m" },
  { name: "70cm", label: "70 cm" },
];
const bandRangesByName = new Map(
  Object.entries(BAND_PRESETS).map(([name, range]) => [
    name,
    { start_hz: Number(range.start_hz), end_hz: Number(range.end_hz) },
  ])
);

function getScanRangeForBand(bandName) {
  const selectedBand = String(bandName || "").trim();
  const range = bandRangesByName.get(selectedBand) || bandRangesByName.get("20m");
  const startHz = Number(range?.start_hz || 0);
  const endHz = Number(range?.end_hz || 0);
  if (startHz > 0 && endHz > startHz) {
    return { start_hz: startHz, end_hz: endHz };
  }
  return { start_hz: 14000000, end_hz: 14350000 };
}

function populateBandSelectOptions(sourceBands) {
  if (!bandSelect) {
    return;
  }
  const byName = new Map();
  DEFAULT_BAND_OPTIONS.forEach((item) => {
    byName.set(item.name, item.label);
  });
  (sourceBands || []).forEach((item) => {
    const name = String(item?.name || "").trim();
    if (!name) {
      return;
    }
    if (!byName.has(name)) {
      byName.set(name, name);
    }
    const startHz = Number(item?.start_hz || 0);
    const endHz = Number(item?.end_hz || 0);
    if (startHz > 0 && endHz > startHz) {
      bandRangesByName.set(name, { start_hz: startHz, end_hz: endHz });
    }
  });

  const current = bandSelect.value;
  bandSelect.innerHTML = "";
  byName.forEach((label, name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = label;
    bandSelect.appendChild(option);
  });

  if (current && byName.has(current)) {
    bandSelect.value = current;
  } else {
    bandSelect.value = byName.has("20m") ? "20m" : (byName.keys().next().value || "");
  }

  refreshQuickBandButtons();
}

function refreshQuickBandButtons() {
  if (!bandSelect || !quickBandButtons.length) {
    return;
  }

  const availableBands = new Set(Array.from(bandSelect.options || []).map((option) => option.value));
  const activeBand = bandSelect.value;

  quickBandButtons.forEach((button) => {
    const buttonBand = String(button.dataset.quickBand || "").trim();
    const isAvailable = availableBands.has(buttonBand);
    const isActive = isAvailable && buttonBand === activeBand;
    button.disabled = !isAvailable || scanActionInFlight;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
}
const EVENTS_PANEL_PAGE_SIZE = 7;
let eventOffset = 0;
let eventsPanelPage = 0;
let latestEvents = [];
let row = 0;
let lastSpectrumFrameTs = 0;
let spectrumFallbackTimer = null;
let spectrumWs = null;
let isScanRunning = false;
let scanActionInFlight = false;
const SHOW_NON_SDR_DEVICES_KEY = "showNonSdrDevices";
let showNonSdrDevices = localStorage.getItem(SHOW_NON_SDR_DEVICES_KEY) === "1";
const WATERFALL_GENERIC_STATUS = "No live spectrum data available. Check SDR device connection and scan status.";
const WATERFALL_SIMULATE_MODE_MARKERS = true;
const WATERFALL_MARKER_TTL_MS = 12000;
const waterfallMarkerCache = new Map();
const WATERFALL_CALLSIGN_TTL_MS = 15 * 60 * 1000;
const WATERFALL_CALLSIGN_MAX_DELTA_HZ = 25000;
const waterfallCallsignCache = new Map();
let waterfallLatestCallsign = { callsign: "", seenAtMs: null };
let waterfallHoverTooltip = null;
const WATERFALL_EXPLORER_KEY = "waterfallExplorerEnabled";
const WATERFALL_EXPLORER_ZOOM_KEY = "waterfallExplorerZoom";
const WATERFALL_SEGMENT_COUNT = 12;
let waterfallExplorerEnabled = localStorage.getItem(WATERFALL_EXPLORER_KEY) !== "0";
let waterfallExplorerZoom = Number(localStorage.getItem(WATERFALL_EXPLORER_ZOOM_KEY) || 1);
if (!Number.isFinite(waterfallExplorerZoom)) {
  waterfallExplorerZoom = 1;
}
waterfallExplorerZoom = Math.max(1, Math.min(16, Math.round(waterfallExplorerZoom)));
let waterfallExplorerPan = 0;
let waterfallDragActive = false;
let waterfallDragStartX = 0;
let waterfallDragStartPan = 0;
let lastSpectrumFrame = null;

if (showNonSdrDevicesToggle) {
  showNonSdrDevicesToggle.checked = showNonSdrDevices;
}

function updateWaterfallModeBadge() {
  if (!waterfallModeBadge) {
    return;
  }
  waterfallModeBadge.textContent = "LIVE";
  waterfallModeBadge.classList.remove("is-fake");
  waterfallModeBadge.classList.add("is-live");
}

function setWaterfallGenericStatus(message = WATERFALL_GENERIC_STATUS) {
  if (!waterfallStatus) {
    return;
  }
  waterfallStatus.textContent = message;
  waterfallStatus.classList.add("is-generic");
  if (waterfallRuler) {
    waterfallRuler.innerHTML = "";
  }
  if (waterfallModeOverlay) {
    waterfallModeOverlay.innerHTML = "";
  }
}

function clearWaterfallGenericStatus() {
  if (!waterfallStatus) {
    return;
  }
  waterfallStatus.classList.remove("is-generic");
}

function applyWaterfallExplorerUi() {
  if (waterfallExplorerToggle) {
    waterfallExplorerToggle.textContent = `Explorer SIM: ${waterfallExplorerEnabled ? "ON" : "OFF"}`;
  }
  if (waterfallZoomInput) {
    waterfallZoomInput.value = String(waterfallExplorerZoom);
    waterfallZoomInput.disabled = !waterfallExplorerEnabled;
  }
  if (waterfallResetViewBtn) {
    waterfallResetViewBtn.disabled = !waterfallExplorerEnabled;
  }
  if (waterfallEl) {
    waterfallEl.classList.toggle("is-draggable", waterfallExplorerEnabled);
    waterfallEl.classList.remove("is-dragging");
  }
}

function buildSegmentedSpectrumSimulation(frame) {
  const base = Array.isArray(frame?.fft_db) ? frame.fft_db : [];
  if (!base.length) {
    return [];
  }
  const now = Date.now() / 1000;
  const bins = base.length;
  const stitched = [];
  for (let segmentIndex = 0; segmentIndex < WATERFALL_SEGMENT_COUNT; segmentIndex += 1) {
    const shift = Math.floor(((segmentIndex * 0.67) % 1) * bins);
    const gain = 0.9 + 0.25 * Math.sin(now * 0.2 + segmentIndex * 0.6);
    for (let idx = 0; idx < bins; idx += 1) {
      const source = base[(idx + shift) % bins];
      const ripple = Math.sin((idx / bins) * Math.PI * 6 + segmentIndex + now * 0.45) * 2.2;
      stitched.push((source * gain) + ripple);
    }
  }
  return stitched;
}

function getWaterfallViewport(frame) {
  const base = Array.isArray(frame?.fft_db) ? frame.fft_db : [];
  const centerHz = Number(frame?.center_hz || 0);
  const spanHz = Number(frame?.span_hz || 0);
  const scanStartHz = Number(frame?.scan_start_hz || 0);
  const scanEndHz = Number(frame?.scan_end_hz || 0);
  const hasScanRange = Number.isFinite(scanStartHz)
    && Number.isFinite(scanEndHz)
    && scanStartHz > 0
    && scanEndHz > scanStartHz;
  if (!base.length || spanHz <= 0) {
    return {
      fftDb: base,
      startHz: centerHz - (spanHz / 2),
      endHz: centerHz + (spanHz / 2),
      visibleSpanHz: spanHz,
      simulated: false
    };
  }
  if (!waterfallExplorerEnabled) {
    return {
      fftDb: base,
      startHz: centerHz - (spanHz / 2),
      endHz: centerHz + (spanHz / 2),
      visibleSpanHz: spanHz,
      simulated: false
    };
  }

  const stitched = buildSegmentedSpectrumSimulation(frame);
  const zoom = Math.max(1, waterfallExplorerZoom);
  const totalBins = stitched.length;
  const visibleBins = Math.max(256, Math.floor(totalBins / zoom));
  const maxPan = Math.max(0, 1 - (1 / zoom));
  waterfallExplorerPan = Math.max(0, Math.min(maxPan, waterfallExplorerPan));
  const startBin = Math.max(0, Math.min(totalBins - visibleBins, Math.round(waterfallExplorerPan * totalBins)));
  const fftDb = stitched.slice(startBin, startBin + visibleBins);

  const fullSpanHz = hasScanRange ? (scanEndHz - scanStartHz) : (spanHz * WATERFALL_SEGMENT_COUNT);
  const visibleSpanHz = fullSpanHz / zoom;
  const fullStartHz = hasScanRange ? scanStartHz : (centerHz - (fullSpanHz / 2));
  const startHz = fullStartHz + (waterfallExplorerPan * fullSpanHz);
  const endHz = startHz + visibleSpanHz;

  return {
    fftDb,
    startHz,
    endHz,
    visibleSpanHz,
    simulated: true
  };
}

function clearWaterfallFrame() {
  row = 0;
  if (webglWaterfall) {
    resizeCanvas();
    return;
  }
  if (!ctx) {
    ctx = canvas.getContext("2d");
  }
  if (!ctx) {
    return;
  }
  const width = canvas.width / window.devicePixelRatio;
  const height = canvas.height / window.devicePixelRatio;
  ctx.clearRect(0, 0, width, height);
}

function normalizeModeLabel(mode) {
  const text = String(mode || "").trim().toUpperCase();
  return text || "SIG";
}

function formatRulerFrequencyLabel(frequencyHz) {
  const mhz = Number(frequencyHz) / 1_000_000;
  if (!Number.isFinite(mhz)) {
    return "-";
  }
  return `${mhz.toFixed(3)} MHz`;
}

function formatLastSeenTime(seenAtMs) {
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

function ensureWaterfallHoverTooltip() {
  if (waterfallHoverTooltip || !waterfallEl) {
    return waterfallHoverTooltip;
  }
  const tooltip = document.createElement("div");
  tooltip.className = "waterfall-hover-tooltip";
  tooltip.setAttribute("role", "tooltip");
  tooltip.classList.add("is-hidden");
  waterfallEl.appendChild(tooltip);
  waterfallHoverTooltip = tooltip;
  return waterfallHoverTooltip;
}

function hideWaterfallHoverTooltip() {
  const tooltip = ensureWaterfallHoverTooltip();
  if (!tooltip) {
    return;
  }
  tooltip.classList.add("is-hidden");
}

function showWaterfallHoverTooltip(text, clientX, clientY) {
  const tooltip = ensureWaterfallHoverTooltip();
  if (!tooltip || !text) {
    return;
  }
  tooltip.textContent = text;
  const rect = waterfallEl.getBoundingClientRect();
  const x = Math.max(10, Math.min(rect.width - 10, clientX - rect.left));
  const y = Math.max(10, Math.min(rect.height - 10, clientY - rect.top));
  tooltip.style.left = `${x}px`;
  tooltip.style.top = `${y}px`;
  tooltip.classList.remove("is-hidden");
}

function computeRulerStepHz(spanHz, rulerWidthPx = 0) {
  const span = Number(spanHz);
  if (!Number.isFinite(span) || span <= 0) {
    return 100_000;
  }

  const widthPx = Number.isFinite(rulerWidthPx) && rulerWidthPx > 0 ? rulerWidthPx : 960;
  const targetTicks = Math.max(4, Math.min(16, Math.round(widthPx / 110)));
  const rawStepHz = span / targetTicks;
  if (!Number.isFinite(rawStepHz) || rawStepHz <= 0) {
    return 100_000;
  }

  const magnitude = 10 ** Math.floor(Math.log10(rawStepHz));
  const normalized = rawStepHz / magnitude;
  let niceFactor = 10;
  if (normalized <= 1) {
    niceFactor = 1;
  } else if (normalized <= 2) {
    niceFactor = 2;
  } else if (normalized <= 5) {
    niceFactor = 5;
  }

  const stepHz = niceFactor * magnitude;
  return Math.max(1_000, Math.round(stepHz));
}

function renderWaterfallRuler(startHz, endHz) {
  if (!waterfallRuler) {
    return;
  }
  const start = Number(startHz);
  const end = Number(endHz);
  const span = end - start;
  if (!Number.isFinite(start) || !Number.isFinite(end) || span <= 0) {
    waterfallRuler.innerHTML = "";
    return;
  }

  const stepHz = computeRulerStepHz(span, waterfallRuler.clientWidth);
  const selectedBandRange = getScanRangeForBand(bandSelect?.value || "20m");
  const gridOriginHz = Number(selectedBandRange?.start_hz || start);
  const firstTick = gridOriginHz + (Math.ceil((start - gridOriginHz) / stepHz) * stepHz);
  const maxTicks = 500;
  let count = 0;
  waterfallRuler.innerHTML = "";

  for (let tickHz = firstTick; tickHz <= end && count < maxTicks; tickHz += stepHz) {
    const normalized = (tickHz - start) / span;
    if (normalized < 0 || normalized > 1) {
      continue;
    }
    const left = `${(normalized * 100).toFixed(2)}%`;

    const tick = document.createElement("span");
    tick.className = "waterfall-ruler__tick";
    tick.style.left = left;

    const label = document.createElement("span");
    label.className = "waterfall-ruler__label";
    label.style.left = left;
    label.textContent = formatRulerFrequencyLabel(tickHz);

    waterfallRuler.appendChild(tick);
    waterfallRuler.appendChild(label);
    count += 1;
  }
}

function resolveWaterfallRulerRange(frame, viewport, stableRangeStartHz = null, stableRangeEndHz = null) {
  const isValidRange = (startValue, endValue) => {
    const start = Number(startValue);
    const end = Number(endValue);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
      return false;
    }
    const center = (start + end) / 2;
    return center > 1_000_000;
  };

  if (isValidRange(stableRangeStartHz, stableRangeEndHz)) {
    if (Boolean(viewport?.simulated) && isValidRange(viewport?.startHz, viewport?.endHz)) {
      return { startHz: Number(viewport.startHz), endHz: Number(viewport.endHz) };
    }
    return { startHz: Number(stableRangeStartHz), endHz: Number(stableRangeEndHz) };
  }
  if (isValidRange(frame?.scan_start_hz, frame?.scan_end_hz)) {
    return { startHz: Number(frame.scan_start_hz), endHz: Number(frame.scan_end_hz) };
  }
  if (isValidRange(viewport?.startHz, viewport?.endHz)) {
    return { startHz: Number(viewport.startHz), endHz: Number(viewport.endHz) };
  }
  const bandRange = getScanRangeForBand(bandSelect?.value || "20m");
  return {
    startHz: Number(bandRange.start_hz),
    endHz: Number(bandRange.end_hz)
  };
}

function buildStableWaterfallMarkers(frame) {
  const scanStartHz = Number(frame?.scan_start_hz || 0);
  const scanEndHz = Number(frame?.scan_end_hz || 0);
  const hasScanRange = Number.isFinite(scanStartHz)
    && Number.isFinite(scanEndHz)
    && scanStartHz > 0
    && scanEndHz > scanStartHz;
  const defaultStartHz = Number(frame?.center_hz || 0) - (Number(frame?.span_hz || 0) / 2);
  const defaultEndHz = Number(frame?.center_hz || 0) + (Number(frame?.span_hz || 0) / 2);
  const rangeStartHz = hasScanRange ? scanStartHz : defaultStartHz;
  const rangeEndHz = hasScanRange ? scanEndHz : defaultEndHz;
  const now = Date.now();

  if (Array.isArray(frame?.mode_markers)) {
    frame.mode_markers.forEach((marker) => {
      const markerMode = normalizeModeLabel(marker?.mode);
      if (markerMode === "UNKNOWN" || markerMode === "SIG") {
        return;
      }
      const markerFreq = Number(marker?.frequency_hz);
      const markerOffset = Number(marker?.offset_hz ?? 0);
      const inferredFreq = Number(frame?.center_hz || 0) + markerOffset;
      const frequencyHz = Number.isFinite(markerFreq) && markerFreq > 0 ? markerFreq : inferredFreq;
      if (!Number.isFinite(frequencyHz) || frequencyHz <= 0) {
        return;
      }
      if (frequencyHz < rangeStartHz || frequencyHz > rangeEndHz) {
        return;
      }
      const key = `${Math.round(frequencyHz / 50) * 50}`;
      waterfallMarkerCache.set(key, {
        frequency_hz: frequencyHz,
        mode: markerMode,
        snr_db: Number(marker?.snr_db),
        seen_at: now
      });
    });
  }

  for (const [key, marker] of waterfallMarkerCache.entries()) {
    if ((now - Number(marker?.seen_at || 0)) > WATERFALL_MARKER_TTL_MS) {
      waterfallMarkerCache.delete(key);
    }
  }

  const markers = Array.from(waterfallMarkerCache.values())
    .filter((marker) => {
      const frequencyHz = Number(marker?.frequency_hz);
      return Number.isFinite(frequencyHz)
        && frequencyHz >= rangeStartHz
        && frequencyHz <= rangeEndHz;
    })
    .sort((left, right) => Number(left.frequency_hz) - Number(right.frequency_hz));

  return {
    markers,
    rangeStartHz,
    rangeEndHz
  };
}

function renderWaterfallModeOverlay(modeMarkers, spanHz, rangeStartHz = null, rangeEndHz = null) {
  if (!waterfallModeOverlay) {
    return;
  }
  const span = Number(spanHz || 0);
  if (!Array.isArray(modeMarkers) || !modeMarkers.length || span <= 0) {
    waterfallModeOverlay.innerHTML = "";
    hideWaterfallHoverTooltip();
    return;
  }

  waterfallModeOverlay.innerHTML = "";
  hideWaterfallHoverTooltip();
  const sortedMarkers = modeMarkers
    .slice()
    .sort((left, right) => Number(left?.offset_hz || 0) - Number(right?.offset_hz || 0));
  const lanes = [[], [], []];

  const hasRange = Number.isFinite(rangeStartHz)
    && Number.isFinite(rangeEndHz)
    && Number(rangeEndHz) > Number(rangeStartHz);
  const safeRangeStartHz = hasRange ? Number(rangeStartHz) : null;
  const safeRangeEndHz = hasRange ? Number(rangeEndHz) : null;

  sortedMarkers.forEach((marker) => {
    const offsetHz = Number(marker?.offset_hz ?? 0);
    const markerFreq = Number(marker?.frequency_hz);
    let normalized = 0.5;
    if (hasRange && Number.isFinite(markerFreq)) {
      normalized = (markerFreq - safeRangeStartHz) / (safeRangeEndHz - safeRangeStartHz);
    } else {
      normalized = (offsetHz + span / 2) / span;
    }
    normalized = Math.max(0, Math.min(1, normalized));
    let laneIndex = 0;
    const minDistance = 0.06;
    for (let idx = 0; idx < lanes.length; idx += 1) {
      const lane = lanes[idx];
      const tooClose = lane.some((existingPos) => Math.abs(existingPos - normalized) < minDistance);
      if (!tooClose) {
        laneIndex = idx;
        break;
      }
    }
    lanes[laneIndex].push(normalized);

    const label = document.createElement("span");
    label.className = "waterfall-mode-label";
    label.style.left = `${(normalized * 100).toFixed(2)}%`;
    label.style.setProperty("--lane-top", `${laneIndex * 22}px`);
    label.textContent = normalizeModeLabel(marker?.mode);
    const snr = Number(marker?.snr_db);
    const callsignMatch = findLatestCallsignForFrequency(markerFreq);
    const markerCallsign = callsignMatch?.callsign || "";
    const markerSeenAtText = formatLastSeenTime(callsignMatch?.seenAtMs);
    const freqText = Number.isFinite(markerFreq) && markerFreq > 0
      ? ` | ${(markerFreq / 1_000_000).toFixed(3)} MHz`
      : "";
    const callsignText = ` | callsign ${markerCallsign || "-"}`;
    const seenAtText = ` | last ${markerSeenAtText}`;
    const tooltipText = Number.isFinite(snr)
      ? `${label.textContent}${freqText}${callsignText}${seenAtText} | ${snr.toFixed(1)} dB`
      : `${label.textContent}${freqText}${callsignText}${seenAtText}`;
    label.title = tooltipText;
    label.setAttribute("aria-label", tooltipText);
    label.addEventListener("mouseenter", (event) => {
      showWaterfallHoverTooltip(tooltipText, event.clientX, event.clientY);
    });
    label.addEventListener("mousemove", (event) => {
      showWaterfallHoverTooltip(tooltipText, event.clientX, event.clientY);
    });
    label.addEventListener("mouseleave", () => {
      hideWaterfallHoverTooltip();
    });
    waterfallModeOverlay.appendChild(label);
  });
}

function cacheCallsignByFrequency(callsign, frequencyHz, seenAtMs = Date.now()) {
  const normalizedCallsign = String(callsign || "").trim().toUpperCase();
  const numericFrequency = Number(frequencyHz);
  if (!normalizedCallsign || !isValidCallsign(normalizedCallsign)) {
    return;
  }
  if (!Number.isFinite(numericFrequency) || numericFrequency <= 0) {
    return;
  }
  const bucketHz = Math.round(numericFrequency / 50) * 50;
  waterfallCallsignCache.set(String(bucketHz), {
    callsign: normalizedCallsign,
    frequency_hz: numericFrequency,
    seen_at: seenAtMs
  });
}

function cacheLatestCallsign(callsign, seenAtMs = Date.now()) {
  const normalizedCallsign = String(callsign || "").trim().toUpperCase();
  const timestampMs = Number(seenAtMs);
  if (!normalizedCallsign || !isValidCallsign(normalizedCallsign)) {
    return;
  }
  if (!Number.isFinite(timestampMs) || timestampMs <= 0) {
    return;
  }
  const currentSeenAt = Number(waterfallLatestCallsign?.seenAtMs || 0);
  if (timestampMs >= currentSeenAt) {
    waterfallLatestCallsign = { callsign: normalizedCallsign, seenAtMs: timestampMs };
  }
}

function cleanupWaterfallCallsignCache() {
  const now = Date.now();
  for (const [key, entry] of waterfallCallsignCache.entries()) {
    if ((now - Number(entry?.seen_at || 0)) > WATERFALL_CALLSIGN_TTL_MS) {
      waterfallCallsignCache.delete(key);
    }
  }
}

function updateCallsignCacheFromEvent(eventItem) {
  if (!eventItem || typeof eventItem !== "object") {
    return;
  }
  const callsign = String(eventItem.callsign || extractCallsignFromRaw(eventItem.raw) || "").trim().toUpperCase();
  const frequencyHz = Number(eventItem.frequency_hz);
  const timestampMs = eventItem.timestamp ? Date.parse(eventItem.timestamp) : Date.now();
  const seenAtMs = Number.isFinite(timestampMs) ? timestampMs : Date.now();
  cacheLatestCallsign(callsign, seenAtMs);
  cacheCallsignByFrequency(callsign, frequencyHz, seenAtMs);
  cleanupWaterfallCallsignCache();
}

function updateCallsignCacheFromEvents(items) {
  if (!Array.isArray(items)) {
    return;
  }
  items.forEach((eventItem) => updateCallsignCacheFromEvent(eventItem));
}

function findLatestCallsignForFrequency(frequencyHz) {
  const targetFrequency = Number(frequencyHz);
  cleanupWaterfallCallsignCache();

  let bestCallsign = "";
  let bestDeltaHz = Infinity;
  let bestSeenAt = -Infinity;
  let latestCallsign = "";
  let latestSeenAt = -Infinity;

  for (const entry of waterfallCallsignCache.values()) {
    const entryFrequency = Number(entry?.frequency_hz);
    if (!Number.isFinite(entryFrequency) || entryFrequency <= 0) {
      continue;
    }
    const seenAt = Number(entry?.seen_at || 0);
    const callsign = String(entry?.callsign || "");
    if (callsign && seenAt > latestSeenAt) {
      latestSeenAt = seenAt;
      latestCallsign = callsign;
    }
    if (!Number.isFinite(targetFrequency) || targetFrequency <= 0) {
      continue;
    }
    const deltaHz = Math.abs(entryFrequency - targetFrequency);
    if (deltaHz > WATERFALL_CALLSIGN_MAX_DELTA_HZ) {
      continue;
    }
    const isBetter = deltaHz < bestDeltaHz || (deltaHz === bestDeltaHz && seenAt > bestSeenAt);
    if (!isBetter) {
      continue;
    }
    bestDeltaHz = deltaHz;
    bestSeenAt = seenAt;
    bestCallsign = callsign;
  }

  if (bestCallsign) {
    return { callsign: bestCallsign, seenAtMs: Number.isFinite(bestSeenAt) ? bestSeenAt : null };
  }
  if (latestCallsign) {
    return {
      callsign: latestCallsign,
      seenAtMs: Number.isFinite(latestSeenAt) && latestSeenAt > 0 ? latestSeenAt : null,
    };
  }
  return {
    callsign: String(waterfallLatestCallsign?.callsign || ""),
    seenAtMs: Number(waterfallLatestCallsign?.seenAtMs || 0) || null,
  };
}

function buildSimulatedModeMarkers(spanHz, rangeStartHz = null, rangeEndHz = null) {
  if (!WATERFALL_SIMULATE_MODE_MARKERS) {
    return [];
  }
  const nextSpanHz = Number(spanHz || 0);
  if (nextSpanHz <= 0) {
    return [];
  }
  const hasRange = Number.isFinite(rangeStartHz)
    && Number.isFinite(rangeEndHz)
    && Number(rangeEndHz) > Number(rangeStartHz);
  const startHz = hasRange ? Number(rangeStartHz) : -nextSpanHz / 2;
  const endHz = hasRange ? Number(rangeEndHz) : nextSpanHz / 2;
  const spanForPlacementHz = endHz - startHz;

  const buildModeSet = (mode, count, snrBase, segmentStartRatio, segmentEndRatio) => {
    const items = [];
    const modeSpanRatio = Math.max(0.01, segmentEndRatio - segmentStartRatio);
    for (let index = 0; index < count; index += 1) {
      const ratio = segmentStartRatio + (((index + 0.5) / count) * modeSpanRatio);
      const frequencyHz = startHz + (ratio * spanForPlacementHz);
      const centeredOffsetHz = frequencyHz - (startHz + spanForPlacementHz / 2);
      items.push({
        mode,
        offset_hz: centeredOffsetHz,
        frequency_hz: hasRange ? frequencyHz : undefined,
        snr_db: snrBase + ((index % 5) * 0.8)
      });
    }
    return items;
  };

  return [
    ...buildModeSet("FT8", 10, 8.0, 0.0, 0.33),
    ...buildModeSet("CW", 20, 10.0, 0.33, 0.66),
    ...buildModeSet("SSB", 30, 12.0, 0.66, 1.0)
  ];
}

function updateFullscreenButtonState() {
  if (!waterfallFullscreenBtn) {
    return;
  }
  const isFullscreen = Boolean(document.fullscreenElement);
  waterfallFullscreenBtn.textContent = isFullscreen ? "Exit fullscreen" : "Fullscreen";
}

if (copyrightYearEl) {
  copyrightYearEl.textContent = String(new Date().getFullYear());
}

updateWaterfallModeBadge();
updateFullscreenButtonState();
applyWaterfallExplorerUi();

function logLine(text) {
  const current = logsEl.textContent === "No logs yet." ? "" : logsEl.textContent;
  logsEl.textContent = `${new Date().toISOString()} ${text}\n${current}`.trim();
}

function renderToast(message, isError = false) {
  if (!toast) {
    return;
  }

  const MAX_TOAST_NOTICES = 5;
  while (toast.childElementCount >= MAX_TOAST_NOTICES) {
    const oldest = toast.firstElementChild;
    if (!oldest) {
      break;
    }
    oldest.remove();
  }

  const noticeEl = document.createElement("div");
  noticeEl.className = "toast-notice";
  if (isError) {
    noticeEl.classList.add("error");
  }

  const messageEl = document.createElement("span");
  messageEl.className = "toast__message";
  messageEl.textContent = message;

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "toast__close";
  closeBtn.textContent = "×";
  closeBtn.setAttribute("aria-label", "Close notification");
  closeBtn.addEventListener("click", () => {
    noticeEl.remove();
  });

  noticeEl.appendChild(messageEl);
  noticeEl.appendChild(closeBtn);
  toast.appendChild(noticeEl);
}

function showToast(message) {
  renderToast(message, false);
}

function showToastError(message) {
  renderToast(message, true);
  logLine(message);
}

function isValidCallsign(value) {
  const text = String(value || "").trim().toUpperCase();
  if (!text) {
    return true;
  }
  return /^[A-Z0-9]{1,3}[0-9][A-Z0-9]{1,4}(\/[A-Z0-9]{1,4})?$/.test(text);
}

function extractCallsignFromRaw(value) {
  const text = String(value || "").toUpperCase();
  if (!text) {
    return "";
  }
  const match = text.match(/\b[A-Z0-9]{1,3}[0-9][A-Z0-9]{1,4}(?:\/[A-Z0-9]{1,4})?\b/);
  return match ? match[0] : "";
}

function isValidLocator(value) {
  const text = String(value || "").trim().toUpperCase();
  if (!text) {
    return true;
  }
  return /^[A-R]{2}[0-9]{2}([A-X]{2})?$/.test(text);
}

function loadPresets() {
  const data = JSON.parse(localStorage.getItem("presets") || "[]");
  presetSelect.innerHTML = "";
  if (!data.length) {
    const emptyOption = document.createElement("option");
    emptyOption.value = "";
    emptyOption.textContent = "No presets saved";
    emptyOption.selected = true;
    presetSelect.appendChild(emptyOption);
    updatePresetActionsState();
    return;
  }

  data.forEach((preset, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = preset.name;
    option.dataset.payload = JSON.stringify(preset);
    presetSelect.appendChild(option);
  });
  updatePresetActionsState();
}

function updatePresetActionsState() {
  const selectedIndex = Number(presetSelect.value);
  const hasValidSelection = Number.isInteger(selectedIndex) && selectedIndex >= 0;
  deletePresetBtn.disabled = !hasValidSelection;
}

function persistPresets(text) {
  const parsed = loadPresetsFromJson(text);
  localStorage.setItem("presets", JSON.stringify(parsed));
  loadPresets();
}

function exportPresets() {
  const data = localStorage.getItem("presets") || "[]";
  const blob = new Blob([data], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "presets.json";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  logLine("Presets exported");
  showToast("Presets exported");
}

function savePreset() {
  const data = JSON.parse(localStorage.getItem("presets") || "[]");
  const preset = {
    name: presetNameInput.value || `Preset ${data.length + 1}`,
    band: bandSelect.value,
    gain: Number(gainInput.value),
    sample_rate: Number(sampleRateInput.value),
    record_path: recordPathInput.value || null
  };
  data.push(preset);
  localStorage.setItem("presets", JSON.stringify(data));
  loadPresets();
  presetSelect.value = String(data.length - 1);
  updatePresetActionsState();
  logLine("Preset saved");
}

function deletePreset() {
  const selectedIndex = Number(presetSelect.value);
  if (!Number.isInteger(selectedIndex) || selectedIndex < 0) {
    showToast("Select a preset to delete");
    return;
  }

  const data = JSON.parse(localStorage.getItem("presets") || "[]");
  if (selectedIndex >= data.length) {
    showToast("Preset not found");
    loadPresets();
    return;
  }

  const selected = data[selectedIndex];
  const confirmed = window.confirm(`Delete preset \"${selected.name}\"?`);
  if (!confirmed) {
    return;
  }

  data.splice(selectedIndex, 1);
  localStorage.setItem("presets", JSON.stringify(data));
  loadPresets();
  showToast("Preset deleted");
  logLine("Preset deleted");
}

savePresetBtn.addEventListener("click", savePreset);
deletePresetBtn.addEventListener("click", deletePreset);
exportPresetsBtn.addEventListener("click", exportPresets);
importPresetsInput.addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) {
    return;
  }
  const text = await file.text();
  try {
    persistPresets(text);
    showToast("Presets imported");
  } catch (err) {
    showToast("Failed to import presets");
  }
});
presetSelect.addEventListener("change", () => {
  updatePresetActionsState();
  const data = JSON.parse(localStorage.getItem("presets") || "[]");
  const selectedIndex = Number(presetSelect.value);
  const selected = Number.isInteger(selectedIndex) ? data[selectedIndex] : null;
  if (!selected) {
    showToast("No preset selected");
    return;
  }
  bandSelect.value = selected.band;
  gainInput.value = selected.gain;
  sampleRateInput.value = selected.sample_rate;
  recordPathInput.value = selected.record_path || "";
  logLine("Preset applied");
});

function loadFavorites() {
  const data = JSON.parse(localStorage.getItem("favoriteBands") || "[]");
  const currentSelection = favoriteBandsSelect.value;
  favoriteBandsSelect.innerHTML = "";
  favoriteFilter.innerHTML = "";

  const allFavoritesOption = document.createElement("option");
  allFavoritesOption.value = "";
  allFavoritesOption.textContent = "All";
  favoriteFilter.appendChild(allFavoritesOption);

  if (!data.length) {
    const emptyOption = document.createElement("option");
    emptyOption.value = "";
    emptyOption.textContent = "No favorite bands";
    emptyOption.selected = true;
    favoriteBandsSelect.appendChild(emptyOption);
    updateFavoriteActionsState();
    return;
  }

  data.forEach((band) => {
    const option = document.createElement("option");
    option.value = band;
    option.textContent = band;
    favoriteBandsSelect.appendChild(option);
    const filterOption = document.createElement("option");
    filterOption.value = band;
    filterOption.textContent = band;
    favoriteFilter.appendChild(filterOption);
  });

  if (currentSelection && data.includes(currentSelection)) {
    favoriteBandsSelect.value = currentSelection;
  }

  updateFavoriteActionsState();
}

function updateFavoriteActionsState() {
  const hasValidSelection = Boolean(favoriteBandsSelect.value);
  removeFavoriteBtn.disabled = !hasValidSelection;
}

addFavoriteBtn.addEventListener("click", () => {
  const selectedBand = String(bandNameInput?.value || bandSelect.value || "").trim();
  if (!selectedBand) {
    showToast("Select a band first");
    return;
  }

  const data = JSON.parse(localStorage.getItem("favoriteBands") || "[]");
  if (data.includes(selectedBand)) {
    showToast("Band is already a favorite");
    return;
  }

  data.push(selectedBand);
  localStorage.setItem("favoriteBands", JSON.stringify(data));
  loadFavorites();
  favoriteBandsSelect.value = selectedBand;
  updateFavoriteActionsState();
  showToast("Favorite added");
  logLine("Favorite added");
  syncFavorites();
});

removeFavoriteBtn.addEventListener("click", () => {
  const selectedFavorite = String(favoriteBandsSelect.value || "").trim();
  if (!selectedFavorite) {
    showToast("No favorite selected");
    return;
  }

  const data = JSON.parse(localStorage.getItem("favoriteBands") || "[]");
  if (!data.includes(selectedFavorite)) {
    showToast("Favorite not found");
    loadFavorites();
    return;
  }

  const filtered = data.filter((band) => band !== selectedFavorite);
  localStorage.setItem("favoriteBands", JSON.stringify(filtered));
  loadFavorites();
  showToast("Favorite removed");
  logLine("Favorite removed");
  syncFavorites();
});

favoriteBandsSelect.addEventListener("change", () => {
  updateFavoriteActionsState();
});

favoriteFilter.addEventListener("change", () => {
  if (favoriteFilter.value) {
    bandFilter.value = favoriteFilter.value;
    fetchEvents();
  }
});

async function syncFavorites() {
  const data = JSON.parse(localStorage.getItem("favoriteBands") || "[]");
  await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeader() },
    body: JSON.stringify({ favorites: data })
  });
}

function getAuthHeader() {
  const user = localStorage.getItem("authUser");
  const pass = localStorage.getItem("authPass");
  if (!user || !pass) {
    return {};
  }
  const token = btoa(`${user}:${pass}`);
  return { Authorization: `Basic ${token}` };
}

function updateLoginStatus() {
  const user = localStorage.getItem("authUser");
  loginStatus.textContent = user ? `Auth: ${user}` : "Auth: guest";
}

function updateQuality(minDb, maxDb) {
  if (minDb === "?" || maxDb === "?") {
    return;
  }
  const snr = Math.max(0, Number(maxDb) - Number(minDb));
  const pct = Math.min(100, Math.round((snr / 30) * 100));
  qualityBar.style.setProperty("--quality", `${pct}%`);
  qualityLabel.textContent = `SNR: ${snr.toFixed(1)} dB`;
}

function wsUrl(path) {
  const user = localStorage.getItem("authUser");
  const pass = localStorage.getItem("authPass");
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  if (user && pass) {
    return `${protocol}://${encodeURIComponent(user)}:${encodeURIComponent(pass)}@${window.location.host}${path}`;
  }
  return `${protocol}://${window.location.host}${path}`;
}

function createWebglWaterfallRenderer(targetCanvas) {
  const gl = targetCanvas.getContext("webgl", {
    alpha: false,
    antialias: false,
    preserveDrawingBuffer: true,
    powerPreference: "high-performance"
  }) || targetCanvas.getContext("experimental-webgl");

  if (!gl) {
    return null;
  }

  const vertexSource = `
    attribute vec2 a_pos;
    attribute vec2 a_uv;
    varying vec2 v_uv;
    void main() {
      gl_Position = vec4(a_pos, 0.0, 1.0);
      v_uv = a_uv;
    }
  `;

  const fragmentSource = `
    precision mediump float;
    varying vec2 v_uv;
    uniform sampler2D u_tex;
    void main() {
      gl_FragColor = texture2D(u_tex, vec2(v_uv.x, 1.0 - v_uv.y));
    }
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
    const vertexShader = compileShader(gl.VERTEX_SHADER, vertexSource);
    const fragmentShader = compileShader(gl.FRAGMENT_SHADER, fragmentSource);
    program = gl.createProgram();
    gl.attachShader(program, vertexShader);
    gl.attachShader(program, fragmentShader);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      throw new Error(gl.getProgramInfoLog(program) || "program_link_failed");
    }
  } catch (err) {
    return null;
  }

  const vertices = new Float32Array([
    -1, -1, 0, 0,
    1, -1, 1, 0,
    -1, 1, 0, 1,
    1, 1, 1, 1
  ]);
  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.STATIC_DRAW);

  const aPos = gl.getAttribLocation(program, "a_pos");
  const aUv = gl.getAttribLocation(program, "a_uv");
  gl.enableVertexAttribArray(aPos);
  gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 16, 0);
  gl.enableVertexAttribArray(aUv);
  gl.vertexAttribPointer(aUv, 2, gl.FLOAT, false, 16, 8);

  const texture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);

  gl.useProgram(program);
  gl.uniform1i(gl.getUniformLocation(program, "u_tex"), 0);

  let width = 0;
  let height = 0;
  let pixels = null;

  function resize(displayWidth, displayHeight) {
    width = Math.max(2, Math.floor(displayWidth));
    height = Math.max(2, Math.floor(displayHeight));
    targetCanvas.width = width;
    targetCanvas.height = height;
    gl.viewport(0, 0, width, height);
    pixels = new Uint8Array(width * height * 4);
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
  }

  function render(fftDb) {
    if (!Array.isArray(fftDb) || !fftDb.length || !pixels) {
      return;
    }
    let minDb = Infinity;
    let maxDb = -Infinity;
    for (let i = 0; i < fftDb.length; i += 1) {
      const value = fftDb[i];
      if (value < minDb) minDb = value;
      if (value > maxDb) maxDb = value;
    }
    const scale = maxDb - minDb || 1;
    const rowBytes = width * 4;
    pixels.copyWithin(0, rowBytes);
    const rowOffset = (height - 1) * rowBytes;

    for (let x = 0; x < width; x += 1) {
      const idx = Math.floor((x / width) * fftDb.length);
      const value = (fftDb[idx] - minDb) / scale;
      const color = colorMap(value);
      const offset = rowOffset + x * 4;
      pixels[offset] = color[0];
      pixels[offset + 1] = color[1];
      pixels[offset + 2] = color[2];
      pixels[offset + 3] = 255;
    }

    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  return { resize, render };
}


function initWaterfallRenderer() {
  webglWaterfall = createWebglWaterfallRenderer(canvas);
  if (webglWaterfall) {
    waterfallRenderer = "webgl";
    return;
  }
  ctx = canvas.getContext("2d");
  waterfallRenderer = "2d";
}

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  if (webglWaterfall) {
    webglWaterfall.resize(rect.width, rect.height);
    return;
  }
  canvas.width = Math.floor(rect.width * window.devicePixelRatio);
  canvas.height = Math.floor(rect.height * window.devicePixelRatio);
  if (!ctx) {
    ctx = canvas.getContext("2d");
  }
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
}

initWaterfallRenderer();
resizeCanvas();
window.addEventListener("resize", resizeCanvas);

function addEvent(text) {
  logLine(`events: ${text}`);
}

function pushLiveEventToPanel(eventPayload) {
  if (!eventPayload || typeof eventPayload !== "object") {
    return;
  }
  updateCallsignCacheFromEvent(eventPayload);
  latestEvents = [eventPayload, ...latestEvents].slice(0, 500);
  renderEventsPanelFromCache();
}

function applyEventsPanelFilters(items) {
  const callsignTerm = (eventsSearchCallsignInput?.value || "").trim().toLowerCase();
  const modeTerm = (eventsSearchModeInput?.value || "").trim().toLowerCase();
  const gridTerm = (eventsSearchGridInput?.value || "").trim().toLowerCase();
  const reportTerm = (eventsSearchReportInput?.value || "").trim().toLowerCase();
  return items.filter((eventItem) => {
    const callsignText = String(eventItem.callsign || "").toLowerCase();
    const modeText = String(eventItem.mode || "").toLowerCase();
    const gridText = String(eventItem.grid || "").toLowerCase();
    const reportText = String(eventItem.report ?? "").toLowerCase();
    if (callsignTerm && !callsignText.includes(callsignTerm)) {
      return false;
    }
    if (modeTerm && !modeText.includes(modeTerm)) {
      return false;
    }
    if (gridTerm && !gridText.includes(gridTerm)) {
      return false;
    }
    if (reportTerm && !reportText.includes(reportTerm)) {
      return false;
    }
    return true;
  });
}

function hasEventsSearchCriteria() {
  return Boolean(
    (eventsSearchCallsignInput?.value || "").trim()
    || (eventsSearchModeInput?.value || "").trim()
    || (eventsSearchGridInput?.value || "").trim()
    || (eventsSearchReportInput?.value || "").trim()
  );
}

function updateEventsPager(totalItems) {
  const totalPages = Math.max(1, Math.ceil(totalItems / EVENTS_PANEL_PAGE_SIZE));
  if (eventsPageInfo) {
    eventsPageInfo.textContent = `Page: ${eventsPanelPage + 1}/${totalPages}`;
  }
  if (eventsPrevBtn) {
    eventsPrevBtn.disabled = eventsPanelPage <= 0;
  }
  if (eventsNextBtn) {
    eventsNextBtn.disabled = eventsPanelPage >= totalPages - 1;
  }
}

function renderEventsPanelFromCache() {
  renderEvents(latestEvents);
}

function orderEventsForDisplay(items) {
  const source = Array.isArray(items) ? items.slice() : [];
  source.sort((a, b) => {
    const aType = String(a?.type || "").toLowerCase();
    const bType = String(b?.type || "").toLowerCase();
    if (aType === "callsign" && bType !== "callsign") {
      return -1;
    }
    if (aType !== "callsign" && bType === "callsign") {
      return 1;
    }
    const aTs = String(a?.timestamp || "");
    const bTs = String(b?.timestamp || "");
    if (aTs > bTs) {
      return -1;
    }
    if (aTs < bTs) {
      return 1;
    }
    return 0;
  });
  return source;
}

function inferBandFromFrequency(frequencyHz) {
  const value = Number(frequencyHz);
  if (!Number.isFinite(value) || value <= 0) {
    return null;
  }
  const bandRanges = [
    { name: "160m", min: 1800000, max: 2000000 },
    { name: "80m", min: 3500000, max: 4000000 },
    { name: "60m", min: 5250000, max: 5450000 },
    { name: "40m", min: 7000000, max: 7300000 },
    { name: "30m", min: 10100000, max: 10150000 },
    { name: "20m", min: 14000000, max: 14350000 },
    { name: "17m", min: 18068000, max: 18168000 },
    { name: "15m", min: 21000000, max: 21450000 },
    { name: "12m", min: 24890000, max: 24990000 },
    { name: "10m", min: 28000000, max: 29700000 },
    { name: "6m", min: 50000000, max: 54000000 },
    { name: "2m", min: 144000000, max: 148000000 },
    { name: "70cm", min: 430000000, max: 440000000 }
  ];
  const match = bandRanges.find((range) => value >= range.min && value <= range.max);
  return match ? match.name : null;
}

function renderEventList(targetEl, items, emptyMessage) {
  if (!targetEl) {
    return;
  }
  targetEl.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("li");
    empty.className = "event-empty";
    empty.textContent = emptyMessage;
    targetEl.appendChild(empty);
    return;
  }

  items.forEach((eventItem) => {
    const li = document.createElement("li");
    li.className = "event-item";

    const header = document.createElement("div");
    header.className = "event-item__meta";

    const typeBadge = document.createElement("span");
    typeBadge.className = `badge ${eventItem.type === "callsign" ? "bg-info" : "bg-secondary"}`;
    typeBadge.textContent = eventItem.type || "event";

    const modeBadge = document.createElement("span");
    modeBadge.className = "badge bg-primary";
    modeBadge.textContent = eventItem.mode || "Unknown";

    const timeStamp = document.createElement("span");
    const timeText = eventItem.timestamp ? new Date(eventItem.timestamp).toLocaleTimeString() : "--";
    timeStamp.className = "event-item__time";
    timeStamp.textContent = timeText;

    header.appendChild(typeBadge);
    header.appendChild(modeBadge);
    header.appendChild(timeStamp);

    const body = document.createElement("div");
    body.className = "event-item__body";
    const frequencyValue = Number(eventItem.frequency_hz);
    const freq = Number.isFinite(frequencyValue) && frequencyValue > 0 ? frequencyValue.toLocaleString() : "-";
    const band = eventItem.band || inferBandFromFrequency(frequencyValue) || "-";
    const callsign = eventItem.callsign || extractCallsignFromRaw(eventItem.raw) || "-";
    body.innerHTML = `<strong>${freq} Hz</strong> <span class="event-item__muted">${band}</span> <span class="event-item__call">${callsign}</span>`;

    const detail = document.createElement("div");
    detail.className = "event-item__detail";
    if (eventItem.mode === "APRS") {
      const latValue = Number(eventItem.lat);
      const lonValue = Number(eventItem.lon);
      const lat = Number.isFinite(latValue) ? latValue.toFixed(3) : "--";
      const lon = Number.isFinite(lonValue) ? lonValue.toFixed(3) : "--";
      detail.textContent = `path=${eventItem.path || "-"} | lat=${lat} lon=${lon} | ${eventItem.msg || eventItem.payload || ""}`.trim();
    } else if (eventItem.type === "callsign") {
      const hasGrid = eventItem.grid !== null && eventItem.grid !== undefined && eventItem.grid !== "";
      const hasReport = eventItem.report !== null && eventItem.report !== undefined && eventItem.report !== "";
      if (hasGrid || hasReport) {
        const grid = hasGrid ? eventItem.grid : "-";
        const report = hasReport ? eventItem.report : "-";
        detail.textContent = `grid=${grid} report=${report}`;
      }
    } else if (eventItem.type === "occupancy") {
      const bw = eventItem.bandwidth_hz ? `${eventItem.bandwidth_hz} Hz` : "-";
      const snrValue = Number(eventItem.snr_db);
      const snr = Number.isFinite(snrValue) ? `${snrValue.toFixed(1)} dB` : "-";
      detail.textContent = `bw=${bw} snr=${snr}`;
    }

    li.appendChild(header);
    li.appendChild(body);
    if (detail.textContent) {
      li.appendChild(detail);
    }
    targetEl.appendChild(li);
  });
}

function renderEvents(items) {
  const sourceItems = Array.isArray(items) ? items : [];
  updateCallsignCacheFromEvents(sourceItems);
  latestEvents = sourceItems.filter((eventItem) => {
    if (String(eventItem?.type || "") !== "occupancy") {
      return true;
    }
    const freq = Number(eventItem?.frequency_hz || 0);
    const mode = String(eventItem?.mode || "").trim().toLowerCase();
    const band = String(eventItem?.band || "").trim();
    const scanId = eventItem?.scan_id;
    const occupied = Boolean(eventItem?.occupied);
    const invalidNoise = (!occupied) && freq <= 0 && (!band || band.toLowerCase() === "null") && mode === "unknown";
    const invalidUnbound = (scanId === null || scanId === undefined) && freq <= 0 && (!band || band.toLowerCase() === "null");
    return !(invalidNoise || invalidUnbound);
  });
  const matrix = {};
  const bandsSeen = new Set();
  const modesSeen = new Set();

  const totalEvents = latestEvents.length;
  const orderedEvents = orderEventsForDisplay(latestEvents);
  const totalEventPages = Math.max(1, Math.ceil(totalEvents / EVENTS_PANEL_PAGE_SIZE));
  if (eventsPanelPage > totalEventPages - 1) {
    eventsPanelPage = totalEventPages - 1;
  }
  if (eventsPanelPage < 0) {
    eventsPanelPage = 0;
  }
  const eventsStartIndex = eventsPanelPage * EVENTS_PANEL_PAGE_SIZE;
  const eventsPagedItems = orderedEvents.slice(eventsStartIndex, eventsStartIndex + EVENTS_PANEL_PAGE_SIZE);

  renderEventList(
    eventsEl,
    eventsPagedItems,
    "No events yet. Start a scan or adjust filters."
  );

  const filteredItems = applyEventsPanelFilters(orderedEvents);

  const shouldShowSearchResults = hasEventsSearchCriteria();
  renderEventList(
    eventsSearchResultsEl,
    shouldShowSearchResults ? filteredItems : [],
    shouldShowSearchResults
      ? (latestEvents.length ? "No events match the current Events search." : "No events yet.")
      : "Use search fields to display results."
  );

  eventsTotal.textContent = String(totalEvents);
  updateEventsPager(totalEvents);

  filteredItems.forEach((eventItem) => {
    const bandName = eventItem.band || inferBandFromFrequency(eventItem.frequency_hz);
    const modeName = eventItem.mode;
    if (!bandName || !modeName) {
      return;
    }

    bandsSeen.add(bandName);
    modesSeen.add(modeName);
    matrix[bandName] = matrix[bandName] || {};
    matrix[bandName][modeName] = (matrix[bandName][modeName] || 0) + 1;
  });

  const renderedBands = Array.from(bandsSeen).sort((a, b) => a.localeCompare(b));
  const renderedModes = Array.from(modesSeen).sort((a, b) => a.localeCompare(b));

  if (summaryMatrixCaption) {
    summaryMatrixCaption.textContent = "Live data from current events";
  }

  if (!summaryMatrixTable) {
    return;
  }

  const head = summaryMatrixTable.querySelector("thead");
  const body = summaryMatrixTable.querySelector("tbody");
  const foot = summaryMatrixTable.querySelector("tfoot");
  if (!head || !body || !foot) {
    return;
  }

  head.innerHTML = "";
  body.innerHTML = "";
  foot.innerHTML = "";

  if (!renderedBands.length || !renderedModes.length) {
    const emptyRow = document.createElement("tr");
    const emptyCell = document.createElement("td");
    emptyCell.colSpan = 2;
    emptyCell.textContent = "No summary matrix available for current events";
    emptyRow.appendChild(emptyCell);
    body.appendChild(emptyRow);
    return;
  }

  const headRow = document.createElement("tr");
  const corner = document.createElement("th");
  corner.scope = "col";
  corner.textContent = "Band \\ Mode";
  headRow.appendChild(corner);
  renderedModes.forEach((mode) => {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = mode;
    headRow.appendChild(th);
  });
  const totalCol = document.createElement("th");
  totalCol.scope = "col";
  totalCol.textContent = "Total";
  headRow.appendChild(totalCol);
  head.appendChild(headRow);

  const modeTotals = Object.fromEntries(renderedModes.map((mode) => [mode, 0]));
  let grandTotal = 0;

  renderedBands.forEach((band) => {
    const row = document.createElement("tr");
    const bandCell = document.createElement("th");
    bandCell.scope = "row";
    bandCell.textContent = band;
    row.appendChild(bandCell);

    let rowTotal = 0;
    renderedModes.forEach((mode) => {
      const value = Number(matrix?.[band]?.[mode] || 0);
      rowTotal += value;
      modeTotals[mode] += value;

      const cell = document.createElement("td");
      cell.textContent = String(value);
      row.appendChild(cell);
    });

    grandTotal += rowTotal;
    const totalCell = document.createElement("td");
    totalCell.textContent = String(rowTotal);
    row.appendChild(totalCell);
    body.appendChild(row);
  });

  const footRow = document.createElement("tr");
  const totalLabel = document.createElement("th");
  totalLabel.scope = "row";
  totalLabel.textContent = "Total";
  footRow.appendChild(totalLabel);

  renderedModes.forEach((mode) => {
    const cell = document.createElement("td");
    cell.textContent = String(modeTotals[mode]);
    footRow.appendChild(cell);
  });

  const grandCell = document.createElement("td");
  grandCell.textContent = String(grandTotal);
  footRow.appendChild(grandCell);
  foot.appendChild(footRow);
}

async function fetchEvents() {
  try {
    const params = new URLSearchParams({ limit: "200", offset: String(eventOffset) });
    if (bandFilter.value) {
      params.append("band", bandFilter.value);
    }
    if (modeFilter.value) {
      params.append("mode", modeFilter.value);
    }
    if (callsignFilter.value) {
      params.append("callsign", callsignFilter.value.trim());
    }
    if (startFilter.value) {
      params.append("start", new Date(startFilter.value).toISOString());
    }
    if (endFilter.value) {
      params.append("end", new Date(endFilter.value).toISOString());
    }
    const resp = await fetch(`/api/events?${params.toString()}`, {
      headers: { ...getAuthHeader() }
    });
    if (resp.status === 401) {
      showToastError("Authentication failed");
      return;
    }
    const data = await resp.json();
    renderEvents(data);
    localStorage.setItem("filters", JSON.stringify({
      band: bandFilter.value,
      mode: modeFilter.value,
      callsign: callsignFilter.value,
      start: startFilter.value,
      end: endFilter.value
    }));
  } catch (err) {
    addEvent("Failed to load events");
  }
}

async function fetchTotal() {
  try {
    const params = new URLSearchParams({});
    if (bandFilter.value) {
      params.append("band", bandFilter.value);
    }
    if (modeFilter.value) {
      params.append("mode", modeFilter.value);
    }
    if (callsignFilter.value) {
      params.append("callsign", callsignFilter.value.trim());
    }
    if (startFilter.value) {
      params.append("start", new Date(startFilter.value).toISOString());
    }
    if (endFilter.value) {
      params.append("end", new Date(endFilter.value).toISOString());
    }
    const resp = await fetch(`/api/events/count?${params.toString()}`, {
      headers: { ...getAuthHeader() }
    });
    if (!resp.ok) {
      return;
    }
    await resp.json();
  } catch (err) {
    return;
  }
}

async function fetchModeStats() {
  try {
    const resp = await fetch("/api/events/stats", { headers: { ...getAuthHeader() } });
    if (!resp.ok) {
      return;
    }
    const data = await resp.json();
    modeStatsCache = data.modes || {};
  } catch (err) {
    return;
  }
}

function renderPropagationSummary(data, options = {}) {
  if (!propagationScore || !propagationBands) {
    return;
  }
  const overallScore = Number(data?.overall?.score ?? 0).toFixed(1);
  const overallState = String(data?.overall?.state || "Unknown");
  const eventCount = Number(data?.event_count || 0);
  const windowMinutes = Number(data?.window_minutes || 30);
  const sourceNote = options?.sourceNote ? ` | ${options.sourceNote}` : "";
  propagationScore.textContent = `Score: ${overallScore}/100 (${overallState}) | events=${eventCount} | window=${windowMinutes} min${sourceNote}`;

  const bands = Array.isArray(data?.bands) ? data.bands.slice(0, 5) : [];
  propagationBands.innerHTML = "";
  if (!bands.length) {
    const li = document.createElement("li");
    li.textContent = "No propagation data yet. Start/continue scan to build propagation statistics.";
    propagationBands.appendChild(li);
    return;
  }

  bands.forEach((item) => {
    const li = document.createElement("li");
    const bandName = String(item?.band || "Unknown");
    const score = Number(item?.score || 0).toFixed(1);
    const state = String(item?.state || "Unknown");
    const events = Number(item?.events || 0);
    const maxSNR = item?.max_snr_db;
    const snrLabel = maxSNR === null || maxSNR === undefined ? "-" : `${Number(maxSNR).toFixed(1)} dB`;
    li.textContent = `${bandName}: ${score}/100 (${state}) | events=${events} | max SNR=${snrLabel}`;
    propagationBands.appendChild(li);
  });
}

async function requestPropagationSummary(windowMinutes, limit) {
  const resp = await fetch(`/api/propagation/summary?window_minutes=${windowMinutes}&limit=${limit}`, {
    headers: { ...getAuthHeader() }
  });
  if (!resp.ok) {
    return null;
  }
  return resp.json();
}

async function fetchPropagationSummary() {
  try {
    const primaryWindowMinutes = 30;
    const fallbackWindowMinutes = 1440;
    const limit = 3000;

    const primary = await requestPropagationSummary(primaryWindowMinutes, limit);
    if (!primary) {
      return;
    }
    if (Number(primary?.event_count || 0) > 0) {
      renderPropagationSummary(primary);
      return;
    }

    const fallback = await requestPropagationSummary(fallbackWindowMinutes, limit);
    if (fallback && Number(fallback?.event_count || 0) > 0) {
      renderPropagationSummary(fallback, { sourceNote: "fallback 24h" });
      return;
    }

    renderPropagationSummary(primary);
  } catch (err) {
    return;
  }
}

async function fetchLogs() {
  try {
    const resp = await fetch("/api/logs?limit=50", { headers: { ...getAuthHeader() } });
    if (!resp.ok) {
      return;
    }
    const data = await resp.json();
    logsEl.textContent = data.join("\n");
  } catch (err) {
    return;
  }
}

function connectLogs() {
  try {
    const ws = new WebSocket(wsUrl("/ws/logs"));
    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        if (Array.isArray(data.logs)) {
          logsEl.textContent = data.logs.join("\n");
        }
      } catch (err) {
        return;
      }
    };
  } catch (err) {
    return;
  }
}

function setStatus(text) {
  statusEl.textContent = text;
}

function initMenuDropdownModalBehavior() {
  const modalDropdownItems = document.querySelectorAll('.menu-toolbar .dropdown-item[data-bs-toggle="modal"]');
  if (!modalDropdownItems.length) {
    return;
  }

  modalDropdownItems.forEach((item) => {
    item.addEventListener("click", () => {
      const dropdownRoot = item.closest(".dropdown");
      const toggle = dropdownRoot ? dropdownRoot.querySelector('[data-bs-toggle="dropdown"]') : null;
      if (!toggle || typeof bootstrap === "undefined" || !bootstrap.Dropdown) {
        return;
      }
      const dropdown = bootstrap.Dropdown.getOrCreateInstance(toggle);
      dropdown.hide();
    });
  });
}

async function parseApiError(response, fallbackMessage) {
  try {
    const payload = await response.json();
    const detail = payload?.detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
  } catch (err) {
    return `${fallbackMessage} (HTTP ${response.status})`;
  }
  return `${fallbackMessage} (HTTP ${response.status})`;
}

function updateScanButtonState() {
  if (!startBtn) {
    return;
  }
  if (scanActionInFlight) {
    startBtn.textContent = isScanRunning ? "Stopping..." : "Starting...";
    startBtn.disabled = true;
    return;
  }
  startBtn.textContent = isScanRunning ? "Stop scanning" : "Start scanning";
  startBtn.disabled = false;
  startBtn.classList.toggle("btn-primary", !isScanRunning);
  startBtn.classList.toggle("btn-danger", isScanRunning);
  refreshQuickBandButtons();
}

function inferDeviceFamily(deviceId) {
  const value = String(deviceId || "").toLowerCase();
  if (value.includes("rtl")) {
    return "rtl";
  }
  if (value.includes("hack")) {
    return "hackrf";
  }
  if (value.includes("air")) {
    return "airspy";
  }
  return "other";
}

function normalizeScanSampleRate(deviceId, sampleRate) {
  const family = inferDeviceFamily(deviceId);
  if (!["rtl", "hackrf", "airspy"].includes(family)) {
    return Number(sampleRate);
  }
  const parsedRate = Number(sampleRate);
  if (Number.isFinite(parsedRate) && parsedRate >= 200000) {
    return parsedRate;
  }
  return Number(DEVICE_AUTO_PROFILES[family]?.sample_rate || 2048000);
}

async function startScan() {
  setStatus("Starting scan...");
  const gain = Number(gainInput.value);
  const selectedDeviceId = deviceSelect.value || null;
  const sampleRate = normalizeScanSampleRate(selectedDeviceId, sampleRateInput.value);
  if (Number(sampleRateInput.value) !== sampleRate) {
    sampleRateInput.value = String(sampleRate);
    showToast(`Sample rate ajustado automaticamente para ${sampleRate} Hz`);
  }
  const recordPath = recordPathInput.value || null;
  const selectedBand = bandSelect.value;
  const range = getScanRangeForBand(selectedBand);
  const response = await fetch("/api/scan/start", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeader() },
    body: JSON.stringify({
      device: selectedDeviceId,
      scan: {
        band: selectedBand,
        start_hz: range.start_hz,
        end_hz: range.end_hz,
        step_hz: 2000,
        dwell_ms: 250,
        mode: "auto",
        gain,
        sample_rate: sampleRate,
        record_path: recordPath
      }
    })
  });
  if (!response.ok) {
    const message = await parseApiError(response, "Failed to start scan");
    throw new Error(message);
  }
  isScanRunning = true;
  setStatus("Scan running");
  logLine("Scan started");
}

async function stopScan() {
  setStatus("Stopping scan...");
  const response = await fetch("/api/scan/stop", { method: "POST", headers: { ...getAuthHeader() } });
  if (!response.ok) {
    const message = await parseApiError(response, "Failed to stop scan");
    throw new Error(message);
  }
  isScanRunning = false;
  setStatus("Scan stopped");
  logLine("Scan stopped");
}

async function syncScanState() {
  try {
    const response = await fetch("/api/scan/status", { headers: { ...getAuthHeader() } });
    if (!response.ok) {
      return;
    }
    const data = await response.json();
    const nextRunning = data?.state === "running";
    if (!scanActionInFlight) {
      isScanRunning = nextRunning;
      setStatus(nextRunning ? "Scan running" : "Scan stopped");
      updateScanButtonState();
    }
  } catch (err) {
    return;
  }
}

async function toggleScan() {
  if (scanActionInFlight) {
    return;
  }
  scanActionInFlight = true;
  updateScanButtonState();
  try {
    if (isScanRunning) {
      await stopScan();
    } else {
      await startScan();
    }
  } catch (err) {
    showToastError(err?.message || (isScanRunning ? "Failed to stop scan" : "Failed to start scan"));
  } finally {
    scanActionInFlight = false;
    updateScanButtonState();
  }
}

async function switchBandLive(selectedBand) {
  if (!bandSelect) {
    return;
  }
  const nextBand = String(selectedBand || "").trim();
  if (!nextBand) {
    return;
  }
  const hasOption = Array.from(bandSelect.options || []).some((option) => option.value === nextBand);
  if (!hasOption) {
    return;
  }

  const previousBand = bandSelect.value;
  if (previousBand === nextBand) {
    refreshQuickBandButtons();
    return;
  }

  bandSelect.value = nextBand;
  bandSelect.dispatchEvent(new Event("change"));

  if (!isScanRunning || scanActionInFlight) {
    return;
  }

  scanActionInFlight = true;
  updateScanButtonState();
  try {
    await stopScan();
    await startScan();
    showToast(`Band switched to ${nextBand}`);
  } catch (err) {
    showToastError(err?.message || "Failed to switch band live");
  } finally {
    scanActionInFlight = false;
    updateScanButtonState();
  }
}

startBtn.addEventListener("click", () => {
  toggleScan();
});

function connectEvents() {
  try {
    const ws = new WebSocket(wsUrl("/ws/events"));
    ws.onopen = () => logLine("Connected to events stream");
    ws.onmessage = (msg) => {
      try {
        const payload = JSON.parse(msg.data);
        if (payload && typeof payload === "object" && payload.event && typeof payload.event === "object") {
          pushLiveEventToPanel(payload.event);
          return;
        }
        if (payload && typeof payload === "object") {
          pushLiveEventToPanel(payload);
        }
      } catch (err) {
        logLine("Events stream decode error");
      }
    };
    ws.onerror = () => logLine("Events stream error");
    ws.onclose = () => {
      wsStatus.textContent = "WS: disconnected";
    };
  } catch (err) {
    logLine("WebSocket not available");
  }
}

connectEvents();
fetchEvents();
setInterval(fetchEvents, 5000);

bandFilter.addEventListener("change", fetchEvents);
modeFilter.addEventListener("change", fetchEvents);
callsignFilter.addEventListener("change", fetchEvents);
startFilter.addEventListener("change", fetchEvents);
endFilter.addEventListener("change", fetchEvents);
bandFilter.addEventListener("change", fetchTotal);
modeFilter.addEventListener("change", fetchTotal);
callsignFilter.addEventListener("change", fetchTotal);
startFilter.addEventListener("change", fetchTotal);
endFilter.addEventListener("change", fetchTotal);

if (eventsSearchCallsignInput) {
  eventsSearchCallsignInput.addEventListener("input", () => {
    eventsPanelPage = 0;
    renderEventsPanelFromCache();
  });
}

if (eventsSearchModeInput) {
  eventsSearchModeInput.addEventListener("input", () => {
    eventsPanelPage = 0;
    renderEventsPanelFromCache();
  });
}

if (eventsSearchGridInput) {
  eventsSearchGridInput.addEventListener("input", () => {
    eventsPanelPage = 0;
    renderEventsPanelFromCache();
  });
}

if (eventsSearchReportInput) {
  eventsSearchReportInput.addEventListener("input", () => {
    eventsPanelPage = 0;
    renderEventsPanelFromCache();
  });
}

if (eventsPrevBtn) {
  eventsPrevBtn.addEventListener("click", () => {
    eventsPanelPage = Math.max(0, eventsPanelPage - 1);
    renderEventsPanelFromCache();
  });
}

if (eventsNextBtn) {
  eventsNextBtn.addEventListener("click", () => {
    const filteredItems = applyEventsPanelFilters(latestEvents);
    const totalPages = Math.max(1, Math.ceil(filteredItems.length / EVENTS_PANEL_PAGE_SIZE));
    eventsPanelPage = Math.min(totalPages - 1, eventsPanelPage + 1);
    renderEventsPanelFromCache();
  });
}

function buildEventExportParams() {
  const params = new URLSearchParams({ limit: "1000" });
  if (bandFilter.value) {
    params.append("band", bandFilter.value);
  }
  if (modeFilter.value) {
    params.append("mode", modeFilter.value);
  }
  if (callsignFilter.value) {
    params.append("callsign", callsignFilter.value.trim());
  }
  if (startFilter.value) {
    params.append("start", new Date(startFilter.value).toISOString());
  }
  if (endFilter.value) {
    params.append("end", new Date(endFilter.value).toISOString());
  }
  return params;
}


exportCsvBtn.addEventListener("click", () => {
  exportCsvBtn.disabled = true;
  exportCsvBtn.textContent = "Exporting...";
  const params = buildEventExportParams();
  params.set("format", "csv");
  window.location.href = `/api/export?${params.toString()}`;
  setTimeout(() => {
    exportCsvBtn.disabled = false;
    exportCsvBtn.textContent = "Export CSV";
  }, 1500);
});


exportJsonBtn.addEventListener("click", async () => {
  exportJsonBtn.disabled = true;
  exportJsonBtn.textContent = "Exporting...";
  try {
    const params = buildEventExportParams();
    const resp = await fetch(`/api/events?${params.toString()}`, { headers: { ...getAuthHeader() } });
    if (!resp.ok) {
      throw new Error("json_export_failed");
    }
    const payload = await resp.json();
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `events-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    showToast("JSON exported");
  } catch (err) {
    showToastError("JSON export failed");
  } finally {
    exportJsonBtn.disabled = false;
    exportJsonBtn.textContent = "Export JSON";
  }
});


exportPngBtn.addEventListener("click", () => {
  exportPngBtn.disabled = true;
  exportPngBtn.textContent = "Exporting...";
  try {
    const url = canvas.toDataURL("image/png");
    const link = document.createElement("a");
    link.href = url;
    link.download = `waterfall-${new Date().toISOString().replace(/[:.]/g, "-")}.png`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    showToast("PNG exported");
  } catch (err) {
    showToastError("PNG export failed");
  } finally {
    exportPngBtn.disabled = false;
    exportPngBtn.textContent = "Export PNG";
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "s") {
    if (!isScanRunning) {
      toggleScan();
    }
  }
  if (event.key === "x") {
    if (isScanRunning) {
      toggleScan();
    }
  }
});

function connectSpectrum() {
  if (spectrumWs) {
    spectrumWs.close();
    spectrumWs = null;
  }
  try {
    const ws = new WebSocket(wsUrl("/ws/spectrum"));
    spectrumWs = ws;
    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        const frame = decodeSpectrumFrame(data.spectrum_frame);
        if (frame && frame.fft_db) {
          lastSpectrumFrame = frame;
          lastSpectrumFrameTs = Date.now();
          const viewport = getWaterfallViewport(frame);
          drawWaterfall(frame, viewport);
          const stableMarkers = buildStableWaterfallMarkers(frame);
          const rulerRange = resolveWaterfallRulerRange(
            frame,
            viewport,
            stableMarkers.rangeStartHz,
            stableMarkers.rangeEndHz
          );
          renderWaterfallRuler(rulerRange.startHz, rulerRange.endHz);
          const simulatedMarkers = buildSimulatedModeMarkers(
            viewport.visibleSpanHz,
            rulerRange.startHz,
            rulerRange.endHz
          );
          const modeMarkers = WATERFALL_SIMULATE_MODE_MARKERS
            ? [...stableMarkers.markers, ...simulatedMarkers]
            : stableMarkers.markers;
          renderWaterfallModeOverlay(modeMarkers, viewport.visibleSpanHz, rulerRange.startHz, rulerRange.endHz);
          const startHz = Math.round(viewport.startHz);
          const endHz = Math.round(viewport.endHz);
          const minDb = frame.min_db !== undefined ? frame.min_db.toFixed(1) : "?";
          const maxDb = frame.max_db !== undefined ? frame.max_db.toFixed(1) : "?";
          const noiseFloor = frame.noise_floor_db !== undefined ? frame.noise_floor_db.toFixed(1) : "?";
          const agcGain = frame.agc_gain_db !== undefined && frame.agc_gain_db !== null
            ? frame.agc_gain_db.toFixed(1)
            : null;
          let peaksInfo = "";
          if (Array.isArray(frame.peaks) && frame.peaks.length) {
            const topPeaks = frame.peaks.slice(0, 3).map((peak) => {
              const hz = Math.round(peak.offset_hz ?? 0);
              const snr = peak.snr_db !== undefined ? peak.snr_db.toFixed(1) : "?";
              return `${hz}Hz/${snr}dB`;
            });
            peaksInfo = ` | peaks ${frame.peaks.length}: ${topPeaks.join(", ")}`;
          }
          const agcInfo = agcGain ? ` | agc ${agcGain}dB` : "";
          const explorerInfo = viewport.simulated ? ` | explorer zoom x${waterfallExplorerZoom}` : "";
          clearWaterfallGenericStatus();
          waterfallStatus.textContent = `FFT bins: ${viewport.fftDb.length} | ${startHz} Hz - ${endHz} Hz | dB ${minDb}..${maxDb} | nf ${noiseFloor}dB${peaksInfo}${agcInfo}${explorerInfo} | ${waterfallRenderer.toUpperCase()}`;
          updateQuality(minDb, maxDb);
        }
      } catch (err) {
        setWaterfallGenericStatus("No live spectrum data available. Check SDR device connection and backend status.");
      }
    };
    ws.onopen = () => {
      wsStatus.textContent = "WS: connected";
    };
    ws.onclose = () => {
      if (spectrumWs === ws) {
        wsStatus.textContent = "WS: disconnected";
        setWaterfallGenericStatus();
        spectrumWs = null;
      }
    };
  } catch (err) {
    wsStatus.textContent = "WS: disconnected";
    setWaterfallGenericStatus();
  }
}

function ensureWaterfallFallback() {
  if (spectrumFallbackTimer) {
    clearInterval(spectrumFallbackTimer);
  }
  spectrumFallbackTimer = setInterval(() => {
    const staleMs = Date.now() - lastSpectrumFrameTs;
    if (lastSpectrumFrameTs === 0 || staleMs > 2500) {
      setWaterfallGenericStatus();
    }
  }, 400);
}

if (waterfallFullscreenBtn) {
  waterfallFullscreenBtn.addEventListener("click", async () => {
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else {
        await document.documentElement.requestFullscreen();
      }
    } catch (err) {
      showToastError("Fullscreen unavailable");
    }
  });
}

document.addEventListener("fullscreenchange", updateFullscreenButtonState);

function redrawWaterfallFromLastFrame() {
  if (!lastSpectrumFrame || !lastSpectrumFrame.fft_db) {
    return;
  }
  const viewport = getWaterfallViewport(lastSpectrumFrame);
  drawWaterfall(lastSpectrumFrame, viewport);
  const stableMarkers = buildStableWaterfallMarkers(lastSpectrumFrame);
  const rulerRange = resolveWaterfallRulerRange(
    lastSpectrumFrame,
    viewport,
    stableMarkers.rangeStartHz,
    stableMarkers.rangeEndHz
  );
  renderWaterfallRuler(rulerRange.startHz, rulerRange.endHz);
  const simulatedMarkers = buildSimulatedModeMarkers(
    viewport.visibleSpanHz,
    rulerRange.startHz,
    rulerRange.endHz
  );
  const modeMarkers = WATERFALL_SIMULATE_MODE_MARKERS
    ? [...stableMarkers.markers, ...simulatedMarkers]
    : stableMarkers.markers;
  renderWaterfallModeOverlay(modeMarkers, viewport.visibleSpanHz, rulerRange.startHz, rulerRange.endHz);
}

function resetWaterfallExplorerView() {
  waterfallExplorerZoom = 1;
  waterfallExplorerPan = 0;
  localStorage.setItem(WATERFALL_EXPLORER_ZOOM_KEY, String(waterfallExplorerZoom));
  applyWaterfallExplorerUi();
  redrawWaterfallFromLastFrame();
}

if (waterfallExplorerToggle) {
  waterfallExplorerToggle.addEventListener("click", () => {
    waterfallExplorerEnabled = !waterfallExplorerEnabled;
    localStorage.setItem(WATERFALL_EXPLORER_KEY, waterfallExplorerEnabled ? "1" : "0");
    if (!waterfallExplorerEnabled) {
      waterfallExplorerPan = 0;
      waterfallExplorerZoom = 1;
      localStorage.setItem(WATERFALL_EXPLORER_ZOOM_KEY, String(waterfallExplorerZoom));
    }
    applyWaterfallExplorerUi();
    redrawWaterfallFromLastFrame();
  });
}

if (waterfallZoomInput) {
  waterfallZoomInput.addEventListener("input", () => {
    const nextZoom = Math.max(1, Math.min(16, Math.round(Number(waterfallZoomInput.value) || 1)));
    const currentCenter = waterfallExplorerPan + (0.5 / waterfallExplorerZoom);
    waterfallExplorerZoom = nextZoom;
    const maxPan = Math.max(0, 1 - (1 / waterfallExplorerZoom));
    waterfallExplorerPan = Math.max(0, Math.min(maxPan, currentCenter - (0.5 / waterfallExplorerZoom)));
    localStorage.setItem(WATERFALL_EXPLORER_ZOOM_KEY, String(waterfallExplorerZoom));
    applyWaterfallExplorerUi();
    clearWaterfallFrame();
    redrawWaterfallFromLastFrame();
  });
}

if (waterfallResetViewBtn) {
  waterfallResetViewBtn.addEventListener("click", () => {
    clearWaterfallFrame();
    resetWaterfallExplorerView();
  });
}

if (waterfallEl) {
  waterfallEl.addEventListener("pointerdown", (event) => {
    if (!waterfallExplorerEnabled) {
      return;
    }
    waterfallDragActive = true;
    waterfallDragStartX = event.clientX;
    waterfallDragStartPan = waterfallExplorerPan;
    waterfallEl.classList.add("is-dragging");
  });
}

document.addEventListener("pointermove", (event) => {
  if (!waterfallDragActive || !waterfallExplorerEnabled || !waterfallEl) {
    return;
  }
  const rect = waterfallEl.getBoundingClientRect();
  if (!rect.width) {
    return;
  }
  const deltaNorm = ((event.clientX - waterfallDragStartX) / rect.width) * (1 / waterfallExplorerZoom);
  const maxPan = Math.max(0, 1 - (1 / waterfallExplorerZoom));
  waterfallExplorerPan = Math.max(0, Math.min(maxPan, waterfallDragStartPan - deltaNorm));
  clearWaterfallFrame();
  redrawWaterfallFromLastFrame();
});

document.addEventListener("pointerup", () => {
  if (!waterfallDragActive) {
    return;
  }
  waterfallDragActive = false;
  if (waterfallEl) {
    waterfallEl.classList.remove("is-dragging");
  }
});

connectSpectrum();
ensureWaterfallFallback();

function decodeSpectrumFrame(frame) {
  if (!frame) {
    return frame;
  }
  if (Array.isArray(frame.fft_db)) {
    return frame;
  }
  if (frame.encoding !== "delta_int8" || !Array.isArray(frame.fft_delta)) {
    return frame;
  }
  const ref = Number(frame.fft_ref_db ?? 0);
  const step = Number(frame.fft_step_db ?? 0.5) || 0.5;
  const fftDb = frame.fft_delta.map((value) => ref + (Number(value) + 128) * step);
  return {
    ...frame,
    fft_db: fftDb
  };
}

function connectStatus() {
  try {
    const ws = new WebSocket(wsUrl("/ws/status"));
    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        const status = data.status;
        if (status) {
          const noiseFloor = Number(status.noise_floor_db);
          const thresholdValue = Number(status.threshold_db);
          const nf = Number.isFinite(noiseFloor) ? noiseFloor.toFixed(1) : "?";
          const threshold = Number.isFinite(thresholdValue) ? thresholdValue.toFixed(1) : "?";
          const agc = status.agc_gain_db !== undefined && status.agc_gain_db !== null
            ? status.agc_gain_db.toFixed(1)
            : "?";
          statusEl.textContent = `state=${status.state} cpu=${status.cpu_pct ?? "?"}% noise=${nf}dB thr=${threshold}dB agc=${agc}dB frameAge=${status.frame_age_ms ?? "?"}ms`;
        }
      } catch (err) {
        setStatus("Status decode error");
      }
    };
  } catch (err) {
    setStatus("Status stream unavailable");
  }
}

connectStatus();

async function fetchDecoderStatus() {
  if (!decoderStatusEl) {
    return;
  }
  try {
    const resp = await fetch("/api/decoders/status", { headers: { ...getAuthHeader() } });
    if (!resp.ok) {
      throw new Error("decoder status failed");
    }
    const data = await resp.json();
    const status = data.status || {};
    const wsjtx = status.wsjtx_udp || {};
    const kiss = status.direwolf_kiss || {};
    const sources = status.sources || {};
    const lastEvent = Object.values(sources).sort().slice(-1)[0] || "-";
    const wsjtxListen = String(wsjtx.listen || "").trim();
    if (wsjtx.enabled) {
      wsjtxUdpStatusEl.textContent = `Listening ${wsjtxListen || "?"}`;
    } else if (wsjtx.last_error) {
      wsjtxUdpStatusEl.textContent = `Error (${wsjtx.last_error})`;
    } else if (wsjtxListen) {
      wsjtxUdpStatusEl.textContent = `Stopped (${wsjtxListen})`;
    } else {
      wsjtxUdpStatusEl.textContent = "Not configured (set WSJTX_UDP_ENABLE=1 or WSJTX_UDP_PORT)";
    }
    const kissState = kiss.enabled ? (kiss.connected ? "Connected" : "Disconnected") : "Disabled";
    const kissDisabledReason = kiss.last_error
      ? ` (${kiss.last_error})`
      : " (set DIREWOLF_KISS_ENABLE=1 or DIREWOLF_KISS_PORT)";
    kissStatusEl.textContent = kiss.enabled ? kissState : `Disabled${kissDisabledReason}`;
    decoderLastEventEl.textContent = lastEvent;
    agcStatusEl.textContent = status.dsp && status.dsp.agc_enabled ? "On" : "Off";
  } catch (err) {
    wsjtxUdpStatusEl.textContent = "Unavailable";
    kissStatusEl.textContent = "Unavailable";
    decoderLastEventEl.textContent = "-";
    agcStatusEl.textContent = "-";
  }
}

async function loadDevices() {
  const previousLabel = refreshDevicesBtn ? refreshDevicesBtn.textContent : null;
  if (refreshDevicesBtn) {
    refreshDevicesBtn.disabled = true;
    refreshDevicesBtn.textContent = "Refreshing...";
  }
  try {
    const resp = await fetch("/api/devices", { headers: { ...getAuthHeader() } });
    if (!resp.ok) {
      throw new Error(`devices_fetch_failed_${resp.status}`);
    }
    const devices = await resp.json();
    if (!Array.isArray(devices)) {
      throw new Error("devices_invalid_response");
    }
    const isLikelySdrDevice = (device) => {
      const haystack = [device?.id, device?.type, device?.name]
        .map((value) => String(value || "").toLowerCase())
        .join(" ");
      if (!haystack) {
        return false;
      }
      if (haystack.includes("audio") || haystack.includes("microphone") || haystack.includes("headphones")) {
        return false;
      }
      return ["rtl", "rtlsdr", "hackrf", "airspy", "limesdr", "sdrplay", "bladerf", "pluto", "uhd", "osmosdr"].some((token) => haystack.includes(token));
    };
    const sdrDevices = devices.filter((device) => isLikelySdrDevice(device));
    const visibleDevices = showNonSdrDevices ? devices : sdrDevices;
    deviceSelect.innerHTML = "";
    if (!visibleDevices.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No SDR devices detected";
      deviceSelect.appendChild(option);
      setWaterfallGenericStatus();
      if (devices.length) {
        showToastError("Only non-SDR devices detected. Connect RTL/HackRF/Airspy or run Administration.");
      } else {
        showToastError("No SDR devices detected. Check RTL/Soapy drivers or use Administration.");
      }
      return;
    }
    visibleDevices.forEach((device) => {
      const option = document.createElement("option");
      option.value = device.id;
      option.textContent = device.name;
      deviceSelect.appendChild(option);
    });
    if (showNonSdrDevices) {
      showToast(`Detected ${visibleDevices.length} device(s) (${sdrDevices.length} SDR)`);
    } else {
      showToast(`Detected ${sdrDevices.length} SDR device(s)`);
    }
  } catch (err) {
    logLine("Failed to load devices");
    showToastError("Failed to refresh devices");
  } finally {
    if (refreshDevicesBtn) {
      refreshDevicesBtn.disabled = false;
      refreshDevicesBtn.textContent = previousLabel || "Refresh devices";
    }
  }
}

function normalizeDeviceChoice(choice) {
  const raw = String(choice || "").trim().toLowerCase();
  if (!raw) {
    return null;
  }
  if (raw.includes("rtl")) {
    return "rtl";
  }
  if (raw.includes("hackrf") || raw.includes("hack")) {
    return "hackrf";
  }
  if (raw.includes("airspy") || raw.includes("air")) {
    return "airspy";
  }
  if (raw.includes("other") || raw.includes("outro")) {
    return "other";
  }
  return raw;
}

function findDeviceByChoice(devices, choice) {
  const term = String(choice || "").toLowerCase();
  return devices.find((device) => {
    const id = String(device.id || "").toLowerCase();
    const type = String(device.type || "").toLowerCase();
    const name = String(device.name || "").toLowerCase();
    return id.includes(term) || type.includes(term) || name.includes(term);
  });
}

async function runAdministrationSetup() {
  if (adminSetupStatus) {
    adminSetupStatus.textContent = "";
    adminSetupStatus.classList.add("d-none");
    adminSetupStatus.classList.remove("alert-warning");
    adminSetupStatus.classList.add("alert-success");
  }
  const input = window.prompt("Which device are you using? (RTL-SDR, HackRF, Airspy, Other)", "RTL-SDR");
  if (input === null) {
    return;
  }
  const choice = normalizeDeviceChoice(input);
  if (!choice) {
    showToastError("Device type not provided");
    return;
  }

  let preflight;
  try {
    const resp = await fetch("/api/admin/device/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify({
        device_type: choice,
        dry_run: true,
        auto_install: false,
        apply_config: false,
      })
    });
    if (!resp.ok) {
      throw new Error("admin_preflight_failed");
    }
    preflight = await resp.json();
  } catch (err) {
    showToastError("Automatic setup pre-check failed");
    return;
  }

  const pkgList = preflight?.requirements?.linux_apt_packages || [];
  const installedPkgs = preflight?.probe_before?.apt_packages?.installed || [];
  const missingPkgs = preflight?.probe_before?.apt_packages?.missing || [];
  const moduleList = preflight?.requirements?.python_modules || [];
  const foundNow = Boolean(preflight?.probe_before?.match_found);
  const summaryText = [
    `Device type: ${input}`,
    `Detected now: ${foundNow ? "yes" : "no"}`,
    `Python modules: ${moduleList.length ? moduleList.join(", ") : "none"}`,
    `Linux packages required: ${pkgList.length ? pkgList.join(", ") : "none"}`,
    `Linux packages installed: ${installedPkgs.length ? installedPkgs.join(", ") : "none"}`,
    `Linux packages missing: ${missingPkgs.length ? missingPkgs.join(", ") : "none"}`,
    "Proceed with automatic installation and configuration?"
  ].join("\n");

  const approve = window.confirm(summaryText);
  if (!approve) {
    return;
  }

  let setupData;
  try {
    const resp = await fetch("/api/admin/device/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify({
        device_type: choice,
        dry_run: false,
        auto_install: true,
        apply_config: true,
      })
    });
    if (!resp.ok) {
      throw new Error("admin_setup_failed");
    }
    setupData = await resp.json();
  } catch (err) {
    showToastError("Automatic setup failed");
    return;
  }

  const selected = setupData?.probe_after?.matched_device;
  if (!selected) {
    const installErr = setupData?.install?.error;
    if (installErr) {
      if (installErr === "elevation_required") {
        showToastError("Automatic install needs system authorization. Approve the OS prompt and try again.");
      } else if (installErr === "no_privilege_escalation_tool") {
        showToastError("Automatic install unavailable: install sudo or pkexec on this Linux system.");
      } else {
        showToastError(`Device not ready (${installErr}).`);
      }
    } else {
      showToastError(`No ${input} device found`);
    }
    return;
  }

  showToast(`Device found: ${selected.name || selected.id}`);
  const installMethod = setupData?.install?.method;
  if (installMethod) {
    logLine(`Automatic package install method: ${installMethod}`);
  }
  const profile = setupData?.configured?.profile || DEVICE_AUTO_PROFILES[choice] || DEVICE_AUTO_PROFILES.other;
  const appliedDeviceConfig = setupData?.configured?.device_config || {};
  const audioProfile = setupData?.configured?.audio_config || setupData?.audio_probe?.suggested || {
    input_device: "",
    output_device: "",
    sample_rate: 48000,
    rx_gain: 1,
    tx_gain: 1,
  };
  deviceSelect.value = selected.id;
  const setupDeviceConfig = {
    device_class: choice,
    ppm_correction: appliedDeviceConfig.ppm_correction ?? profile.ppm_correction ?? 0,
    frequency_offset_hz: appliedDeviceConfig.frequency_offset_hz ?? profile.frequency_offset_hz ?? 0,
    gain_profile: appliedDeviceConfig.gain_profile || profile.gain_profile || "auto",
  };
  applyDeviceConfigToForm(setupDeviceConfig);
  sampleRateInput.value = String(profile.sample_rate);
  gainInput.value = String(profile.gain);
  audioInputDeviceInput.value = audioProfile.input_device || "";
  audioOutputDeviceInput.value = audioProfile.output_device || "";
  audioSampleRateInput.value = String(audioProfile.sample_rate ?? 48000);
  audioRxGainInput.value = String(audioProfile.rx_gain ?? 1);
  audioTxGainInput.value = String(audioProfile.tx_gain ?? 1);

  const methods = (setupData?.audio_probe?.methods || []).join("/") || "defaults";
  updateAdminAudioStatus(audioProfile, { sourceLabel: "auto-configurado", methods });

  const appliedDeviceClass = (deviceClassSelect?.value || "auto").toUpperCase();
  const appliedPpm = devicePpmInput.value || "0";
  const appliedOffset = deviceOffsetHzInput.value || "0";
  const appliedGainProfile = deviceGainProfileSelect.value || "auto";
  showToast(`Configuração automática: classe=${appliedDeviceClass}, PPM=${appliedPpm}, offset=${appliedOffset} Hz, gain=${appliedGainProfile}`);
  logLine(`Admin setup applied: device=${selected.id}, class=${appliedDeviceClass}, ppm=${appliedPpm}, offset_hz=${appliedOffset}, gain_profile=${appliedGainProfile}`);
  await loadSettings();
}

async function runAudioAutoDetect() {
  const choice = normalizeDeviceChoice(deviceClassSelect?.value || deviceSelect?.value || "other") || "other";
  try {
    const resp = await fetch("/api/admin/device/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify({
        device_type: choice,
        dry_run: true,
        auto_install: false,
        apply_config: false,
      })
    });
    if (!resp.ok) {
      throw new Error("audio_auto_detect_failed");
    }
    const data = await resp.json();
    const audioProfile = data?.audio_probe?.suggested || {
      input_device: "",
      output_device: "",
      sample_rate: 48000,
      rx_gain: 1,
      tx_gain: 1,
    };
    const methods = (data?.audio_probe?.methods || []).join("/") || "defaults";

    audioInputDeviceInput.value = audioProfile.input_device || "";
    audioOutputDeviceInput.value = audioProfile.output_device || "";
    audioSampleRateInput.value = String(audioProfile.sample_rate ?? 48000);
    audioRxGainInput.value = String(audioProfile.rx_gain ?? 1);
    audioTxGainInput.value = String(audioProfile.tx_gain ?? 1);

    const hasDetectedEndpoints = Boolean((audioProfile.input_device || "").trim() || (audioProfile.output_device || "").trim());
    updateAdminAudioStatus(audioProfile, { sourceLabel: "auto-detectado", methods });
    showToast("Auto-detect áudio concluído");
    logLine(`Audio auto-detect: detected=${hasDetectedEndpoints}, input=${audioProfile.input_device || ""}, output=${audioProfile.output_device || ""}, sample_rate=${audioProfile.sample_rate ?? 48000}, method=${methods}`);
  } catch (err) {
    showToastError("Falha no auto-detect de áudio");
  }
}

async function loadBands() {
  try {
    const resp = await fetch("/api/bands", { headers: { ...getAuthHeader() } });
    const bands = await resp.json();
    if (Array.isArray(bands)) {
      populateBandSelectOptions(bands);
      return;
    }
  } catch (err) {
    logLine("Failed to load bands");
  }
  populateBandSelectOptions([]);
}

async function loadSettings() {
  const authUser = localStorage.getItem("authUser") || "";
  const authPass = localStorage.getItem("authPass") || "";
  authUserInput.value = authUser;
  authPassInput.value = authPass;
  loginUserInput.value = authUser;
  loginPassInput.value = authPass;

  try {
    const resp = await fetch("/api/settings", { headers: { ...getAuthHeader() } });
    const data = await resp.json();
    if (data.band) {
      if (typeof data.band === "string") {
        bandSelect.value = data.band;
      } else if (data.band.name) {
        bandSelect.value = data.band.name;
        bandNameInput.value = data.band.name;
        bandStartInput.value = data.band.start_hz ?? bandStartInput.value;
        bandEndInput.value = data.band.end_hz ?? bandEndInput.value;
      }
    }
    if (data.device_id) {
      deviceSelect.value = data.device_id;
    }
    if (Array.isArray(data.favorites)) {
      localStorage.setItem("favoriteBands", JSON.stringify(data.favorites));
      loadFavorites();
    }
    if (data.modes) {
      ft8Toggle.value = data.modes.ft8 ? "on" : "off";
      aprsToggle.value = data.modes.aprs ? "on" : "off";
      cwToggle.value = data.modes.cw ? "on" : "off";
      ssbToggle.value = data.modes.ssb ? "on" : "off";
    }
    if (data.station) {
      stationCallsignInput.value = data.station.callsign || "";
      stationOperatorInput.value = data.station.operator || "";
      stationLocatorInput.value = data.station.locator || "";
      stationQthInput.value = data.station.qth || "";
    }
    applyDeviceConfigToForm(data.device_config || {});
    if (data.audio_config) {
      audioInputDeviceInput.value = data.audio_config.input_device || "";
      audioOutputDeviceInput.value = data.audio_config.output_device || "";
      audioSampleRateInput.value = data.audio_config.sample_rate ?? 48000;
      audioRxGainInput.value = data.audio_config.rx_gain ?? 1;
      audioTxGainInput.value = data.audio_config.tx_gain ?? 1;
      updateAdminAudioStatus(data.audio_config, { sourceLabel: "guardado" });
    } else if (adminSetupStatus) {
      adminSetupStatus.textContent = "";
      adminSetupStatus.classList.add("d-none");
      adminSetupStatus.classList.remove("alert-warning");
      adminSetupStatus.classList.add("alert-success");
    }
  } catch (err) {
    logLine("Failed to load settings");
  }
}

saveModesBtn.addEventListener("click", async () => {
  const payload = {
    modes: {
      ft8: ft8Toggle.value === "on",
      aprs: aprsToggle.value === "on",
      cw: cwToggle.value === "on",
      ssb: ssbToggle.value === "on"
    }
  };
  await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeader() },
    body: JSON.stringify(payload)
  });
  showToast("Modes saved");
});

if (prevPageBtn) {
  prevPageBtn.addEventListener("click", () => {
    eventOffset = Math.max(0, eventOffset - 25);
    fetchEvents();
  });
}

if (nextPageBtn) {
  nextPageBtn.addEventListener("click", () => {
    eventOffset += 25;
    fetchEvents();
  });
}

if (compactToggle) {
  compactToggle.addEventListener("click", () => {
    const panel = compactToggle.closest(".filters");
    panel?.classList.toggle("compact");
  });
}

loginSaveBtn.addEventListener("click", () => {
  localStorage.setItem("authUser", loginUserInput.value);
  localStorage.setItem("authPass", loginPassInput.value);
  showToast("Credentials saved");
  updateLoginStatus();
});

const onboardingSteps = [
  {
    title: "Welcome",
    text: "Configure device, band, and credentials. Use Start or press s."
  },
  {
    title: "Scan",
    text: "Select band, gain, and sample rate. Start scan and watch the waterfall."
  },
  {
    title: "Events",
    text: "Use filters to narrow events and export CSV reports."
  }
];
let onboardingStep = 0;

function renderOnboarding() {
  const step = onboardingSteps[onboardingStep];
  onboardingTitle.textContent = step.title;
  onboardingText.textContent = step.text;
  onboardingPrev.disabled = onboardingStep === 0;
  onboardingNext.textContent = onboardingStep === onboardingSteps.length - 1 ? "Done" : "Next";
}

onboardingPrev.addEventListener("click", () => {
  if (onboardingStep > 0) {
    onboardingStep -= 1;
    renderOnboarding();
  }
});

onboardingNext.addEventListener("click", () => {
  if (onboardingStep < onboardingSteps.length - 1) {
    onboardingStep += 1;
    renderOnboarding();
    return;
  }
  onboarding.classList.remove("show");
  localStorage.setItem("onboardingDone", "1");
});

function loadFilters() {
  const data = JSON.parse(localStorage.getItem("filters") || "{}")
  if (data.band) bandFilter.value = data.band;
  if (data.mode) modeFilter.value = data.mode;
  if (data.callsign) callsignFilter.value = data.callsign;
  if (data.start) startFilter.value = data.start;
  if (data.end) endFilter.value = data.end;
}

saveSettingsBtn.addEventListener("click", async () => {
  localStorage.setItem("authUser", authUserInput.value);
  localStorage.setItem("authPass", authPassInput.value);
  if (!isValidCallsign(stationCallsignInput.value)) {
    showToastError("Invalid callsign format");
    return;
  }
  if (!isValidLocator(stationLocatorInput.value)) {
    showToastError("Invalid locator format (use IN51 or IN51ab)");
    return;
  }

  const payload = {
    band: bandSelect.value,
    device_id: deviceSelect.value,
    station: {
      callsign: stationCallsignInput.value.trim(),
      operator: stationOperatorInput.value.trim(),
      locator: stationLocatorInput.value.trim(),
      qth: stationQthInput.value.trim(),
    },
    device_config: buildDeviceConfigPayload(),
    audio_config: buildAudioConfigPayload()
  };
  const response = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeader() },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    const message = await parseApiError(response, "Failed to save settings");
    showToastError(message);
    return;
  }
  await loadSettings();
  logLine("Settings saved");
  showToast("Settings saved");
});

if (saveDeviceConfigBtn) {
  saveDeviceConfigBtn.addEventListener("click", async () => {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify({ device_config: buildDeviceConfigPayload() })
    });
    if (!response.ok) {
      const message = await parseApiError(response, "Failed to save device configuration");
      showToastError(message);
      return;
    }
    await loadSettings();
    logLine("Device configuration saved");
    showToast("Device configuration saved");
  });
}

if (saveAudioConfigBtn) {
  saveAudioConfigBtn.addEventListener("click", async () => {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify({ audio_config: buildAudioConfigPayload() })
    });
    if (!response.ok) {
      const message = await parseApiError(response, "Failed to save audio configuration");
      showToastError(message);
      return;
    }
    await loadSettings();
    logLine("Audio configuration saved");
    showToast("Audio configuration saved");
  });
}

if (testConfigBtn) {
  testConfigBtn.addEventListener("click", async () => {
    const payload = {
      device_id: deviceSelect.value || null,
      audio_config: {
        input_device: audioInputDeviceInput.value.trim(),
        output_device: audioOutputDeviceInput.value.trim(),
        sample_rate: Number(audioSampleRateInput.value || 48000),
        rx_gain: Number(audioRxGainInput.value || 1),
        tx_gain: Number(audioTxGainInput.value || 1),
      }
    };
    try {
      const resp = await fetch("/api/admin/config/test", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeader() },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) {
        if (resp.status === 404 || resp.status === 405) {
          throw new Error("Config test endpoint unavailable (HTTP 405/404). Restart backend service to load latest API.");
        }
        const message = await parseApiError(resp, "Config test failed");
        throw new Error(message);
      }
      const data = await resp.json();
      const deviceOk = Boolean(data?.device?.ok);
      const audioOk = Boolean(data?.audio?.ok);
      const soapyOk = Boolean(data?.device?.soapy_import_ok);

      const failedChecks = [];
      const audioChecks = data?.audio?.checks || {};
      Object.entries(audioChecks).forEach(([checkName, passed]) => {
        if (!passed) {
          failedChecks.push(checkName);
        }
      });

      if (!deviceOk) {
        const detectedCount = Number(data?.device?.detected_count || 0);
        failedChecks.push(detectedCount > 0 ? "selected_device" : "device_detection");
      }
      if (!soapyOk) {
        failedChecks.push("soapy_import");
      }

      if (deviceOk && audioOk && soapyOk) {
        showToast("Config test passed");
      } else {
        const checkLabels = {
          arecord: "arecord",
          aplay: "aplay",
          pactl: "pactl",
          "pw-cli": "pw-cli",
          sample_rate_valid: "sample rate",
          rx_gain_valid: "RX gain",
          tx_gain_valid: "TX gain",
          selected_device: "selected device",
          device_detection: "device detection",
          soapy_import: "SoapySDR import",
          unknown_checks: "unknown checks",
        };
        const issueText = failedChecks.length
          ? failedChecks.map((checkName) => checkLabels[checkName] || checkName).join(", ")
          : checkLabels.unknown_checks;
        const soapyError = data?.device?.soapy_import_error;
        const suffix = soapyError ? ` | soapy: ${soapyError}` : "";
        showToastError(`Config test issues: ${issueText}${suffix}`);
      }
      logLine(`Config test: device_ok=${deviceOk} audio_ok=${audioOk} soapy_ok=${soapyOk}`);
    } catch (err) {
      showToastError(err?.message || "Config test failed");
    }
  });
}

if (resetDefaultsBtn) {
  resetDefaultsBtn.addEventListener("click", async () => {
    const approved = window.confirm("Reset settings defaults? This will replace current mode/summary settings.");
    if (!approved) {
      return;
    }
    const previousLabel = resetDefaultsBtn.textContent;
    resetDefaultsBtn.disabled = true;
    resetDefaultsBtn.textContent = "Resetting...";
    try {
      const resp = await fetch("/api/settings/reset-defaults", {
        method: "POST",
        headers: { ...getAuthHeader() },
      });
      if (!resp.ok) {
        const message = await parseApiError(resp, "Failed to reset defaults");
        throw new Error(message);
      }
      await loadSettings();
      fetchEvents();
      fetchModeStats();
      showToast("Defaults restored");
      logLine("Settings defaults restored");
    } catch (err) {
      showToastError(err?.message || "Failed to reset defaults");
    } finally {
      resetDefaultsBtn.disabled = false;
      resetDefaultsBtn.textContent = previousLabel || "Reset defaults";
    }
  });
}

if (resetAllConfigBtn) {
  resetAllConfigBtn.addEventListener("click", async () => {
    const approved = window.confirm("Reset total? This will clear backend settings/bands and local browser data.");
    if (!approved) {
      return;
    }
    const previousLabel = resetAllConfigBtn.textContent;
    resetAllConfigBtn.disabled = true;
    resetAllConfigBtn.textContent = "Resetting...";
    try {
      const resp = await fetch("/api/admin/reset-all-config", {
        method: "POST",
        headers: { ...getAuthHeader() },
      });
      if (!resp.ok) {
        const message = await parseApiError(resp, "Failed to reset total config");
        throw new Error(message);
      }
      localStorage.clear();
      window.location.reload();
    } catch (err) {
      showToastError(err?.message || "Failed to reset total config");
      resetAllConfigBtn.disabled = false;
      resetAllConfigBtn.textContent = previousLabel || "Reset total";
    }
  });
}

if (purgeInvalidEventsBtn) {
  purgeInvalidEventsBtn.addEventListener("click", async () => {
    const confirmed = window.confirm("Purge invalid/incomplete events from local database?");
    if (!confirmed) {
      return;
    }
    const previousLabel = purgeInvalidEventsBtn.textContent;
    purgeInvalidEventsBtn.disabled = true;
    purgeInvalidEventsBtn.textContent = "Purging...";
    try {
      const resp = await fetch("/api/admin/events/purge-invalid", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeader() },
        body: JSON.stringify({})
      });
      if (!resp.ok) {
        throw new Error(`purge_failed_${resp.status}`);
      }
      const data = await resp.json();
      const deleted = Number(data?.purge?.deleted || 0);
      showToast(`Invalid events purged: ${deleted}`);
      fetchEvents();
      fetchTotal();
      fetchModeStats();
    } catch (err) {
      showToastError("Failed to purge invalid events");
    } finally {
      purgeInvalidEventsBtn.disabled = false;
      purgeInvalidEventsBtn.textContent = previousLabel || "Purge invalid events";
    }
  });
}

refreshDevicesBtn.addEventListener("click", () => {
  loadDevices();
});

if (showNonSdrDevicesToggle) {
  showNonSdrDevicesToggle.addEventListener("change", () => {
    showNonSdrDevices = Boolean(showNonSdrDevicesToggle.checked);
    localStorage.setItem(SHOW_NON_SDR_DEVICES_KEY, showNonSdrDevices ? "1" : "0");
    loadDevices();
  });
}

if (adminDeviceSetupBtn) {
  adminDeviceSetupBtn.addEventListener("click", () => {
    runAdministrationSetup();
  });
}

if (adminAudioAutoDetectBtn) {
  adminAudioAutoDetectBtn.addEventListener("click", () => {
    runAudioAutoDetect();
  });
}

if (bandNameInput) {
  bandNameInput.addEventListener("change", () => {
    if (bandSelect) {
      const hasOption = Array.from(bandSelect.options || []).some((option) => option.value === bandNameInput.value);
      if (hasOption) {
        bandSelect.value = bandNameInput.value;
      }
    }

    const preset = BAND_PRESETS[String(bandNameInput.value)];
    if (!preset) {
      return;
    }
    bandStartInput.value = String(preset.start_hz);
    bandEndInput.value = String(preset.end_hz);
  });

  const initialPreset = BAND_PRESETS[String(bandNameInput.value)];
  if (initialPreset) {
    bandStartInput.value = String(initialPreset.start_hz);
    bandEndInput.value = String(initialPreset.end_hz);
  }
}

if (bandSelect && bandNameInput) {
  bandSelect.addEventListener("change", () => {
    const hasOption = Array.from(bandNameInput.options || []).some((option) => option.value === bandSelect.value);
    if (hasOption) {
      bandNameInput.value = bandSelect.value;
    }
    refreshQuickBandButtons();
  });
}

if (bandSelect && quickBandButtons.length) {
  quickBandButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      if (scanActionInFlight) {
        return;
      }
      const selectedBand = String(button.dataset.quickBand || "").trim();
      await switchBandLive(selectedBand);
    });
  });
}

saveBandBtn.addEventListener("click", async () => {
  const payload = {
    band: {
      name: bandNameInput.value,
      start_hz: Number(bandStartInput.value),
      end_hz: Number(bandEndInput.value)
    }
  };
  const resp = await fetch("/api/bands", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeader() },
    body: JSON.stringify(payload)
  });
  if (!resp.ok) {
    showToast("Band validation failed");
    return;
  }
  logLine("Band saved");
  showToast("Band saved");
  loadBands();
});

loadDevices().then(loadBands).then(loadSettings).then(loadPresets).then(loadFavorites).then(loadFilters).then(fetchTotal);
refreshQuickBandButtons();
syncScanState();
setInterval(syncScanState, 5000);
fetchModeStats();
setInterval(fetchModeStats, 10000);
fetchPropagationSummary();
setInterval(fetchPropagationSummary, 15000);
fetchDecoderStatus();
setInterval(fetchDecoderStatus, 10000);
updateLoginStatus();
connectLogs();
fetchLogs();
setInterval(fetchLogs, 4000);
initMenuDropdownModalBehavior();

if (!localStorage.getItem("onboardingDone")) {
  onboarding.classList.add("show");
  renderOnboarding();
}

function drawWaterfall(frame, viewport = null) {
  const resolvedViewport = viewport || getWaterfallViewport(frame);
  const fftDb = resolvedViewport.fftDb || [];
  if (webglWaterfall) {
    webglWaterfall.render(fftDb);
    return;
  }
  const width = canvas.width / window.devicePixelRatio;
  const height = canvas.height / window.devicePixelRatio;
  if (!fftDb.length) {
    return;
  }

  let minDb = Infinity;
  let maxDb = -Infinity;
  for (let i = 0; i < fftDb.length; i += 1) {
    const value = fftDb[i];
    if (value < minDb) {
      minDb = value;
    }
    if (value > maxDb) {
      maxDb = value;
    }
  }
  const scale = maxDb - minDb || 1;
  const rowData = ctx.createImageData(Math.floor(width), 1);

  for (let x = 0; x < width; x += 1) {
    const idx = Math.floor((x / width) * fftDb.length);
    const value = (fftDb[idx] - minDb) / scale;
    const color = colorMap(value);
    const offset = x * 4;
    rowData.data[offset] = color[0];
    rowData.data[offset + 1] = color[1];
    rowData.data[offset + 2] = color[2];
    rowData.data[offset + 3] = 255;
  }

  ctx.putImageData(rowData, 0, row);
  if (!resolvedViewport.simulated && Array.isArray(frame.peaks) && frame.peaks.length && frame.span_hz) {
    ctx.save();
    ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
    const span = frame.span_hz;
    frame.peaks.forEach((peak) => {
      const offset = peak.offset_hz ?? 0;
      const x = Math.round(((offset + span / 2) / span) * width);
      ctx.fillRect(x, row, 2, 1);
    });
    ctx.restore();
  }
  row = (row + 1) % height;
  if (row === 0) {
    ctx.clearRect(0, 0, width, height);
  }
}

function colorMap(value) {
  const r = Math.floor(255 * value);
  const g = Math.floor(140 + 80 * (1 - value));
  const b = Math.floor(255 * (1 - value));
  return [r, g, b];
}
