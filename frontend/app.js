/*
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-02-24 18:30 UTC
*/

import { loadPresetsFromJson } from "./utils/presets.js";

const statusEl = document.getElementById("status");
const eventsEl = document.getElementById("events");
const eventsSearchCallsignInput = document.getElementById("eventsSearchCallsign");
const eventsSearchModeInput = document.getElementById("eventsSearchMode");
const eventsSearchBandInput = document.getElementById("eventsSearchBand");
const eventsSearchSnrMinInput = document.getElementById("eventsSearchSnrMin");
const eventsSearchStartInput = document.getElementById("eventsSearchStart");
const eventsSearchEndInput = document.getElementById("eventsSearchEnd");
const eventsSearchCountEl = document.getElementById("eventsSearchCount");
const eventsSearchPrevBtn = document.getElementById("eventsSearchPrev");
const eventsSearchNextBtn = document.getElementById("eventsSearchNext");
const eventsSearchPageInfoEl = document.getElementById("eventsSearchPageInfo");
const eventsPrevBtn = document.getElementById("eventsPrev");
const eventsNextBtn = document.getElementById("eventsNext");
const eventsTypeFilter = document.getElementById("eventsTypeFilter");
const eventsPageInfo = document.getElementById("eventsPageInfo");
const eventsSearchResultsEl = document.getElementById("eventsSearchResults");
const eventsFullscreenEl = document.getElementById("eventsFullscreen");
const eventsFullscreenPrevBtn = document.getElementById("eventsFullscreenPrev");
const eventsFullscreenNextBtn = document.getElementById("eventsFullscreenNext");
const eventsFullscreenPageInfo = document.getElementById("eventsFullscreenPageInfo");
const eventsFullscreenTitle = document.getElementById("eventsFullscreenTitle");
const eventsFullscreenModal = document.getElementById("eventsFullscreenModal");
const adminModalEl = document.getElementById("adminModal");
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
const spectrumCanvas = document.getElementById("spectrumCanvas");
const spectrumCtx = spectrumCanvas ? spectrumCanvas.getContext("2d") : null;
let _specSmooth = null;
const _SPEC_SMOOTH_ALPHA = 0.2;
let ctx = null;
let webglWaterfall = null;
let waterfallRenderer = "2d";
const gainInput = document.getElementById("gain");
const sampleRateInput = document.getElementById("sampleRate");
const recordPathInput = document.getElementById("recordPath");
const cwScanParamsRow = document.getElementById("cwScanParamsRow");
const cwStepHzInput = document.getElementById("cwStepHz");
const cwDwellSInput = document.getElementById("cwDwellS");
const scanRangeSummaryEl = document.getElementById("scanRangeSummary");
const cwSegmentSummaryWrapEl = document.getElementById("cwSegmentSummaryWrap");
const cwSegmentSummaryEl = document.getElementById("cwSegmentSummary");
const frontendLogsEl = document.getElementById("frontendLogs");
const frontendLogsOpsEl = document.getElementById("frontendLogsOps");
const serverLogsEl = document.getElementById("serverLogs");
const exportBandFilter = document.getElementById("exportBandFilter");
const exportModeFilter = document.getElementById("exportModeFilter");
const exportCallsignFilter = document.getElementById("exportCallsignFilter");
const exportStartFilter = document.getElementById("exportStartFilter");
const exportEndFilter = document.getElementById("exportEndFilter");
const exportCsvBtn = document.getElementById("exportCsv");
const exportJsonBtn = document.getElementById("exportJson");
const exportPngBtn = document.getElementById("exportPng");
const deviceSelect = document.getElementById("deviceSelect");
const bandSelect = document.getElementById("bandSelect");
const authUserInput = document.getElementById("authUser");
const authPassInput = document.getElementById("authPass");
const AUTH_PASSWORD_MASK = "********";
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
const quickModeButtons = Array.from(document.querySelectorAll("[data-quick-mode]"));
const adminSetupStatus = document.getElementById("adminSetupStatus");

// Selected decoder mode for scan
let selectedDecoderMode = null;
let latestScanState = null;

const CW_DECODER_SUBBANDS = {
  "160m": { start_hz: 1_800_000, end_hz: 1_840_000 },
  "80m": { start_hz: 3_500_000, end_hz: 3_600_000 },
  "40m": { start_hz: 7_000_000, end_hz: 7_040_000 },
  "30m": { start_hz: 10_100_000, end_hz: 10_130_000 },
  "20m": { start_hz: 14_000_000, end_hz: 14_070_000 },
  "17m": { start_hz: 18_068_000, end_hz: 18_110_000 },
  "15m": { start_hz: 21_000_000, end_hz: 21_150_000 },
  "12m": { start_hz: 24_890_000, end_hz: 24_930_000 },
  "10m": { start_hz: 28_000_000, end_hz: 28_300_000 },
};

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
    adminSetupStatus.textContent = `Audio ${sourceLabel}: input=${inputDevice || "not set"} | output=${outputDevice || "not set"} | sample rate=${sampleRate} Hz (${methods})`;
  } else {
    adminSetupStatus.classList.add("alert-warning");
    adminSetupStatus.textContent = `Audio not automatically detected: input/output not set | sample rate=${sampleRate} Hz. Configure manually or run Auto-detect Device again.`;
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
const toast = document.getElementById("toast");
const loginUserInput = document.getElementById("loginModalUser");
const loginPassInput = document.getElementById("loginModalPass");
const loginSaveBtn = document.getElementById("loginModalSave");
const saveCredentialsBtn = document.getElementById("saveCredentials");
const clearCredentialsBtn = document.getElementById("clearCredentials");
const authStatusBadge = document.getElementById("authStatusBadge");
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
const eventsCardTitle = document.getElementById("eventsCardTitle");
const eventsCardTitleText = document.getElementById("eventsCardTitleText");
const propagationScore = document.getElementById("propagationScore");
const propagationBands = document.getElementById("propagationBands");
const compactToggle = document.getElementById("compactToggle");
let modeStatsCache = {};
let totalEventsInDB = 0;
const externalFtStatusModalEl = document.getElementById("externalFtStatusModal");
const kissStatusModalEl = document.getElementById("kissStatusModal");
const decoderLastEventModalEl = document.getElementById("decoderLastEventModal");
const agcStatusModalEl = document.getElementById("agcStatusModal");
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

function formatBandOptionLabel(bandName) {
  const normalizedBand = String(bandName || "").trim();
  if (!normalizedBand) {
    return "";
  }
  const defaultOption = DEFAULT_BAND_OPTIONS.find((item) => item.name === normalizedBand);
  const baseLabel = defaultOption?.label || normalizedBand;
  const range = getScanRangeForBand(normalizedBand);
  const startHz = Number(range.start_hz || 0);
  const endHz = Number(range.end_hz || 0);
  if (!(startHz > 0 && endHz > startHz)) {
    return baseLabel;
  }
  return `${baseLabel} (${(startHz / 1_000_000).toFixed(3)} - ${(endHz / 1_000_000).toFixed(3)} MHz)`;
}

function refreshBandEditorOptions() {
  if (!bandNameInput) {
    return;
  }

  const optionNames = new Set([
    ...DEFAULT_BAND_OPTIONS.map((item) => item.name),
    ...bandRangesByName.keys(),
  ]);

  const currentValue = String(bandNameInput.value || "").trim();
  bandNameInput.innerHTML = "";
  Array.from(optionNames).forEach((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = formatBandOptionLabel(name);
    bandNameInput.appendChild(option);
  });

  if (currentValue && optionNames.has(currentValue)) {
    bandNameInput.value = currentValue;
  } else if (optionNames.has("20m")) {
    bandNameInput.value = "20m";
  } else {
    bandNameInput.value = Array.from(optionNames)[0] || "";
  }
}

function syncBandEditorFields(bandName) {
  if (!bandNameInput || !bandStartInput || !bandEndInput) {
    return;
  }
  const normalizedBand = String(bandName || bandNameInput.value || "").trim();
  if (!normalizedBand) {
    return;
  }
  const range = getScanRangeForBand(normalizedBand);
  bandNameInput.value = normalizedBand;
  bandStartInput.value = String(Number(range.start_hz || 0));
  bandEndInput.value = String(Number(range.end_hz || 0));
}

async function applyPreviewBandRange(selectedBand, { syncInputs = false } = {}) {
  const nextBand = String(selectedBand || "").trim();
  if (!nextBand) {
    return;
  }

  const bandRange = getScanRangeForBand(nextBand);
  const bandStartHz = Number(bandRange.start_hz);
  const bandEndHz = Number(bandRange.end_hz);
  if (!(bandStartHz > 0 && bandEndHz > bandStartHz)) {
    return;
  }

  if (bandSelect) {
    const hasOption = Array.from(bandSelect.options || []).some((option) => option.value === nextBand);
    if (hasOption) {
      bandSelect.value = nextBand;
      bandSelect.dispatchEvent(new Event("change"));
    }
  }
  if (syncInputs) {
    syncBandEditorFields(nextBand);
  }

  const newCenterHz = Math.round((bandStartHz + bandEndHz) / 2);
  renderWaterfallRuler(bandStartHz, bandEndHz);
  updateVFODisplay(bandStartHz, bandEndHz);
  lastSpectrumFrame = null;
  clearWaterfallFrame();

  try {
    const resp = await fetch("/api/scan/preview/tune", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify({ center_hz: newCenterHz, band: nextBand, start_hz: bandStartHz, end_hz: bandEndHz })
    });
    if (!resp.ok) {
      const message = await parseApiError(resp, `Failed to tune to ${nextBand}`);
      showToastError(message);
    }
  } catch (err) {
    showToastError(err?.message || `Failed to tune to ${nextBand}`);
  }
}

function getWaterfallFullRangeHz() {
  const frame = lastSpectrumFrame;
  const scanStartHz = Number(frame?.scan_start_hz || 0);
  const scanEndHz = Number(frame?.scan_end_hz || 0);
  const centerHz = Number(frame?.center_hz || 0);
  const spanHz = Number(frame?.span_hz || 0);
  const hasScanRange = Number.isFinite(scanStartHz)
    && Number.isFinite(scanEndHz)
    && scanStartHz > 0
    && scanEndHz > scanStartHz;
  if (hasScanRange) {
    return {
      startHz: scanStartHz,
      spanHz: scanEndHz - scanStartHz,
    };
  }
  if (Number.isFinite(centerHz) && Number.isFinite(spanHz) && centerHz > 0 && spanHz > 0) {
    const fullSpanHz = spanHz * WATERFALL_SEGMENT_COUNT;
    return {
      startHz: centerHz - (fullSpanHz / 2),
      spanHz: fullSpanHz,
    };
  }
  const fallbackBand = bandSelect?.value || "20m";
  const fallbackRange = getScanRangeForBand(fallbackBand);
  const startHz = Number(fallbackRange.start_hz || 0);
  const endHz = Number(fallbackRange.end_hz || 0);
  if (startHz > 0 && endHz > startHz) {
    return {
      startHz,
      spanHz: endHz - startHz,
    };
  }
  return null;
}

function getModeFocusFrequencyHz(mode) {
  const normalizedMode = String(mode || "").trim().toUpperCase();
  const selectedBand = String(bandSelect?.value || "").trim().toLowerCase();
  if (normalizedMode === "CW" || normalizedMode === "CW_CANDIDATE") {
    const cwFocusHz = Number(WATERFALL_CW_FOCUS_FREQUENCIES[selectedBand]);
    if (Number.isFinite(cwFocusHz) && cwFocusHz > 0) {
      return cwFocusHz;
    }
  }
  const bandDialFrequencies = WATERFALL_DIAL_FREQUENCIES[selectedBand] || null;
  if (bandDialFrequencies && Number.isFinite(Number(bandDialFrequencies[normalizedMode]))) {
    return Number(bandDialFrequencies[normalizedMode]);
  }
  const bandRange = getScanRangeForBand(bandSelect?.value || "20m");
  const startHz = Number(bandRange.start_hz || 0);
  const endHz = Number(bandRange.end_hz || 0);
  if (startHz > 0 && endHz > startHz) {
    return Math.round((startHz + endHz) / 2);
  }
  return null;
}

function recenterWaterfallForMode(mode) {
  if (!waterfallExplorerEnabled) {
    waterfallExplorerEnabled = true;
    localStorage.setItem(WATERFALL_EXPLORER_KEY, "1");
  }
  if (waterfallExplorerZoom <= 1) {
    waterfallExplorerZoom = 4;
    localStorage.setItem(WATERFALL_EXPLORER_ZOOM_KEY, "4");
    applyWaterfallExplorerUi();
  }
  if (waterfallExplorerZoom <= 1) {
    return;
  }
  const targetHz = Number(getModeFocusFrequencyHz(mode));
  if (!Number.isFinite(targetHz) || targetHz <= 0) {
    return;
  }
  const fullRange = getWaterfallFullRangeHz();
  if (!fullRange) {
    return;
  }
  const fullStartHz = Number(fullRange.startHz || 0);
  const fullSpanHz = Number(fullRange.spanHz || 0);
  if (!Number.isFinite(fullStartHz) || !Number.isFinite(fullSpanHz) || fullSpanHz <= 0) {
    return;
  }
  const clampedTargetHz = Math.max(fullStartHz, Math.min(fullStartHz + fullSpanHz, targetHz));
  const zoom = Math.max(1, Number(waterfallExplorerZoom || 1));
  const visibleSpanHz = fullSpanHz / zoom;
  const desiredStartHz = clampedTargetHz - (visibleSpanHz / 2);
  const maxPan = Math.max(0, 1 - (1 / zoom));
  waterfallExplorerPan = Math.max(0, Math.min(maxPan, (desiredStartHz - fullStartHz) / fullSpanHz));
  redrawWaterfallFromHistory();
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

  refreshBandEditorOptions();
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

function refreshModeButtons() {
  if (quickModeButtons.length) {
    quickModeButtons.forEach((button) => {
      const buttonMode = String(button.dataset.quickMode || "").trim();
      const isActive = selectedDecoderMode === buttonMode;
      button.disabled = scanActionInFlight;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
  }
  if (cwScanParamsRow) {
    const isCwMode = String(selectedDecoderMode || "").trim().toUpperCase() === "CW";
    cwScanParamsRow.classList.toggle("d-none", !isCwMode);
  }
  renderScanContextSummary(latestScanState);
}

function formatScanRangeSummary(startHz, endHz) {
  const start = Number(startHz || 0);
  const end = Number(endHz || 0);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start <= 0 || end <= start) {
    return "--";
  }
  return `${formatRulerFrequencyLabel(start)} - ${formatRulerFrequencyLabel(end)}`;
}

function resolveActiveBandName(scanState) {
  const stateBand = String(scanState?.scan?.band || "").trim();
  if (stateBand) {
    return stateBand;
  }
  return String(bandSelect?.value || "").trim();
}

function resolveDisplayedScanRange(scanState) {
  const scan = scanState?.scan || null;
  const startHz = Number(scan?.start_hz || 0);
  const endHz = Number(scan?.end_hz || 0);
  if (Number.isFinite(startHz) && Number.isFinite(endHz) && startHz > 0 && endHz > startHz) {
    return { start_hz: startHz, end_hz: endHz };
  }
  const selectedBand = resolveActiveBandName(scanState);
  return getScanRangeForBand(selectedBand);
}

function resolveCwDecoderSegment(scanState) {
  const activeBand = String(resolveActiveBandName(scanState) || "").trim().toLowerCase();
  const subband = CW_DECODER_SUBBANDS[activeBand];
  if (!subband) {
    return null;
  }

  const scanRange = resolveDisplayedScanRange(scanState);
  const clippedStartHz = Math.max(Number(scanRange?.start_hz || 0), subband.start_hz);
  const clippedEndHz = Math.min(Number(scanRange?.end_hz || 0), subband.end_hz);
  if (!Number.isFinite(clippedStartHz) || !Number.isFinite(clippedEndHz) || clippedEndHz <= clippedStartHz) {
    return null;
  }
  return { start_hz: clippedStartHz, end_hz: clippedEndHz };
}

function renderScanContextSummary(scanState) {
  if (scanRangeSummaryEl) {
    const scanRange = resolveDisplayedScanRange(scanState);
    scanRangeSummaryEl.textContent = formatScanRangeSummary(scanRange?.start_hz, scanRange?.end_hz);
  }

  if (!cwSegmentSummaryWrapEl || !cwSegmentSummaryEl) {
    return;
  }

  const isCwMode = String(selectedDecoderMode || "").trim().toUpperCase() === "CW";
  cwSegmentSummaryWrapEl.classList.toggle("d-none", !isCwMode);
  if (!isCwMode) {
    return;
  }

  const cwSegment = resolveCwDecoderSegment(scanState);
  cwSegmentSummaryEl.textContent = cwSegment
    ? formatScanRangeSummary(cwSegment.start_hz, cwSegment.end_hz)
    : "full band";
}

const EVENTS_PANEL_PAGE_SIZE = 50;
let eventOffset = 0;
let eventsPanelPage = 0;
let latestEvents = [];
let row = 0;
let lastSpectrumFrameTs = 0;
let spectrumFallbackTimer = null;
// Circular history buffer — stores raw WS frames so pan/zoom/goto can
// replay the full waterfall instead of resetting to a blank canvas.
const FFT_HISTORY_MAX = 300;
const fftHistoryFrames = [];
let waterfallDragRafPending = false; // rAF gate for drag replay
let spectrumWs = null;
let isScanRunning = false;
let scanActionInFlight = false;
const SHOW_NON_SDR_DEVICES_KEY = "showNonSdrDevices";
let showNonSdrDevices = localStorage.getItem(SHOW_NON_SDR_DEVICES_KEY) === "1";
const WATERFALL_GENERIC_STATUS = "No live spectrum data available. Check SDR device connection and scan status.";
const WATERFALL_SIMULATE_MODE_MARKERS = false;
const WATERFALL_MARKER_TTL_MS = 12000;
const waterfallMarkerCache = new Map();
// Synthetic markers injected from jt9 decoded callsigns.  FT8/FT4 operate
// 15-20 dB below the noise floor so DSP quality gates never fire for them.
// Instead we inject ONE marker per known dial frequency per mode, carrying
// the most-recently decoded callsign.  This avoids flooding the waterfall
// with one marker per decoded station (can be 50-100 per cycle on busy bands).
const WATERFALL_DECODED_MARKER_TTL_MS = 15 * 60 * 1000;
// One decoded-marker entry per "<dialHz>_<MODE>" key.
const waterfallDecodedMarkerCache = new Map();
const WATERFALL_CALLSIGN_TTL_MS = 15 * 60 * 1000;
// Used for DSP-marker to callsign proximity matching (non-decoded modes).
const WATERFALL_CALLSIGN_MAX_DELTA_HZ = 1500;

// Standard dial frequencies for FT8 / FT4 / WSPR, mirrored from the backend.
// Used to snap decoded callsigns to a single marker position per band/mode.
const WATERFALL_DIAL_FREQUENCIES = {
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

const WATERFALL_CW_FOCUS_FREQUENCIES = {
  "160m": 1_830_000,
  "80m": 3_530_000,
  "60m": 5_355_000,
  "40m": 7_030_000,
  "30m": 10_120_000,
  "20m": 14_050_000,
  "17m": 18_086_000,
  "15m": 21_050_000,
  "12m": 24_900_000,
  "10m": 28_050_000,
  "6m": 50_100_000,
  "2m": 144_050_000,
};
// Maximum distance from a decoded freq to a known dial freq for the signal
// to be considered "on that dial".  FT8 audio range is 0-3000 Hz; add 1 kHz
// margin for direct-sampling frequency offset.
const WATERFALL_DIAL_SNAP_HZ = 4000;

function findDialFrequency(frequencyHz, mode) {
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
const waterfallCallsignCache = new Map();
let waterfallLatestCallsign = { callsign: "", seenAtMs: null };
let waterfallHoverTooltip = null;
// Track active hover so the tooltip survives the per-frame overlay redraw.
let _waterfallHoverActive = false;
let _waterfallLastTooltipText = "";
let _waterfallLastTooltipX = 0;
let _waterfallLastTooltipY = 0;
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
if (waterfallExplorerZoom > 1) {
  const maxPan = Math.max(0, 1 - (1 / waterfallExplorerZoom));
  waterfallExplorerPan = maxPan / 2;
}
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

const waterfallTransition = document.getElementById("waterfallTransition");
const waterfallTransitionMsg = document.getElementById("waterfallTransitionMsg");

function showWaterfallTransition(message) {
  if (!waterfallTransition || !waterfallTransitionMsg) return;
  waterfallTransitionMsg.textContent = message;
  waterfallTransition.hidden = false;
}

function hideWaterfallTransition() {
  if (!waterfallTransition) return;
  waterfallTransition.hidden = true;
  if (waterfallTransitionMsg) waterfallTransitionMsg.textContent = "";
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
  // Intentional reset (band change, etc.) — discard accumulated history too
  fftHistoryFrames.length = 0;
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
  if (text === "CW_CANDIDATE") {
    return "CW TRAFFIC";
  }
  return text || "SIG";
}

function modeMatchesSelectedMode(modeValue, selectedModeValue) {
  const mode = String(modeValue || "").trim().toUpperCase();
  const selectedMode = String(selectedModeValue || "").trim().toUpperCase();
  if (!selectedMode) {
    return true;
  }
  if (selectedMode === "CW") {
    return mode === "CW" || mode === "CW_CANDIDATE";
  }
  return mode === selectedMode;
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
  _waterfallHoverActive = false;
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
  _waterfallHoverActive = true;
  _waterfallLastTooltipText = text;
  _waterfallLastTooltipX = clientX;
  _waterfallLastTooltipY = clientY;
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
  
  // Only show markers during active scan with mode selected
  if (!isScanRunning || !selectedDecoderMode) {
    return {
      markers: [],
      rangeStartHz,
      rangeEndHz
    };
  }
  
  const now = Date.now();

  if (Array.isArray(frame?.mode_markers)) {
    const selectedMode = String(selectedDecoderMode).toUpperCase();
    
    frame.mode_markers.forEach((marker) => {
      const markerModeRaw = String(marker?.mode || "").trim().toUpperCase();
      
      // Filter by selected decoder mode - only show markers matching current mode
      if (!modeMatchesSelectedMode(markerModeRaw, selectedMode)) {
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
        mode: markerModeRaw,
        snr_db: Number(marker?.snr_db),
        crest_db: Number(marker?.crest_db),
        seen_at: now
      });
    });
  }

  for (const [key, marker] of waterfallMarkerCache.entries()) {
    if ((now - Number(marker?.seen_at || 0)) > WATERFALL_MARKER_TTL_MS) {
      waterfallMarkerCache.delete(key);
    }
  }

  // Expire stale synthetic (jt9-decoded) markers
  for (const [key, marker] of waterfallDecodedMarkerCache.entries()) {
    if ((now - Number(marker?.seen_at || 0)) > WATERFALL_DECODED_MARKER_TTL_MS) {
      waterfallDecodedMarkerCache.delete(key);
    }
  }

  // Build merged set: DSP markers take precedence; decoded markers fill the
  // gaps (FT8/FT4 operate below the noise floor so DSP gates rarely trigger).
  const mergedMarkerMap = new Map();
  for (const [key, marker] of waterfallDecodedMarkerCache.entries()) {
    mergedMarkerMap.set(key, marker);
  }
  for (const [key, marker] of waterfallMarkerCache.entries()) {
    mergedMarkerMap.set(key, marker); // DSP marker wins when both exist
  }

  const selectedMode = String(selectedDecoderMode).toUpperCase();
  
  const markers = Array.from(mergedMarkerMap.values())
    .filter((marker) => {
      const frequencyHz = Number(marker?.frequency_hz);
      const m = String(marker?.mode || "").toUpperCase();
      
      // Filter by selected decoder mode
      if (!modeMatchesSelectedMode(m, selectedMode)) return false;
      
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
  // Sort by frequency_hz (decoded markers) or offset_hz (DSP markers)
  const sortedMarkers = modeMarkers
    .slice()
    .sort((left, right) => {
      const aFreq = Number(left?.frequency_hz || 0);
      const bFreq = Number(right?.frequency_hz || 0);
      if (aFreq && bFreq) return aFreq - bFreq;
      return Number(left?.offset_hz || 0) - Number(right?.offset_hz || 0);
    });
  const lanes = [[], [], []];

  const hasRange = Number.isFinite(rangeStartHz)
    && Number.isFinite(rangeEndHz)
    && Number(rangeEndHz) > Number(rangeStartHz);
  const safeRangeStartHz = hasRange ? Number(rangeStartHz) : null;
  const safeRangeEndHz = hasRange ? Number(rangeEndHz) : null;

  // For DSP markers (no embedded callsign) fall back to proximity-based lookup.
  // Decoded markers already have .callsign embedded — no lookup needed.
  const callsignMap = assignCallsignsToMarkers(
    sortedMarkers.filter((m) => !m?.decoded)
  );

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
    const crest = Number(marker?.crest_db);
    const markerKey = String(Math.round(markerFreq / 50) * 50);
    // Decoded markers (FT8/FT4 from jt9) have the callsign embedded directly.
    // DSP markers fall back to a proximity-based cache lookup.
    const embeddedCallsign = String(marker?.callsign || "");
    const embeddedSeenAtMs = marker?.seenAtMs || null;
    const proximityMatch = callsignMap.get(markerKey) || { callsign: "", seenAtMs: null };
    const markerCallsign = embeddedCallsign || proximityMatch?.callsign || "";
    const markerModeText = String(marker?.mode || "").trim().toUpperCase();
    const missingCallsignLabel = markerModeText === "CW_CANDIDATE"
      ? "CW TRAFFIC"
      : markerModeText === "CW"
        ? "CW"
        : "-";
    const markerSeenAtText = formatLastSeenTime(embeddedSeenAtMs || proximityMatch?.seenAtMs);
    const isCwMarker = markerModeText === "CW" || markerModeText === "CW_CANDIDATE";
    const freqText = Number.isFinite(markerFreq) && markerFreq > 0
      ? ` | ${(markerFreq / 1_000_000).toFixed(3)} MHz`
      : "";
    const callsignText = markerCallsign
      ? ` | callsign ${markerCallsign}`
      : ` | ${missingCallsignLabel}`;
    const crestText = Number.isFinite(crest) ? ` | Crest ${crest.toFixed(1)} dB` : "";
    const statusText = isCwMarker
      ? `${Number.isFinite(snr) ? ` | SNR(tone) ${snr.toFixed(1)} dB` : " | SNR(tone) -"}${crestText}`
      : ` | last ${markerSeenAtText}`;
    const tooltipText = Number.isFinite(snr)
      ? `${label.textContent}${freqText}${callsignText}${statusText}${isCwMarker ? "" : ` | ${snr.toFixed(1)} dB`}`
      : `${label.textContent}${freqText}${callsignText}${statusText}`;
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
  // Restore tooltip if the user was actively hovering before the per-frame redraw.
  // innerHTML = "" destroys the label elements without firing mouseleave, so
  // _waterfallHoverActive stays true and we can re-show with the saved state.
  if (_waterfallHoverActive && _waterfallLastTooltipText) {
    showWaterfallHoverTooltip(_waterfallLastTooltipText, _waterfallLastTooltipX, _waterfallLastTooltipY);
  }
}

function cacheCallsignByFrequency(callsign, frequencyHz, seenAtMs = Date.now(), mode = "") {
  const normalizedCallsign = String(callsign || "").trim().toUpperCase();
  const numericFrequency = Number(frequencyHz);
  if (!normalizedCallsign || !isValidCallsign(normalizedCallsign)) {
    return;
  }
  if (!Number.isFinite(numericFrequency) || numericFrequency <= 0) {
    return;
  }
  const bucketHz = Math.round(numericFrequency / 50) * 50;
  const normalizedMode = String(mode || "").toUpperCase();
  waterfallCallsignCache.set(String(bucketHz), {
    callsign: normalizedCallsign,
    frequency_hz: numericFrequency,
    seen_at: seenAtMs,
    mode: normalizedMode
  });

  // FT8 / FT4 signals are decoded 15-20 dB below the noise floor, so the DSP
  // quality gate (SNR ≥ 10 dB, min_hits ≥ 2) never fires for them.  Instead,
  // inject ONE synthetic marker per known dial frequency per mode, keeping the
  // MOST RECENT decoded callsign.  This gives a single, stable FT8 and FT4
  // marker on the waterfall (not one per station on a busy band).
  if (normalizedMode !== "FT8" && normalizedMode !== "FT4") {
    return;
  }
  const dialHz = findDialFrequency(numericFrequency, normalizedMode);
  if (!dialHz) {
    return;
  }
  const markerKey = `${dialHz}_${normalizedMode}`;
  const existing = waterfallDecodedMarkerCache.get(markerKey);
  const ts = Number(seenAtMs);
  // Update when: no existing entry, or this decode is the same age or newer
  if (!existing || ts >= Number(existing.seen_at || 0)) {
    waterfallDecodedMarkerCache.set(markerKey, {
      frequency_hz: dialHz,    // anchor at dial freq (band centre), not audio offset
      mode: normalizedMode,
      snr_db: null,
      seen_at: ts,
      callsign: normalizedCallsign,   // *** embedded directly in the marker ***
      seenAtMs: ts,
      decoded: true,
    });
  }
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
  
  // Filter events by selected decoder mode - reject mismatched modes
  const eventMode = String(eventItem.mode || "").toUpperCase();
  if (selectedDecoderMode) {
    const selectedMode = String(selectedDecoderMode).toUpperCase();
    if (!modeMatchesSelectedMode(eventMode, selectedMode)) {
      return; // Ignore events from different decoder modes
    }
  }
  
  const callsign = String(eventItem.callsign || extractCallsignFromRaw(eventItem.raw) || "").trim().toUpperCase();
  const frequencyHz = Number(eventItem.frequency_hz);
  const mode = eventMode;
  const timestampMs = eventItem.timestamp ? Date.parse(eventItem.timestamp) : Date.now();
  const seenAtMs = Number.isFinite(timestampMs) ? timestampMs : Date.now();
  cacheLatestCallsign(callsign, seenAtMs);
  cacheCallsignByFrequency(callsign, frequencyHz, seenAtMs, mode);
  cleanupWaterfallCallsignCache();
}

function updateCallsignCacheFromEvents(items) {
  if (!Array.isArray(items)) {
    return;
  }
  items.forEach((eventItem) => updateCallsignCacheFromEvent(eventItem));
}

/**
 * Build a 1:1 mapping from marker frequency to callsign so that each
 * decoded callsign appears on at most ONE marker tooltip.
 *
 * Algorithm:
 *  1. Collect all (callsign-cache entry, marker) pairs within
 *     WATERFALL_CALLSIGN_MAX_DELTA_HZ and matching mode.
 *  2. Sort pairs by frequency delta (closest first).
 *  3. Greedily assign: if neither the cache entry nor the marker
 *     has been used yet, link them.
 *
 * Returns a Map<roundedMarkerFreq, {callsign, seenAtMs}>.
 */
function assignCallsignsToMarkers(markers) {
  cleanupWaterfallCallsignCache();
  const result = new Map();
  if (!Array.isArray(markers) || !markers.length) {
    return result;
  }

  // Build candidate pairs
  const pairs = [];
  const cacheEntries = Array.from(waterfallCallsignCache.values());
  for (const marker of markers) {
    const mFreq = Number(marker?.frequency_hz);
    const mMode = String(marker?.mode || "").toUpperCase();
    if (!Number.isFinite(mFreq) || mFreq <= 0) continue;
    for (const entry of cacheEntries) {
      const eFreq = Number(entry?.frequency_hz);
      const eMode = String(entry?.mode || "").toUpperCase();
      const eCall = String(entry?.callsign || "");
      if (!eCall) continue;
      if (!Number.isFinite(eFreq) || eFreq <= 0) continue;
      if (mMode && eMode && eMode !== mMode) continue;
      const delta = Math.abs(eFreq - mFreq);
      if (delta > WATERFALL_CALLSIGN_MAX_DELTA_HZ) continue;
      pairs.push({
        markerKey: String(Math.round(mFreq / 50) * 50),
        callsign: eCall,
        seenAt: Number(entry?.seen_at || 0),
        delta,
        entryKey: String(Math.round(eFreq / 50) * 50),
      });
    }
  }

  // Sort: smallest delta first; break ties by newest decode
  pairs.sort((a, b) => a.delta - b.delta || b.seenAt - a.seenAt);

  const usedMarkers = new Set();
  const usedCallsigns = new Set();
  for (const p of pairs) {
    if (usedMarkers.has(p.markerKey)) continue;
    if (usedCallsigns.has(p.callsign)) continue;
    usedMarkers.add(p.markerKey);
    usedCallsigns.add(p.callsign);
    result.set(p.markerKey, {
      callsign: p.callsign,
      seenAtMs: Number.isFinite(p.seenAt) ? p.seenAt : null,
    });
  }
  return result;
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

  // Filter simulated markers by selected decoder mode
  if (!selectedDecoderMode) {
    return []; // No mode selected, show no markers
  }
  
  const selectedMode = String(selectedDecoderMode || "").toUpperCase();
  
  // Generate markers only for the selected mode
  switch (selectedMode) {
    case "FT8":
    case "FT4":
      return buildModeSet(selectedMode, 10, 8.0, 0.0, 1.0);
    case "CW":
      return buildModeSet("CW", 20, 10.0, 0.0, 1.0);
    case "SSB":
      return buildModeSet("SSB", 30, 12.0, 0.0, 1.0);
    case "WSPR":
      return buildModeSet("WSPR", 8, 6.0, 0.0, 1.0);
    case "APRS":
      return buildModeSet("APRS", 12, 9.0, 0.0, 1.0);
    default:
      return [];
  }
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
  if (!frontendLogsEl) {
    return;
  }
  const current = frontendLogsEl.textContent === "No frontend logs yet." ? "" : frontendLogsEl.textContent;
  frontendLogsEl.textContent = `${new Date().toISOString()} ${text}\n${current}`.trim();
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

  // Auto-dismiss informational toasts after 5 seconds
  // Error toasts remain until manually closed
  if (!isError) {
    setTimeout(() => {
      if (noticeEl.parentNode) {
        noticeEl.remove();
      }
    }, 5000);
  }
}

function showToast(message) {
  renderToast(message, false);
}

function showToastError(message) {
  renderToast(message, true);
  logLine(message);
}

function showRetentionToast(info) {
  if (!toast) return;

  const MAX_TOAST_NOTICES = 5;
  while (toast.childElementCount >= MAX_TOAST_NOTICES) {
    const oldest = toast.firstElementChild;
    if (!oldest) break;
    oldest.remove();
  }

  const noticeEl = document.createElement("div");
  noticeEl.className = "toast-notice retention";

  const msgEl = document.createElement("span");
  msgEl.className = "toast__message";
  const rows = info.export_rows ?? info.purged ?? 0;
  msgEl.textContent = `Database: ${rows.toLocaleString()} events automatically exported and purged.`;

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "toast__close";
  closeBtn.textContent = "×";
  closeBtn.setAttribute("aria-label", "Close notification");
  closeBtn.addEventListener("click", () => noticeEl.remove());

  noticeEl.appendChild(msgEl);

  if (info.download_url) {
    const dlBtn = document.createElement("a");
    dlBtn.className = "toast__download";
    dlBtn.href = info.download_url;
    dlBtn.download = "";
    dlBtn.textContent = "Download CSV";
    noticeEl.appendChild(dlBtn);
  }

  noticeEl.appendChild(closeBtn);
  toast.appendChild(noticeEl);
  logLine(`[Retention] ${rows} events exported and purged.`);
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

function extractDecodedText(eventItem) {
  if (!eventItem || typeof eventItem !== "object") {
    return "";
  }
  const candidates = [eventItem.msg, eventItem.text];
  for (const candidate of candidates) {
    const value = String(candidate || "").trim();
    if (value) {
      return value.length > 220 ? `${value.slice(0, 220)}…` : value;
    }
  }
  return "";
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

function getAuthHeader() {
  return {};
}

function updateLoginStatus() {
  const user = window.__authUser || "";
  loginStatus.textContent = user ? `Auth: ${user}` : "Auth: guest";
  const logoutBtn = document.getElementById("logoutBtn");
  if (logoutBtn) logoutBtn.classList.toggle("d-none", !user);
}

function setAuthFields(authConfig = {}) {
  if (!authUserInput || !authPassInput) {
    return;
  }

  const enabled = Boolean(authConfig?.enabled);
  const user = String(authConfig?.user || "").trim();
  const hasStoredPassword = Boolean(authConfig?.password_configured);

  authUserInput.value = enabled ? user : "";
  authPassInput.value = enabled && hasStoredPassword ? AUTH_PASSWORD_MASK : "";
  authPassInput.dataset.masked = enabled && hasStoredPassword ? "1" : "0";
  authPassInput.placeholder = enabled && hasStoredPassword
    ? "Stored password hidden. Type a new one to replace it."
    : "";
}

function deriveAuthConfigFromStatus(statusData = {}) {
  const enabled = Boolean(statusData?.auth_required);
  const user = String(statusData?.user || window.__authUser || "").trim();
  return {
    enabled,
    user,
    password_configured: enabled,
  };
}

async function refreshAdminAuthFields() {
  try {
    const resp = await fetch("/api/auth/status");
    if (!resp.ok) {
      return null;
    }
    const data = await resp.json();
    window.__authUser = data.user || "";
    setAuthFields(deriveAuthConfigFromStatus(data));
    return data;
  } catch (_) {
    return null;
  }
}

async function updateAuthStatusBadge() {
  if (!authStatusBadge) return;
  try {
    const resp = await fetch("/api/auth/status");
    const data = await resp.json();
    window.__authUser = data.user || "";
    updateLoginStatus();
    setAuthFields(deriveAuthConfigFromStatus(data));
    if (data.auth_required) {
      const src = data.env_locked ? " (env)" : "";
      const stateLabel = data.authenticated ? "session" : "login required";
      authStatusBadge.textContent = `Auth ON${src} · ${stateLabel}`;
      authStatusBadge.className = "badge bg-success ms-1";
    } else {
      authStatusBadge.textContent = "Auth OFF";
      authStatusBadge.className = "badge bg-secondary ms-1";
    }
    return data;
  } catch (_) {
    window.__authUser = "";
    updateLoginStatus();
    authStatusBadge.textContent = "unknown";
    authStatusBadge.className = "badge bg-warning ms-1";
    return null;
  }
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
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
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
  latestEvents = [eventPayload, ...latestEvents];
  renderEventsPanelFromCache();
  
  // Update fullscreen modal if it's open
  if (eventsFullscreenModal && eventsFullscreenModal.classList.contains('show')) {
    renderEventsFullscreen();
  }
}

function applyEventsPanelFilters(items) {
  const callsignTerm = (eventsSearchCallsignInput?.value || "").trim().toLowerCase();
  const modeTerm = (eventsSearchModeInput?.value || "").trim().toLowerCase();
  const bandTerm = (eventsSearchBandInput?.value || "").trim().toLowerCase();
  return items.filter((eventItem) => {
    const callsignText = String(eventItem.callsign || "").toLowerCase();
    const modeText = String(eventItem.mode || "").toLowerCase();
    const bandText = String(eventItem.band || "").toLowerCase();
    if (callsignTerm && !callsignText.includes(callsignTerm)) {
      return false;
    }
    if (modeTerm && !modeText.includes(modeTerm)) {
      return false;
    }
    if (bandTerm && !bandText.includes(bandTerm)) {
      return false;
    }
    return true;
  });
}

function applyEventsCardTypeFilter(items) {
  const source = Array.isArray(items) ? items : [];
  const selected = String(eventsTypeFilter?.value || "all").trim();
  if (selected === "cw-candidate") {
    return source.filter((eventItem) => String(eventItem?.mode || "").trim().toUpperCase() === "CW_CANDIDATE");
  }
  if (selected === "cw-only") {
    return source.filter((eventItem) => String(eventItem?.mode || "").trim().toUpperCase() === "CW");
  }
  if (selected === "callsign-only") {
    return source.filter((eventItem) => {
      const callsignText = String(eventItem?.callsign || extractCallsignFromRaw(eventItem?.raw) || "").trim();
      return callsignText.length > 0;
    });
  }
  return source;
}

function hasEventsSearchCriteria() {
  return Boolean(
    (eventsSearchCallsignInput?.value || "").trim()
    || (eventsSearchModeInput?.value || "").trim()
    || (eventsSearchBandInput?.value || "").trim()
    || (eventsSearchSnrMinInput?.value || "").trim()
  );
}

let _eventsSearchTimer = null;
let _eventsSearchAbort = null;

let _searchResultsCache = [];
let _searchPage = 0;
const SEARCH_PAGE_SIZE = 50;

function renderSearchPage() {
  const totalPages = Math.max(1, Math.ceil(_searchResultsCache.length / SEARCH_PAGE_SIZE));
  if (_searchPage >= totalPages) _searchPage = totalPages - 1;
  if (_searchPage < 0) _searchPage = 0;
  const start = _searchPage * SEARCH_PAGE_SIZE;
  const pageItems = _searchResultsCache.slice(start, start + SEARCH_PAGE_SIZE);
  renderEventList(eventsSearchResultsEl, pageItems, "No events match the current Events search.");
  if (eventsSearchPageInfoEl) {
    eventsSearchPageInfoEl.textContent = _searchResultsCache.length > 0
      ? `Page ${_searchPage + 1}/${totalPages}`
      : "";
  }
  if (eventsSearchPrevBtn) eventsSearchPrevBtn.disabled = _searchPage <= 0;
  if (eventsSearchNextBtn) eventsSearchNextBtn.disabled = _searchPage >= totalPages - 1;
}

function scheduleEventsSearch() {
  _searchPage = 0;
  clearTimeout(_eventsSearchTimer);
  _eventsSearchTimer = setTimeout(fetchAndRenderSearchResults, 400);
}

async function fetchAndRenderSearchResults() {
  if (!eventsSearchResultsEl) return;
  const callsign = (eventsSearchCallsignInput?.value || "").trim();
  const mode     = (eventsSearchModeInput?.value     || "").trim();
  const band     = (eventsSearchBandInput?.value     || "").trim();
  const snrMin   = (eventsSearchSnrMinInput?.value   || "").trim();
  const start    = (eventsSearchStartInput?.value    || "").trim();
  const end      = (eventsSearchEndInput?.value      || "").trim();

  if (!callsign && !mode && !band && !snrMin && !start && !end) {
    if (eventsSearchCountEl) eventsSearchCountEl.textContent = "";
    renderEventList(eventsSearchResultsEl, [], "Use search fields to display results.");
    return;
  }

  // Cancel any in-flight request to avoid stale results overwriting newer ones
  if (_eventsSearchAbort) {
    _eventsSearchAbort.abort();
    _eventsSearchAbort = null;
  }
  const controller = new AbortController();
  _eventsSearchAbort = controller;

  if (eventsSearchCountEl) eventsSearchCountEl.textContent = "";
  renderEventList(eventsSearchResultsEl, [], "Searching\u2026");

  const params = new URLSearchParams({ limit: "500" });
  if (callsign) params.set("callsign", callsign);
  if (mode)     params.set("mode", mode);
  if (band)     params.set("band", band);
  if (snrMin !== "") params.set("snr_min", snrMin);
  const startISO = start.length === 10 ? (() => { const [d,m,y] = start.split("/"); const dt = new Date(`${y}-${m}-${d}T00:00:00`); return isNaN(dt) ? "" : dt.toISOString(); })() : "";
  const endISO   = end.length   === 10 ? (() => { const [d,m,y] = end.split("/");   const dt = new Date(`${y}-${m}-${d}T23:59:59`); return isNaN(dt) ? "" : dt.toISOString(); })() : "";
  if (startISO) params.set("start", startISO);
  if (endISO)   params.set("end",   endISO);

  try {
    const resp = await fetch(`/api/events?${params.toString()}`, {
      headers: { ...getAuthHeader() },
      signal: controller.signal
    });
    // If superseded by a newer search, discard silently
    if (_eventsSearchAbort !== controller) return;
    _eventsSearchAbort = null;

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    let data = await resp.json();

    // Search only shows callsign events
    data = data.filter(e => e.type === "callsign");

    _searchResultsCache = data;
    if (eventsSearchCountEl) {
      eventsSearchCountEl.textContent = data.length === 0 ? "" : `${data.length} result${data.length === 1 ? "" : "s"}`;
    }
    renderSearchPage();
  } catch (err) {
    if (err.name === "AbortError") return; // superseded by newer search
    _eventsSearchAbort = null; // reset so next search starts clean
    _searchResultsCache = [];
    if (eventsSearchPrevBtn) eventsSearchPrevBtn.disabled = true;
    if (eventsSearchNextBtn) eventsSearchNextBtn.disabled = true;
    if (eventsSearchPageInfoEl) eventsSearchPageInfoEl.textContent = "";
    renderEventList(eventsSearchResultsEl, [], "Search error. Try again.");
  }
}

function updateEventsPager(totalItems) {
  const totalLocalPages = Math.max(1, Math.ceil(totalItems / EVENTS_PANEL_PAGE_SIZE));
  if (eventsPageInfo) {
    const globalPage = Math.floor(eventOffset / EVENTS_PANEL_PAGE_SIZE) + eventsPanelPage + 1;
    const totalGlobalPages = totalEventsInDB > 0
      ? Math.ceil(totalEventsInDB / EVENTS_PANEL_PAGE_SIZE)
      : totalLocalPages;
    eventsPageInfo.textContent = `Page: ${globalPage}/${totalGlobalPages}`;
  }
  if (eventsPrevBtn) {
    eventsPrevBtn.disabled = eventsPanelPage <= 0 && eventOffset <= 0;
  }
  if (eventsNextBtn) {
    const moreServerEvents = totalEventsInDB > eventOffset + latestEvents.length;
    eventsNextBtn.disabled = eventsPanelPage >= totalLocalPages - 1 && !moreServerEvents;
  }
}

function renderEventsPanelFromCache() {
  renderEvents(latestEvents);
}

function orderEventsForDisplay(items) {
  const source = Array.isArray(items) ? items.slice() : [];
  source.sort((a, b) => {
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
    modeBadge.textContent = normalizeModeLabel(eventItem.mode || "Unknown");

    const timeStamp = document.createElement("span");
    const timeText = eventItem.timestamp ? new Date(eventItem.timestamp).toLocaleString("pt-PT", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) : "--";
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
    const callsign = eventItem.callsign || extractCallsignFromRaw(eventItem.raw) || "NO CALLSIGN DETECTED";
    const decodedText = extractDecodedText(eventItem);

    const frequencyEl = document.createElement("strong");
    frequencyEl.textContent = `${freq} Hz`;

    const bandEl = document.createElement("span");
    bandEl.className = "event-item__muted";
    bandEl.textContent = band;

    body.appendChild(frequencyEl);
    body.appendChild(bandEl);

    if (decodedText) {
      const decodedBtn = document.createElement("button");
      decodedBtn.type = "button";
      decodedBtn.className = "event-decoded-help";
      decodedBtn.textContent = "TXT";
      decodedBtn.setAttribute("data-tooltip", decodedText);
      decodedBtn.setAttribute("aria-label", `Decoded text: ${decodedText}`);
      body.appendChild(decodedBtn);
    }

    const callsignEl = document.createElement("span");
    callsignEl.className = "event-item__call";
    callsignEl.textContent = callsign;
    body.appendChild(callsignEl);

    const detail = document.createElement("div");
    detail.className = "event-item__detail";
    if (eventItem.mode === "APRS") {
      const latValue = Number(eventItem.lat);
      const lonValue = Number(eventItem.lon);
      const lat = Number.isFinite(latValue) ? latValue.toFixed(3) : "--";
      const lon = Number.isFinite(lonValue) ? lonValue.toFixed(3) : "--";
      detail.textContent = `path=${eventItem.path || "-"} | lat=${lat} lon=${lon} | ${eventItem.msg || eventItem.payload || ""}`.trim();
    } else if (eventItem.type === "callsign") {
      const isCwMode = String(eventItem.mode || "").toUpperCase() === "CW";
      const snrValue = Number(eventItem.snr_db);
      const crestValue = Number(eventItem.crest_db);
      const rawPowerValue = eventItem.power_dbm;
      const powerValue =
        rawPowerValue === null || rawPowerValue === undefined || rawPowerValue === ""
          ? NaN
          : Number(rawPowerValue);
      const snrLabel = isCwMode ? "SNR(tone)" : "SNR";
      const snrText = Number.isFinite(snrValue) ? `${snrLabel} ${snrValue >= 0 ? "+" : ""}${snrValue.toFixed(1)} dB` : null;
      const crestText = Number.isFinite(crestValue) ? `Crest ${crestValue.toFixed(1)} dB` : null;
      const powerText = Number.isFinite(powerValue) ? `PWR ${powerValue.toFixed(1)} dBm` : null;
      const detailParts = isCwMode
        ? [snrText, crestText, powerText]
        : [snrText, powerText];
      detail.textContent = detailParts.filter(Boolean).join(" | ");
    } else if (eventItem.type === "occupancy") {
      const isCwMode = String(eventItem.mode || "").toUpperCase() === "CW";
      const bw = eventItem.bandwidth_hz ? `${eventItem.bandwidth_hz} Hz` : "-";
      const snrValue = Number(eventItem.snr_db);
      const crestValue = Number(eventItem.crest_db);
      const rawPowerValue = eventItem.power_dbm;
      const powerValue =
        rawPowerValue === null || rawPowerValue === undefined || rawPowerValue === ""
          ? NaN
          : Number(rawPowerValue);
      const snr = Number.isFinite(snrValue) ? `${snrValue.toFixed(1)} dB` : "-";
      const crest = Number.isFinite(crestValue) ? `${crestValue.toFixed(1)} dB` : "-";
      const pwr = Number.isFinite(powerValue) ? `pwr=${powerValue.toFixed(1)} dBm` : null;
      const detailParts = isCwMode
        ? [`bw=${bw}`, `snr(tone)=${snr}`, `crest=${crest}`, pwr]
        : [`bw=${bw}`, `snr=${snr}`, pwr];
      detail.textContent = detailParts.filter(Boolean).join(" ");
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
  const cardItems = applyEventsCardTypeFilter(orderedEvents);
  const totalEventPages = Math.max(1, Math.ceil(cardItems.length / EVENTS_PANEL_PAGE_SIZE));
  if (eventsPanelPage > totalEventPages - 1) {
    eventsPanelPage = totalEventPages - 1;
  }
  if (eventsPanelPage < 0) {
    eventsPanelPage = 0;
  }
  const eventsStartIndex = eventsPanelPage * EVENTS_PANEL_PAGE_SIZE;
  const eventsPagedItems = cardItems.slice(eventsStartIndex, eventsStartIndex + EVENTS_PANEL_PAGE_SIZE);

  renderEventList(
    eventsEl,
    eventsPagedItems,
    "No events yet. Start a scan or adjust filters."
  );

  const filteredItems = applyEventsPanelFilters(orderedEvents);

  if (eventsCardTitle) {
    const displayTotal = totalEventsInDB > 0 ? totalEventsInDB : totalEvents;
    const titleTarget = eventsCardTitleText || eventsCardTitle;
    titleTarget.textContent = `Events (${displayTotal.toLocaleString()} — last 24h)`;
  }
  updateEventsPager(cardItems.length);

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
  
  // Update fullscreen modal if it's open
  if (eventsFullscreenModal && eventsFullscreenModal.classList.contains('show')) {
    renderEventsFullscreen();
  }
}

let _fetchEventsAbort = null;
let _fetchEventsVersion = 0;

async function fetchEvents() {
  // Increment version — any older in-flight call that completes will be discarded
  _fetchEventsVersion++;
  const myVersion = _fetchEventsVersion;

  // Cancel any in-flight request
  if (_fetchEventsAbort) {
    _fetchEventsAbort.abort();
    _fetchEventsAbort = null;
  }
  const controller = new AbortController();
  _fetchEventsAbort = controller;

  try {
    // Card Events shows events from the last 24 hours
    const start24h = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
    const params = new URLSearchParams({ offset: String(eventOffset), limit: "200", start: start24h, end: new Date().toISOString() });
    
    const resp = await fetch(`/api/events?${params.toString()}`, {
      headers: { ...getAuthHeader() },
      signal: controller.signal
    });
    // Discard if a newer call has already started
    if (myVersion !== _fetchEventsVersion) return;
    _fetchEventsAbort = null;

    if (resp.status === 401) {
      showToastError("Authentication failed");
      return;
    }
    const data = await resp.json();
    // Discard if superseded while parsing JSON
    if (myVersion !== _fetchEventsVersion) return;

    renderEvents(data);
  } catch (err) {
    if (err.name === "AbortError") return; // superseded by newer request
    _fetchEventsAbort = null;
    addEvent("Failed to load events");
  }
}

async function fetchTotal() {
  try {
    // Count only events from the last 24 hours
    const start24h = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
    const params = new URLSearchParams({ start: start24h, end: new Date().toISOString() });
    
    const resp = await fetch(`/api/events/count?${params.toString()}`, {
      headers: { ...getAuthHeader() }
    });
    if (!resp.ok) {
      return;
    }
    const data = await resp.json();
    totalEventsInDB = Number(data.count || 0);
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
    // totalEventsInDB is managed by fetchTotal() (counts events from last 24h)
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
  propagationScore.className = "";
  const stateColorClass = { "Excellent": "text-success", "Good": "text-success", "Fair": "text-warning", "Poor": "text-danger" }[overallState] || "text-secondary";
  propagationScore.classList.add("fw-semibold", stateColorClass);

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
    const primaryWindowMinutes = 60;
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
    const resp = await fetch("/api/logs?limit=500", { headers: { ...getAuthHeader() } });
    if (!resp.ok) {
      return;
    }
    const data = await resp.json();
    if (frontendLogsOpsEl) {
      frontendLogsOpsEl.textContent = data.length ? data.join("\n") : "No app operations yet.";
    }
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
          if (frontendLogsOpsEl) {
            frontendLogsOpsEl.textContent = data.logs.length ? data.logs.join("\n") : "No app operations yet.";
          }
        }
      } catch (err) {
        return;
      }
    };
  } catch (err) {
    return;
  }
}

async function fetchFileLog() {
  try {
    const resp = await fetch("/api/logs/file?limit=2000", { headers: { ...getAuthHeader() } });
    if (!resp.ok) {
      return;
    }
    const data = await resp.json();
    if (serverLogsEl) {
      serverLogsEl.textContent = data.length ? data.join("\n") : "No server logs yet.";
    }
  } catch (err) {
    return;
  }
}

(function initServerLogsExport() {
  const btn = document.getElementById("exportServerLogsBtn");
  if (!btn) {
    return;
  }
  btn.addEventListener("click", async () => {
    try {
      const resp = await fetch("/api/logs/file?limit=2000", { headers: { ...getAuthHeader() } });
      if (!resp.ok) {
        return;
      }
      const data = await resp.json();
      const blob = new Blob([data.join("\n")], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `backend_${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}.log`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      return;
    }
  });
})();

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
  refreshModeButtons();
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
  // Validate decoder mode is selected
  if (!selectedDecoderMode) {
    showToast("⚠️ Select the desired mode before starting the scan");
    return;
  }

  setStatus("Starting scan...");
  const gain = Number(gainInput.value);
  const selectedDeviceId = deviceSelect.value || null;
  const sampleRate = normalizeScanSampleRate(selectedDeviceId, sampleRateInput.value);
  if (Number(sampleRateInput.value) !== sampleRate) {
    sampleRateInput.value = String(sampleRate);
    showToast(`Sample rate automatically adjusted to ${sampleRate} Hz`);
  }
  const recordPath = recordPathInput.value || null;
  const selectedBand = bandSelect.value;
  const range = getScanRangeForBand(selectedBand);
  const decoderModeToSend = selectedDecoderMode ? selectedDecoderMode.toLowerCase() : "";
  const requestPayload = {
    device: selectedDeviceId,
    decoder_mode: decoderModeToSend,
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
  };
  if (decoderModeToSend === "cw") {
    const cwStepHzValue = Number(cwStepHzInput?.value);
    const cwDwellSValue = Number(cwDwellSInput?.value);
    requestPayload.cw_step_hz = Number.isFinite(cwStepHzValue)
      ? Math.max(1000, Math.round(cwStepHzValue))
      : 6500;
    requestPayload.cw_dwell_s = Number.isFinite(cwDwellSValue)
      ? Math.max(0.5, cwDwellSValue)
      : 30.0;
  }
  const response = await fetch("/api/scan/start", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeader() },
    body: JSON.stringify(requestPayload)
  });
  if (!response.ok) {
    const message = await parseApiError(response, "Failed to start scan");
    throw new Error(message);
  }
  isScanRunning = true;
  setStatus("Scan running");
  logLine("Scan started");
  // Sync the events filter with the selected decoder mode so only
  // events from this mode appear in the panel.
  if (selectedDecoderMode) {
    recenterWaterfallForMode(selectedDecoderMode);
    eventsSearchModeInput.value = selectedDecoderMode;
    fetchEvents();
    fetchTotal();
  }
}

async function stopScan() {
  setStatus("Stopping scan...");
  const response = await fetch("/api/scan/stop", { method: "POST", headers: { ...getAuthHeader() } });
  if (!response.ok) {
    const message = await parseApiError(response, "Failed to stop scan");
    throw new Error(message);
  }
  isScanRunning = false;
  
  // Clear waterfall marker caches when scan stops
  waterfallMarkerCache.clear();
  waterfallDecodedMarkerCache.clear();
  waterfallCallsignCache.clear();
  latestEvents = []; // Clear events list
  renderEventsPanelFromCache(); // Refresh empty panel
  
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
    latestScanState = data;
    const nextRunning = data?.state === "running";
    const isPreview = data?.state === "preview";
    if (!scanActionInFlight) {
      const wasRunning = isScanRunning;
      isScanRunning = nextRunning;
      setStatus(nextRunning ? "Scan running" : isPreview ? "Monitor mode" : "Scan stopped");
      updateScanButtonState();
      if (!wasRunning && nextRunning && selectedDecoderMode) {
        recenterWaterfallForMode(selectedDecoderMode);
      }
      // Deselect mode button when scan transitions running → stopped
      if (wasRunning && !nextRunning && selectedDecoderMode) {
        selectedDecoderMode = null;
        refreshModeButtons();
      }
    }
    // Restore selectedDecoderMode from backend state (handles page refresh mid-scan)
    // Only sync when a scan is actually running — when stopped, the stale
    // decoder_mode in scan_state should not force a button selection.
    const backendMode = String(data?.decoder_mode || "").trim().toUpperCase();
    if (nextRunning && backendMode && backendMode !== selectedDecoderMode) {
      selectedDecoderMode = backendMode;
      recenterWaterfallForMode(backendMode);
      refreshModeButtons();
      // Sync the events panel filter with the restored mode
      if (eventsSearchModeInput.value !== backendMode) {
        eventsSearchModeInput.value = backendMode;
        fetchEvents();
        fetchTotal();
      }
    }
    renderScanContextSummary(data);
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
    if (bandNameInput && bandNameInput.value !== nextBand) {
      syncBandEditorFields(nextBand);
    }
    refreshQuickBandButtons();
    return;
  }

  bandSelect.value = nextBand;
  bandSelect.dispatchEvent(new Event("change"));

  if (scanActionInFlight) {
    return;
  }

  if (!isScanRunning) {
    await applyPreviewBandRange(nextBand, { syncInputs: true });
    return;
  }

  // Scan running: stop and restart on the new band
  scanActionInFlight = true;
  updateScanButtonState();
  showWaterfallTransition(`Switching to band ${nextBand}...`);

  try {
    await stopScan();
    // Clear the old band's frame so getWaterfallFullRangeHz() falls back to
    // the new band's range when recenterWaterfallForMode runs inside startScan()
    lastSpectrumFrame = null;
    lastSpectrumFrameTs = 0;
    clearWaterfallFrame();
    await startScan();
    showToast(`Band switched to ${nextBand}`);
  } catch (err) {
    showToastError(err?.message || "Failed to switch band live");
  } finally {
    hideWaterfallTransition();
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

/**
 * Dedicated unfiltered fetch to populate the waterfall callsign cache.
 * Runs independently of the events panel so filters (band / mode / callsign
 * dropdowns) never starve the waterfall tooltips of decoded callsigns.
 */
async function fetchCallsignCacheUpdate() {
  try {
    const modeParam = selectedDecoderMode
      ? `&mode=${encodeURIComponent(String(selectedDecoderMode).toUpperCase())}`
      : "";
    const resp = await fetch(`/api/events?limit=300${modeParam}`, {
      headers: { ...getAuthHeader() }
    });
    if (!resp.ok) return;
    const data = await resp.json();
    const items = Array.isArray(data) ? data : [];
    // Only feed callsign-type events (jt9/wsprd decodes) into the cache
    const callsignEvents = items.filter((e) =>
      e && e.type === "callsign" && e.callsign && e.frequency_hz
    );
    updateCallsignCacheFromEvents(callsignEvents);
  } catch (_) {
    // silently ignore — waterfall cache is best-effort
  }
}
fetchCallsignCacheUpdate();
setInterval(fetchCallsignCacheUpdate, 5000);

/**
 * Debug helper — call window._debugWaterfall() from the browser console
 * to inspect both waterfall caches and diagnose tooltip issues.
 */
window._debugWaterfall = function () {
  console.group("=== waterfall callsign cache (exact-freq buckets) ===");
  if (waterfallCallsignCache.size === 0) {
    console.warn("  (empty)");
  } else {
    for (const [k, v] of waterfallCallsignCache.entries()) {
      console.log(`  ${k}: ${v.callsign}  mode=${v.mode}  freq=${v.frequency_hz}  age=${Math.round((Date.now() - v.seen_at) / 1000)}s`);
    }
  }
  console.groupEnd();
  console.group("=== waterfall decoded marker cache (one per dial-freq/mode) ===");
  if (waterfallDecodedMarkerCache.size === 0) {
    console.warn("  (empty — no jt9 decodes yet, or all expired)");
  } else {
    for (const [k, v] of waterfallDecodedMarkerCache.entries()) {
      console.log(`  ${k}: callsign=${v.callsign}  dialFreq=${v.frequency_hz} Hz  mode=${v.mode}  age=${Math.round((Date.now() - v.seen_at) / 1000)}s`);
    }
  }
  console.groupEnd();
  console.group("=== waterfall DSP marker cache ===");
  if (waterfallMarkerCache.size === 0) {
    console.warn("  (empty — DSP quality gate has not fired yet)");
  } else {
    for (const [k, v] of waterfallMarkerCache.entries()) {
      console.log(`  ${k}: mode=${v.mode}  freq=${v.frequency_hz}  snr=${v.snr_db}  age=${Math.round((Date.now() - v.seen_at) / 1000)}s`);
    }
  }
  console.groupEnd();
  console.log("WATERFALL_CALLSIGN_MAX_DELTA_HZ (DSP fallback) =", WATERFALL_CALLSIGN_MAX_DELTA_HZ);
  // Show what markers would be rendered right now
  const last = window._lastSpectrumFrame || lastSpectrumFrame;
  if (last) {
    const built = buildStableWaterfallMarkers(last);
    console.group(`=== built markers (${built.markers.length}) for range ${built.rangeStartHz}-${built.rangeEndHz} Hz ===`);
    for (const m of built.markers) {
      console.log(`  ${m.mode}  ${m.frequency_hz} Hz  callsign=${m.callsign || "(DSP, no callsign)"}  decoded=${!!m.decoded}`);
    }
    console.groupEnd();
  } else {
    console.warn("No spectrum frame received yet — cannot compute built markers.");
  }
};

function resetEventsPagination() {
  eventOffset = 0;
  eventsPanelPage = 0;
}

function handleEventsFilterChange() {
  resetEventsPagination();
  fetchEvents();
  fetchTotal();
}

// REMOVED: Export filters no longer affect Card Events
// Event listeners for export filters removed

if (eventsSearchCallsignInput) {
  eventsSearchCallsignInput.addEventListener("input", () => {
    eventsPanelPage = 0;
    renderEventsPanelFromCache();
  });
}

if (eventsSearchModeInput) {
  eventsSearchModeInput.addEventListener("change", () => {
    eventsPanelPage = 0;
    scheduleEventsSearch();
  });
}

if (eventsSearchBandInput) {
  eventsSearchBandInput.addEventListener("change", () => {
    eventsPanelPage = 0;
    scheduleEventsSearch();
  });
}

if (eventsSearchSnrMinInput) {
  eventsSearchSnrMinInput.addEventListener("input", () => {
    eventsPanelPage = 0;
    scheduleEventsSearch();
  });
}

if (eventsPrevBtn) {
  eventsPrevBtn.addEventListener("click", () => {
    if (eventsPanelPage > 0) {
      eventsPanelPage = Math.max(0, eventsPanelPage - 1);
      renderEventsPanelFromCache();
    } else if (eventOffset > 0) {
      // At start of local window — load previous server batch
      eventOffset = Math.max(0, eventOffset - 200);
      eventsPanelPage = 0;
      fetchEvents();
    }
  });
}

if (eventsNextBtn) {
  eventsNextBtn.addEventListener("click", () => {
    const orderedItems = orderEventsForDisplay(latestEvents);
    const filteredItems = applyEventsCardTypeFilter(orderedItems);
    const totalLocalPages = Math.max(1, Math.ceil(filteredItems.length / EVENTS_PANEL_PAGE_SIZE));
    if (eventsPanelPage < totalLocalPages - 1) {
      // Still pages left in the current local window
      eventsPanelPage = Math.min(totalLocalPages - 1, eventsPanelPage + 1);
      renderEventsPanelFromCache();
    } else if (totalEventsInDB > eventOffset + latestEvents.length) {
      // Reached end of local window — load next server batch
      eventOffset += 200;
      eventsPanelPage = 0;
      fetchEvents();
    }
  });
}

if (eventsTypeFilter) {
  eventsTypeFilter.addEventListener("change", () => {
    eventsPanelPage = 0;
    renderEventsPanelFromCache();
  });
}

// ══════════════════════════════════════════════════════════════════
// Events Fullscreen Modal
// ══════════════════════════════════════════════════════════════════

let eventsFullscreenPage = 0;

function renderEventsFullscreen() {
  const sourceItems = latestEvents || [];
  const orderedEvents = orderEventsForDisplay(sourceItems);
  const cardItems = applyEventsCardTypeFilter(orderedEvents);
  const totalPages = Math.max(1, Math.ceil(cardItems.length / EVENTS_PANEL_PAGE_SIZE));
  
  if (eventsFullscreenPage > totalPages - 1) {
    eventsFullscreenPage = totalPages - 1;
  }
  if (eventsFullscreenPage < 0) {
    eventsFullscreenPage = 0;
  }
  
  const startIndex = eventsFullscreenPage * EVENTS_PANEL_PAGE_SIZE;
  const pagedItems = cardItems.slice(startIndex, startIndex + EVENTS_PANEL_PAGE_SIZE);
  
  renderEventList(
    eventsFullscreenEl,
    pagedItems,
    "No events available."
  );
  
  if (eventsFullscreenTitle) {
    const displayTotal = totalEventsInDB > 0 ? totalEventsInDB : cardItems.length;
    eventsFullscreenTitle.textContent = `Events (${displayTotal.toLocaleString()} — last 24h)`;
  }
  
  if (eventsFullscreenPageInfo) {
    eventsFullscreenPageInfo.textContent = `Page: ${eventsFullscreenPage + 1}/${totalPages}`;
  }
  
  if (eventsFullscreenPrevBtn) {
    eventsFullscreenPrevBtn.disabled = eventsFullscreenPage <= 0;
  }
  
  if (eventsFullscreenNextBtn) {
    eventsFullscreenNextBtn.disabled = eventsFullscreenPage >= totalPages - 1;
  }
}

if (eventsFullscreenPrevBtn) {
  eventsFullscreenPrevBtn.addEventListener("click", () => {
    eventsFullscreenPage = Math.max(0, eventsFullscreenPage - 1);
    renderEventsFullscreen();
  });
}

if (eventsFullscreenNextBtn) {
  eventsFullscreenNextBtn.addEventListener("click", () => {
    const totalPages = Math.max(1, Math.ceil(applyEventsCardTypeFilter(orderEventsForDisplay(latestEvents || [])).length / EVENTS_PANEL_PAGE_SIZE));
    eventsFullscreenPage = Math.min(totalPages - 1, eventsFullscreenPage + 1);
    renderEventsFullscreen();
  });
}

if (eventsFullscreenModal) {
  eventsFullscreenModal.addEventListener("show.bs.modal", () => {
    eventsFullscreenPage = eventsPanelPage;
    renderEventsFullscreen();
  });
}

if (adminModalEl) {
  adminModalEl.addEventListener("show.bs.modal", () => {
    loadSettings();
    refreshAdminAuthFields();
  });
}

function buildEventExportParams() {
  const params = new URLSearchParams({ limit: "1000" });
  if (exportBandFilter?.value) {
    params.append("band", exportBandFilter.value);
  }
  if (exportModeFilter?.value) {
    params.append("mode", exportModeFilter.value);
  }
  if (exportCallsignFilter?.value) {
    params.append("callsign", exportCallsignFilter.value.trim());
  }
  if (exportStartFilter?.value) {
    params.append("start", new Date(exportStartFilter.value).toISOString());
  }
  if (exportEndFilter?.value) {
    params.append("end", new Date(exportEndFilter.value).toISOString());
  }
  return params;
}


exportCsvBtn.addEventListener("click", async () => {
  exportCsvBtn.disabled = true;
  exportCsvBtn.textContent = "Exporting...";
  try {
    const params = buildEventExportParams();
    const resp = await fetch(`/api/events/export/csv?${params.toString()}`, { headers: { ...getAuthHeader() } });
    if (!resp.ok) {
      throw new Error("csv_export_failed");
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `events-${new Date().toISOString().replace(/[:.]/g, "-")}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    showToast("CSV exported");
  } catch (err) {
    showToastError("CSV export failed");
  } finally {
    exportCsvBtn.disabled = false;
    exportCsvBtn.textContent = "Export CSV";
  }
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


exportPngBtn.addEventListener("click", async () => {
  exportPngBtn.disabled = true;
  exportPngBtn.textContent = "Exporting...";
  try {
    // Capture the main scan section (spectrum, waterfall, events, prop map)
    const mainSection = document.querySelector("section.row.g-3.mb-3");
    if (!mainSection) {
      throw new Error("Main section not found");
    }
    
    // Use html2canvas to capture the entire section
    const canvas = await html2canvas(mainSection, {
      backgroundColor: "#1a1a1a",
      scale: 2, // Higher quality
      logging: false,
      useCORS: true
    });
    
    const url = canvas.toDataURL("image/png");
    const link = document.createElement("a");
    link.href = url;
    link.download = `4ham-scan-${new Date().toISOString().replace(/[:.]/g, "-")}.png`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    showToast("PNG exported");
  } catch (err) {
    console.error("PNG export error:", err);
    showToastError("PNG export failed");
  } finally {
    exportPngBtn.disabled = false;
    exportPngBtn.textContent = "Export Waterfall to PNG";
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
          drawSpectrum(viewport.fftDb);
          const stableMarkers = buildStableWaterfallMarkers(frame);
          const rulerRange = resolveWaterfallRulerRange(
            frame,
            viewport,
            stableMarkers.rangeStartHz,
            stableMarkers.rangeEndHz
          );
          renderWaterfallRuler(rulerRange.startHz, rulerRange.endHz);
          updateVFODisplay(rulerRange.startHz, rulerRange.endHz);
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
        if (isScanRunning) {
          setWaterfallGenericStatus("No live spectrum data available. Check SDR device connection and backend status.");
        } else {
          clearWaterfallGenericStatus();
        }
      }
    };
    ws.onopen = () => {
      wsStatus.textContent = "WS: connected";
    };
    ws.onclose = () => {
      if (spectrumWs === ws) {
        wsStatus.textContent = "WS: disconnected";
        if (isScanRunning) {
          setWaterfallGenericStatus();
        } else {
          clearWaterfallGenericStatus();
        }
        spectrumWs = null;
      }
    };
  } catch (err) {
    wsStatus.textContent = "WS: disconnected";
    if (isScanRunning) {
      setWaterfallGenericStatus();
    } else {
      clearWaterfallGenericStatus();
    }
  }
}

function ensureWaterfallFallback() {
  if (spectrumFallbackTimer) {
    clearInterval(spectrumFallbackTimer);
  }
  spectrumFallbackTimer = setInterval(() => {
    const staleMs = Date.now() - lastSpectrumFrameTs;
    if (lastSpectrumFrameTs === 0 || staleMs > 2500) {
      if (isScanRunning) {
        setWaterfallGenericStatus();
      } else {
        clearWaterfallGenericStatus();
      }
      drawSpectrumIdle();
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
  drawWaterfall(lastSpectrumFrame, viewport, true);
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

// Replay the full history buffer with the current pan/zoom viewport.
// Does NOT clear fftHistoryFrames — only used for pan/zoom/goto changes.
function redrawWaterfallFromHistory() {
  if (webglWaterfall) {
    // WebGL manages its own internal accumulation buffer
    redrawWaterfallFromLastFrame();
    return;
  }
  if (!fftHistoryFrames.length) {
    return;
  }
  // Clear canvas pixels without touching the history buffer
  row = 0;
  if (ctx) {
    const w = canvas.width / window.devicePixelRatio;
    const h = canvas.height / window.devicePixelRatio;
    ctx.clearRect(0, 0, w, h);
  }
  for (const hFrame of fftHistoryFrames) {
    const vp = getWaterfallViewport(hFrame);
    drawWaterfall(hFrame, vp, true); // _historyReplay=true: don't re-push
  }
  // Update ruler and overlays from the most recent frame
  const lastFrame = fftHistoryFrames[fftHistoryFrames.length - 1];
  const lastVp = getWaterfallViewport(lastFrame);
  const stableMarkers = buildStableWaterfallMarkers(lastFrame);
  const rulerRange = resolveWaterfallRulerRange(
    lastFrame, lastVp, stableMarkers.rangeStartHz, stableMarkers.rangeEndHz
  );
  renderWaterfallRuler(rulerRange.startHz, rulerRange.endHz);
  const simulatedMarkers = buildSimulatedModeMarkers(
    lastVp.visibleSpanHz, rulerRange.startHz, rulerRange.endHz
  );
  const modeMarkers = WATERFALL_SIMULATE_MODE_MARKERS
    ? [...stableMarkers.markers, ...simulatedMarkers]
    : stableMarkers.markers;
  renderWaterfallModeOverlay(modeMarkers, lastVp.visibleSpanHz, rulerRange.startHz, rulerRange.endHz);
}

function resetWaterfallExplorerView() {
  waterfallExplorerZoom = 1;
  waterfallExplorerPan = 0;
  localStorage.setItem(WATERFALL_EXPLORER_ZOOM_KEY, String(waterfallExplorerZoom));
  applyWaterfallExplorerUi();
  redrawWaterfallFromHistory();
}

if (waterfallExplorerToggle) {
  waterfallExplorerToggle.addEventListener("click", () => {
    waterfallExplorerEnabled = !waterfallExplorerEnabled;
    localStorage.setItem(WATERFALL_EXPLORER_KEY, waterfallExplorerEnabled ? "1" : "0");
    if (!waterfallExplorerEnabled) {
      waterfallExplorerZoom = 1;
      waterfallExplorerPan = 0;
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
    redrawWaterfallFromHistory();
  });
}

if (waterfallResetViewBtn) {
  waterfallResetViewBtn.addEventListener("click", () => {
    // Keep history — reset only pan/zoom so the full waterfall reappears at zoom=1
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
  // Gate replay to one rAF per drag tick to keep dragging smooth
  if (!waterfallDragRafPending) {
    waterfallDragRafPending = true;
    requestAnimationFrame(() => {
      waterfallDragRafPending = false;
      redrawWaterfallFromHistory();
    });
  }
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
        if (data.retention_completed) {
          showRetentionToast(data.retention_completed);
        }
      } catch (err) {
        setStatus("Status decode error");
      }
    };
  } catch (err) {
    setStatus("Status stream unavailable");
  }
}

async function fetchDecoderStatus() {
  try {
    const resp = await fetch("/api/decoders/status", { headers: { ...getAuthHeader() } });
    if (!resp.ok) {
      throw new Error("decoder status failed");
    }
    const data = await resp.json();
    const status = data.status || {};
    const extFt = status.external_ft || {};
    const kiss = status.direwolf_kiss || {};
    const sources = status.sources || {};
    const lastEvent = Object.values(sources).sort().slice(-1)[0] || "-";
    if (extFt.enabled) {
      const modes = (extFt.modes || []).join(", ");
      if (externalFtStatusModalEl) externalFtStatusModalEl.textContent = `Configured (${modes})`;
    } else {
      if (externalFtStatusModalEl) externalFtStatusModalEl.textContent = "Not configured (set FT_EXTERNAL_ENABLE=1)";
    }
    const kissState = kiss.enabled ? (kiss.connected ? "Connected" : "Disconnected") : "Disabled";
    const kissDisabledReason = kiss.last_error
      ? ` (${kiss.last_error})`
      : " (set DIREWOLF_KISS_ENABLE=1 or DIREWOLF_KISS_PORT)";
    if (kissStatusModalEl) kissStatusModalEl.textContent = kiss.enabled ? kissState : `Disabled${kissDisabledReason}`;
    if (decoderLastEventModalEl) decoderLastEventModalEl.textContent = lastEvent;
    if (agcStatusModalEl) agcStatusModalEl.textContent = status.dsp && status.dsp.agc_enabled ? "On" : "Off";
  } catch (err) {
    if (externalFtStatusModalEl) externalFtStatusModalEl.textContent = "Unavailable";
    if (kissStatusModalEl) kissStatusModalEl.textContent = "Unavailable";
    if (decoderLastEventModalEl) decoderLastEventModalEl.textContent = "-";
    if (agcStatusModalEl) agcStatusModalEl.textContent = "-";
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
  showToast(`Auto setup applied: class=${appliedDeviceClass}, PPM=${appliedPpm}, offset=${appliedOffset} Hz, gain=${appliedGainProfile}`);
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
    showToast("Audio auto-detect completed");
    logLine(`Audio auto-detect: detected=${hasDetectedEndpoints}, input=${audioProfile.input_device || ""}, output=${audioProfile.output_device || ""}, sample_rate=${audioProfile.sample_rate ?? 48000}, method=${methods}`);
  } catch (err) {
    showToastError("Audio auto-detect failed");
  }
}

async function loadBands() {
  try {
    const resp = await fetch("/api/bands", { headers: { ...getAuthHeader() } });
    const bands = await resp.json();
    if (Array.isArray(bands)) {
      populateBandSelectOptions(bands);
      syncBandEditorFields(bandNameInput?.value || bandSelect?.value || "20m");
      renderScanContextSummary(latestScanState);
      return;
    }
  } catch (err) {
    logLine("Failed to load bands");
  }
  populateBandSelectOptions([]);
  syncBandEditorFields(bandNameInput?.value || bandSelect?.value || "20m");
  renderScanContextSummary(latestScanState);
}

async function loadSettings() {
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
    renderScanContextSummary(latestScanState);
    if (data.device_id) {
      deviceSelect.value = data.device_id;
    }
    if (data.station) {
      stationCallsignInput.value = data.station.callsign || "";
      stationOperatorInput.value = data.station.operator || "";
      stationLocatorInput.value = data.station.locator || "";
      stationQthInput.value = data.station.qth || "";
    }
    if (data.auth) {
      setAuthFields(data.auth || {});
    } else {
      await refreshAdminAuthFields();
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
    await refreshAdminAuthFields();
  }
}

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

if (saveCredentialsBtn) {
  saveCredentialsBtn.addEventListener("click", async () => {
    const user = (authUserInput?.value || "").trim();
    const pass = (authPassInput?.value || "").trim();
    const passIsMasked = authPassInput?.dataset.masked === "1" && pass === AUTH_PASSWORD_MASK;
    if (passIsMasked) {
      if (user === String(window.__authUser || "").trim()) {
        showToast("Credentials unchanged");
        return;
      }
      showToastError("Type a new password to change credentials");
      return;
    }
    if (!user || !pass) {
      showToastError("Both username and password are required");
      return;
    }
    try {
      const resp = await fetch("/api/auth/credentials", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeader() },
        body: JSON.stringify({ user, password: pass }),
      });
      if (!resp.ok) {
        const message = await parseApiError(resp, "Failed to save credentials");
        showToastError(message);
        return;
      }
      window.__authUser = user;
      showToast("Credentials saved");
      updateLoginStatus();
      setAuthFields({ enabled: true, user, password_configured: true });
      await updateAuthStatusBadge();
    } catch (err) {
      showToastError("Failed to save credentials");
    }
  });
}

if (clearCredentialsBtn) {
  clearCredentialsBtn.addEventListener("click", async () => {
    const confirmed = window.confirm("Clear server credentials? Authentication will be disabled.");
    if (!confirmed) {
      return;
    }
    try {
      const resp = await fetch("/api/auth/credentials", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeader() },
        body: JSON.stringify({ user: "", password: "" }),
      });
      if (!resp.ok) {
        const message = await parseApiError(resp, "Failed to clear credentials");
        showToastError(message);
        return;
      }
      window.__authUser = "";
      setAuthFields({ enabled: false, user: "", password_configured: false });
      showToast("Credentials cleared — authentication disabled");
      updateLoginStatus();
      await updateAuthStatusBadge();
    } catch (err) {
      showToastError("Failed to clear credentials");
    }
  });
}

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
  if (data.band && exportBandFilter) exportBandFilter.value = data.band;
  if (data.mode && exportModeFilter) exportModeFilter.value = data.mode;
  if (data.callsign && exportCallsignFilter) exportCallsignFilter.value = data.callsign;
  if (data.start && exportStartFilter) exportStartFilter.value = data.start;
  if (data.end && exportEndFilter) exportEndFilter.value = data.end;
}

saveSettingsBtn.addEventListener("click", async () => {
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

    syncBandEditorFields(bandNameInput.value);
  });

  syncBandEditorFields(bandNameInput.value);
}

if (authPassInput) {
  authPassInput.addEventListener("focus", () => {
    if (authPassInput.dataset.masked === "1") {
      authPassInput.value = "";
      authPassInput.dataset.masked = "0";
    }
  });
}

if (bandSelect && bandNameInput) {
  bandSelect.addEventListener("change", () => {
    const hasOption = Array.from(bandNameInput.options || []).some((option) => option.value === bandSelect.value);
    if (hasOption) {
      bandNameInput.value = bandSelect.value;
    }
    refreshQuickBandButtons();
    renderScanContextSummary(latestScanState);
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

if (quickModeButtons.length) {
  quickModeButtons.forEach((button) => {
    button.addEventListener("click", async () => {
      if (scanActionInFlight) {
        return;
      }
      const mode = String(button.dataset.quickMode || "").trim();
      
      // During active scan: allow mode change but prevent deselection
      if (isScanRunning) {
        if (selectedDecoderMode === mode) {
          // Trying to deselect during scan - block it
          showToast("Cannot deselect mode while scanning. Stop the scan first.");
          return;
        }
        // Changing to different mode during scan - clear caches and notify backend
        waterfallMarkerCache.clear();
        waterfallDecodedMarkerCache.clear();
        waterfallCallsignCache.clear();
        latestEvents = []; // Clear events from previous mode
        renderEventsPanelFromCache(); // Refresh empty panel
        
        selectedDecoderMode = mode;
        recenterWaterfallForMode(mode);
        // Sync the events panel filter so only events from this mode are shown
        eventsSearchModeInput.value = mode;
        refreshModeButtons();
        logLine(`Mode changed during scan: ${mode}`);
        
        showWaterfallTransition(`Switching to mode ${mode}...`);

        try {
          await fetch("/api/scan/mode", {
            method: "POST",
            headers: { "Content-Type": "application/json", ...getAuthHeader() },
            body: JSON.stringify({ decoder_mode: mode.toLowerCase() })
          });
          showToast(`Mode switched to ${mode}`);
          fetchEvents();
          fetchTotal();
        } catch (err) {
          showToastError(`Failed to switch mode: ${err.message}`);
        } finally {
          hideWaterfallTransition();
        }
        return;
      }
      
      // Not scanning: allow toggle (select/deselect)
      if (selectedDecoderMode === mode) {
        selectedDecoderMode = null;
        eventsSearchModeInput.value = "";
        refreshModeButtons();
        logLine(`Modo desseleccionado: ${mode}`);
        fetchEvents();
        fetchTotal();
      } else {
        selectedDecoderMode = mode;
        recenterWaterfallForMode(mode);
        eventsSearchModeInput.value = mode;
        refreshModeButtons();
        logLine(`Modo selecionado: ${mode}`);
        fetchEvents();
        fetchTotal();
      }
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
  try {
    const resp = await fetch("/api/bands", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify(payload)
    });
    if (!resp.ok) {
      const message = await parseApiError(resp, "Band validation failed");
      showToastError(message);
      return;
    }

    await loadBands();
    syncBandEditorFields(payload.band.name);

    if (String(bandSelect?.value || "") === String(payload.band.name)) {
      if (isScanRunning) {
        renderWaterfallRuler(Number(payload.band.start_hz), Number(payload.band.end_hz));
        updateVFODisplay(Number(payload.band.start_hz), Number(payload.band.end_hz));
        showToast("Band saved. New limits apply fully on next scan restart.");
      } else {
        await applyPreviewBandRange(payload.band.name, { syncInputs: true });
        showToast("Band saved");
      }
    } else {
      showToast("Band saved");
    }

    logLine(`Band saved: ${payload.band.name}`);
  } catch (err) {
    showToastError(err?.message || "Band save failed");
  }
});

let appStarted = false;

async function startApplication() {
  if (appStarted) {
    return;
  }
  appStarted = true;
  connectSpectrum();
  ensureWaterfallFallback();
  connectStatus();
  connectEvents();
  await loadDevices();
  await loadBands();
  await loadSettings();
  await loadPresets();
  loadFilters();
  fetchEvents();
  fetchTotal();
  setInterval(() => { fetchEvents(); fetchTotal(); }, 5000);
  refreshQuickBandButtons();
  syncScanState();
  setInterval(syncScanState, 5000);
  fetchModeStats();
  setInterval(fetchModeStats, 10000);
  fetchPropagationSummary();
  setInterval(fetchPropagationSummary, 15000);
  fetchDecoderStatus();
  setInterval(fetchDecoderStatus, 10000);
  connectLogs();
  fetchLogs();
  setInterval(fetchLogs, 4000);
  fetchFileLog();
  setInterval(fetchFileLog, 8000);
  initMenuDropdownModalBehavior();

  try {
    const res = await fetch("/api/health");
    if (res.ok) {
      const data = await res.json();
      const deviceCount = Number(data?.devices ?? -1);
      if (deviceCount === 0) {
        setWaterfallGenericStatus("No SDR device detected. Connect your device and start a scan.");
        drawSpectrumIdle("No SDR device detected. Connect your device and start a scan.");
        showToastError("No SDR device detected. Connect your device and start a scan.");
      }
    }
  } catch (_) {
    // health check is best-effort; ignore network errors
  }

  if (!localStorage.getItem("onboardingDone")) {
    onboarding.classList.add("show");
    renderOnboarding();
  }
}

// ── Logout button ──
const logoutBtnEl = document.getElementById("logoutBtn");
if (logoutBtnEl) {
  logoutBtnEl.addEventListener("click", async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST" });
      window.__authUser = "";
      updateLoginStatus();
      const loginModalEl = document.getElementById("loginModal");
      const loginModalUser = document.getElementById("loginModalUser");
      const loginModalPass = document.getElementById("loginModalPass");
      if (loginModalUser) loginModalUser.value = "";
      if (loginModalPass) loginModalPass.value = "";
      const data = await updateAuthStatusBadge();
      if (data?.auth_required) {
        new bootstrap.Modal(loginModalEl, { backdrop: "static" }).show();
      }
    } catch (_) {}
  });
}

// ── Login modal: show when server requires auth and no valid session ──
(async () => {
  const data = await updateAuthStatusBadge();
  if (data?.auth_required && !data.authenticated) {
    const loginModal = new bootstrap.Modal(document.getElementById("loginModal"), { backdrop: "static" });
    loginModal.show();
    return;
  }
  await startApplication();
})();

const loginModalSaveBtnEl = document.getElementById("loginModalSave");
if (loginModalSaveBtnEl) {
  loginModalSaveBtnEl.addEventListener("click", async () => {
    const user = (document.getElementById("loginModalUser")?.value || "").trim();
    const pass = (document.getElementById("loginModalPass")?.value || "").trim();
    const errEl = document.getElementById("loginModalError");
    if (!user || !pass) {
      if (errEl) { errEl.textContent = "Enter username and password"; errEl.classList.remove("d-none"); }
      return;
    }
    const testResp = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user, password: pass })
    }).catch(() => null);
    if (!testResp || !testResp.ok) {
      if (errEl) { errEl.textContent = "Invalid username or password"; errEl.classList.remove("d-none"); }
      return;
    }
    window.__authUser = user;
    if (errEl) errEl.classList.add("d-none");
    const loginModalEl = document.getElementById("loginModal");
    bootstrap.Modal.getInstance(loginModalEl)?.hide();
    updateLoginStatus();
    await updateAuthStatusBadge();
    await startApplication();
    loadSettings();
    fetchEvents();
    fetchTotal();
  });
}

// ── Spectrum graph renderer (above waterfall) ──
function drawSpectrum(fftDb) {
  if (!spectrumCtx || !Array.isArray(fftDb) || !fftDb.length) return;
  const sc = spectrumCanvas;
  const W = sc.offsetWidth > 0 ? sc.offsetWidth : (sc.width || 640);
  const H = sc.height || 80;
  if (sc.width !== W) sc.width = W;
  let minDb = Infinity, maxDb = -Infinity;
  for (let i = 0; i < fftDb.length; i++) {
    if (fftDb[i] < minDb) minDb = fftDb[i];
    if (fftDb[i] > maxDb) maxDb = fftDb[i];
  }
  const scale = maxDb - minDb || 1;
  if (!_specSmooth || _specSmooth.length !== W) {
    _specSmooth = new Float32Array(W);
    for (let x = 0; x < W; x++) {
      const idx = Math.min(fftDb.length - 1, Math.floor((x / (W - 1)) * (fftDb.length - 1)));
      _specSmooth[x] = (fftDb[idx] - minDb) / scale;
    }
  }
  for (let x = 0; x < W; x++) {
    const idx = Math.min(fftDb.length - 1, Math.floor((x / (W - 1)) * (fftDb.length - 1)));
    const v = (fftDb[idx] - minDb) / scale;
    _specSmooth[x] = _specSmooth[x] * (1 - _SPEC_SMOOTH_ALPHA) + v * _SPEC_SMOOTH_ALPHA;
  }
  // Background
  spectrumCtx.fillStyle = "#080c14";
  spectrumCtx.fillRect(0, 0, W, H);
  // Grid
  spectrumCtx.strokeStyle = "rgba(255,255,255,0.04)";
  spectrumCtx.lineWidth = 1;
  for (let g = 1; g <= 3; g++) {
    const y = Math.round(H * g / 4) + 0.5;
    spectrumCtx.beginPath(); spectrumCtx.moveTo(0, y); spectrumCtx.lineTo(W, y); spectrumCtx.stroke();
  }
  // Filled gradient
  const grad = spectrumCtx.createLinearGradient(0, 0, 0, H);
  for (let s = 0; s <= 8; s++) {
    const [r, g, b] = colorMap(1 - s / 8);
    grad.addColorStop(s / 8, `rgba(${r},${g},${b},${Math.max(0, 0.48 - s * 0.05)})`);
  }
  spectrumCtx.beginPath();
  spectrumCtx.moveTo(0, H);
  for (let x = 0; x < W; x++) spectrumCtx.lineTo(x, H - _specSmooth[x] * (H - 3));
  spectrumCtx.lineTo(W - 1, H);
  spectrumCtx.closePath();
  spectrumCtx.fillStyle = grad;
  spectrumCtx.fill();
  // Line
  spectrumCtx.beginPath();
  for (let x = 0; x < W; x++) {
    const y = H - _specSmooth[x] * (H - 3);
    x === 0 ? spectrumCtx.moveTo(x, y) : spectrumCtx.lineTo(x, y);
  }
  const [lr, lg, lb] = colorMap(0.85);
  spectrumCtx.strokeStyle = `rgba(${lr},${lg},${lb},0.88)`;
  spectrumCtx.lineWidth = 1.5;
  spectrumCtx.stroke();
}

function drawSpectrumIdle(message) {
  if (!spectrumCtx || !spectrumCanvas) return;
  const sc = spectrumCanvas;
  const W = sc.offsetWidth > 0 ? sc.offsetWidth : (sc.width || 640);
  const H = sc.height || 80;
  if (sc.width !== W) sc.width = W;
  spectrumCtx.fillStyle = "#080c14";
  spectrumCtx.fillRect(0, 0, W, H);
  spectrumCtx.save();
  spectrumCtx.font = "13px 'Courier New', monospace";
  spectrumCtx.fillStyle = "rgba(255,255,255,0.35)";
  spectrumCtx.textAlign = "center";
  spectrumCtx.textBaseline = "middle";
  spectrumCtx.fillText(message || "No live spectrum available. Check SDR device connection and scan status.", W / 2, H / 2);
  spectrumCtx.restore();
}

function drawWaterfall(frame, viewport = null, _historyReplay = false) {
  // Accumulate raw frames for history replay (pan/zoom/goto).
  // Skip when called recursively during redrawWaterfallFromHistory.
  if (!_historyReplay && frame && frame.fft_db) {
    fftHistoryFrames.push(frame);
    if (fftHistoryFrames.length > FFT_HISTORY_MAX) {
      fftHistoryFrames.shift();
    }
  }
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

// FT-DX10 "jet" palette — black → electric-blue → cyan → green → yellow → orange → red
// Colour stops match Yaesu FT-DX10 waterfall display.
// Pure visual change: zero functional, API or memory impact.
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

// ─────────────────────────────────────────────
// VFO DISPLAY + CONTROLS (visual only — no scan state altered)
// ─────────────────────────────────────────────
let _vfoDisplayHz = 0;
const _vfoFreqEl  = document.getElementById("vfoFreqEl");

function _formatVFOFreq(hz) {
  const mhz = Math.floor(hz / 1_000_000);
  const khz = Math.floor((hz % 1_000_000) / 1000).toString().padStart(3, "0");
  const hz3 = (hz % 1000).toString().padStart(3, "0");
  return `${mhz}<span class="vfo-sep">.</span>${khz}<span class="vfo-sep">.</span>${hz3}`;
}

function updateVFODisplay(startHz, endHz) {
  if (!_vfoFreqEl || !Number.isFinite(startHz) || !Number.isFinite(endHz)) return;
  const centre = Math.round((startHz + endHz) / 2);
  if (centre === _vfoDisplayHz) return;
  _vfoDisplayHz = centre;
  _vfoFreqEl.innerHTML = _formatVFOFreq(centre);
  refreshQuickBandButtons();
}

(function initVFOControls() {
  const gotoInput = document.getElementById("vfoGotoInput");
  function applyGoto() {
    const raw = (gotoInput?.value || "").trim().replace(",", ".");
    const mhz = parseFloat(raw);
    if (isNaN(mhz) || mhz <= 0) {
      if (gotoInput) {
        gotoInput.style.borderColor = "rgba(180,40,40,0.8)";
        setTimeout(() => { gotoInput.style.borderColor = ""; }, 700);
      }
      return;
    }
    const targetHz = Math.round(mhz * 1_000_000);
    const frame = lastSpectrumFrame;
    const scanStartHz = Number(frame?.scan_start_hz || 0);
    const scanEndHz   = Number(frame?.scan_end_hz   || 0);
    const centerHz    = Number(frame?.center_hz     || 0);
    const spanHz      = Number(frame?.span_hz       || 0);
    const hasScanRange = scanStartHz > 0 && scanEndHz > scanStartHz;
    const fullStartHz  = hasScanRange ? scanStartHz : (centerHz - (spanHz * WATERFALL_SEGMENT_COUNT / 2));
    const fullSpanHz   = hasScanRange ? (scanEndHz - scanStartHz) : (spanHz * WATERFALL_SEGMENT_COUNT);
    if (!fullSpanHz || targetHz < fullStartHz || targetHz > fullStartHz + fullSpanHz) {
      showToast(`${mhz.toFixed(3)} MHz is outside the current band`);
      return;
    }
    if (!waterfallExplorerEnabled) {
      waterfallExplorerEnabled = true;
      localStorage.setItem(WATERFALL_EXPLORER_KEY, "1");
    }
    if (waterfallExplorerZoom <= 1) {
      waterfallExplorerZoom = 4;
      localStorage.setItem(WATERFALL_EXPLORER_ZOOM_KEY, "4");
    }
    const zoom = waterfallExplorerZoom;
    const visibleSpanHz  = fullSpanHz / zoom;
    const desiredStartHz = targetHz - visibleSpanHz / 2;
    const maxPan = Math.max(0, 1 - 1 / zoom);
    waterfallExplorerPan = Math.max(0, Math.min(maxPan, (desiredStartHz - fullStartHz) / fullSpanHz));
    applyWaterfallExplorerUi();
    redrawWaterfallFromHistory();
    if (gotoInput) gotoInput.value = "";
    showToast(`Centred on ${mhz.toFixed(3)} MHz`);
  }
  document.getElementById("vfoApplyBtn")?.addEventListener("click", applyGoto);
  gotoInput?.addEventListener("keydown", e => { if (e.key === "Enter") applyGoto(); });

  // Events Search modal — callsign input also triggers API search
  // (mode/band/snrMin already have change/input listeners above)
  eventsSearchCallsignInput?.addEventListener("input", scheduleEventsSearch);
  eventsSearchStartInput?.addEventListener("change", scheduleEventsSearch);
  eventsSearchEndInput?.addEventListener("change", scheduleEventsSearch);
  // Init Flatpickr date pickers with Portuguese locale
  if (eventsSearchStartInput && window.flatpickr) {
    flatpickr(eventsSearchStartInput, {
      locale: "pt", dateFormat: "d/m/Y",
      allowInput: false,
      onChange: () => scheduleEventsSearch()
    });
  }
  if (eventsSearchEndInput && window.flatpickr) {
    flatpickr(eventsSearchEndInput, {
      locale: "pt", dateFormat: "d/m/Y",
      allowInput: false,
      onChange: () => scheduleEventsSearch()
    });
  }
  eventsSearchPrevBtn?.addEventListener("click", () => { _searchPage--; renderSearchPage(); });
  eventsSearchNextBtn?.addEventListener("click", () => { _searchPage++; renderSearchPage(); });
  document.getElementById("eventsSearchModal")
    ?.addEventListener("shown.bs.modal", () => scheduleEventsSearch());
})();
