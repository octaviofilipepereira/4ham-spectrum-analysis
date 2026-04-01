/*
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
Last update: 2026-02-24 18:30 UTC
*/

import { loadPresetsFromJson } from "./utils/presets.js";
import {
  EVENTS_PANEL_PAGE_SIZE,
  SEARCH_PAGE_SIZE,
  AUTH_PASSWORD_MASK,
  SHOW_NON_SDR_DEVICES_KEY,
  BAND_PRESETS,
  DEFAULT_BAND_OPTIONS,
  CW_DECODER_SUBBANDS,
  DEVICE_AUTO_PROFILES,
} from "./modules/constants.js";
import {
  normalizeNumberInputValue,
  formatScanRangeSummary,
  inferBandFromFrequency,
  normalizeModeLabel,
  isValidCallsign,
  extractCallsignFromRaw,
  isValidLocator,
  _isSsbSpectralProof,
  extractDecodedText,
  getAuthHeader,
  wsUrl,
} from "./modules/utils.js";
import { WaterfallController } from "./modules/waterfall.js";

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
const saveSettingsBtn = document.getElementById("saveSettings");
const testConfigBtn = document.getElementById("testConfig");
const refreshDevicesBtn = document.getElementById("refreshDevices");
const adminDeviceSetupBtn = document.getElementById("adminDeviceSetup");
const adminAudioAutoDetectBtn = document.getElementById("adminAudioAutoDetect");
const purgeInvalidEventsBtn = document.getElementById("purgeInvalidEvents");
const resetDefaultsBtn = document.getElementById("resetDefaults");
const resetAllConfigBtn = document.getElementById("resetAllConfig");
const showNonSdrDevicesToggle = document.getElementById("showNonSdrDevices");
const ssbAsrEnabledCheck = document.getElementById("ssbAsrEnabled");
const ssbAsrAvailableBadge = document.getElementById("ssbAsrAvailableBadge");
const saveAsrSettingsBtn = document.getElementById("saveAsrSettings");
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
  wfc.renderRuler(bandStartHz, bandEndHz);
  wfc.updateVFODisplay(bandStartHz, bandEndHz);
  wfc.clearFrame();

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

let eventOffset = 0;
let eventsPanelPage = 0;
let latestEvents = [];
let spectrumFallbackTimer = null;
let spectrumWs = null;
let isScanRunning = false;
let scanActionInFlight = false;
let showNonSdrDevices = localStorage.getItem(SHOW_NON_SDR_DEVICES_KEY) === "1";

if (showNonSdrDevicesToggle) {
  showNonSdrDevicesToggle.checked = showNonSdrDevices;
}

const wfc = new WaterfallController(
  {
    canvas,
    spectrumCanvas,
    spectrumCtx,
    waterfallEl,
    waterfallStatus,
    waterfallModeBadge,
    waterfallRuler,
    waterfallModeOverlay,
    waterfallTransition: document.getElementById("waterfallTransition"),
    waterfallTransitionMsg: document.getElementById("waterfallTransitionMsg"),
    waterfallExplorerToggle,
    waterfallZoomInput,
    waterfallResetViewBtn,
    bandSelect,
    vfoFreqEl: document.getElementById("vfoFreqEl"),
    vfoGotoInput: document.getElementById("vfoGotoInput"),
    vfoApplyBtn: document.getElementById("vfoApplyBtn"),
  },
  {
    getScanRange: (bandName) => getScanRangeForBand(bandName),
    onVFOUpdate: () => refreshQuickBandButtons(),
    showToast: (msg) => showToast(msg),
  }
);

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

wfc.updateModeBadge();
updateFullscreenButtonState();
wfc.applyExplorerUi();

function logLine(text) {
  if (!frontendLogsEl) {
    return;
  }
  const current = frontendLogsEl.textContent === "No frontend logs yet." ? "" : frontendLogsEl.textContent;
  frontendLogsEl.textContent = `${new Date().toISOString()} ${text}\n${current}`.trim();
}

function renderToast(message, isError = false, detail = "") {
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

  const bodyEl = document.createElement("div");
  bodyEl.className = "toast__body";

  const messageEl = document.createElement("span");
  messageEl.className = "toast__message";
  messageEl.textContent = message;
  bodyEl.appendChild(messageEl);

  if (detail) {
    const detailEl = document.createElement("span");
    detailEl.className = "toast__detail";
    detailEl.textContent = detail;
    bodyEl.appendChild(detailEl);
  }

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "toast__close";
  closeBtn.textContent = "×";
  closeBtn.setAttribute("aria-label", "Close notification");
  closeBtn.addEventListener("click", () => {
    noticeEl.remove();
  });

  noticeEl.appendChild(bodyEl);
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

window.addEventListener("resize", () => wfc.resize());

function addEvent(text) {
  logLine(`events: ${text}`);
}

function pushLiveEventToPanel(eventPayload) {
  if (!eventPayload || typeof eventPayload !== "object") {
    return;
  }

  // Toast notification for confirmed SSB voice detections
  const _evMode = String(eventPayload.mode || "").toUpperCase();
  const _evSrc = String(eventPayload.source || "");
  if (
    (_evMode === "SSB" || _evMode === "SSB_TRAFFIC") &&
    eventPayload.type === "callsign" &&
    (_evSrc === "internal_ssb_occupancy" || _evSrc === "internal_ssb_asr")
  ) {
    const _ssbMsg = String(eventPayload.msg || "").trim();
    const _ssbProof = String(eventPayload.raw || "").trim();
    const _ssbSub = (_ssbProof !== _ssbMsg && !_isSsbSpectralProof(_ssbProof)) ? _ssbProof : "";
    if (_ssbMsg) {
      renderToast(_ssbMsg, false, _ssbSub);
    }
  }

  wfc.updateCallsignCacheFromEvent(eventPayload);
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
  if (selected === "ssb-traffic") {
    return source.filter((eventItem) => String(eventItem?.mode || "").trim().toUpperCase() === "SSB_TRAFFIC");
  }
  if (selected === "ssb-callsign") {
    // SSB callsign events where a valid amateur callsign was identified
    return source.filter((eventItem) => {
      const mode = String(eventItem?.mode || "").trim().toUpperCase();
      if (mode !== "SSB" && mode !== "SSB_TRAFFIC") return false;
      if (String(eventItem?.type || "").trim() !== "callsign") return false;
      const cs = String(eventItem?.callsign || "").trim();
      if (cs) return true;
      const fromRaw = extractCallsignFromRaw(eventItem?.raw);
      return fromRaw.length > 0;
    });
  }
  if (selected === "cw-only") {
    return source.filter((eventItem) => String(eventItem?.mode || "").trim().toUpperCase() === "CW");
  }
  if (selected === "callsign-only") {
    return source.filter((eventItem) => {
      const modeText = String(eventItem?.mode || "").trim().toUpperCase();
      const allowRawCallsignInference = modeText !== "SSB";
      const callsignText = String(
        eventItem?.callsign || (allowRawCallsignInference ? extractCallsignFromRaw(eventItem?.raw) : "") || ""
      ).trim();
      return callsignText.length > 0;
    });
  }
  if (selected === "all-occupancy") {
    return source;
  }
  // Default "all" — show callsign events only (suppress raw occupancy noise)
  return source.filter((eventItem) => String(eventItem?.type || "").trim() === "callsign");
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
    const _isSSBVoice = eventItem.type === "callsign" && /^SSB/i.test(eventItem.mode || "") && !eventItem.callsign;
    typeBadge.className = `badge ${eventItem.type === "callsign" ? "bg-info" : "bg-secondary"}`;
    typeBadge.textContent = _isSSBVoice ? "Voice Signature" : (eventItem.type || "event");

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
    const modeText = String(eventItem.mode || "").trim().toUpperCase();
    const isSsbMode = modeText === "SSB" || modeText === "SSB_TRAFFIC";
    let callsign;
    if (isSsbMode) {
      if (eventItem.callsign) {
        callsign = eventItem.callsign;
      } else {
        const rawText = String(eventItem.raw || "").trim();
        const hasRealTranscript = rawText && !_isSsbSpectralProof(rawText);
        callsign = hasRealTranscript ? "Voice Transcript" : "Voice Confirmed";
      }
    } else {
      callsign = eventItem.callsign || extractCallsignFromRaw(eventItem.raw) || "NO CALLSIGN DETECTED";
    }
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
  wfc.updateCallsignCacheFromEvents(sourceItems);
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
    titleTarget.textContent = `Events (Total of ${displayTotal.toLocaleString()} Events - Last 24h)`;
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

  // Phase 1.4 behavior: markers are tied to the current scan session only.
  wfc.clearMarkerCaches();

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
    wfc.recenterForMode(selectedDecoderMode);
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
  wfc.clearMarkerCaches();
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
        wfc.recenterForMode(selectedDecoderMode);
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
      wfc.recenterForMode(backendMode);
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
  wfc.showTransition(`Switching to band ${nextBand}...`);

  try {
    await stopScan();
    // Clear the old band's waterfall frame and state
    wfc.clearFrame();
    await startScan();
    showToast(`Band switched to ${nextBand}`);
  } catch (err) {
    showToastError(err?.message || "Failed to switch band live");
  } finally {
    wfc.hideTransition();
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
    wfc.updateCallsignCacheFromEvents(callsignEvents);
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
window._debugWaterfall = () => wfc.debug();

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
    eventsFullscreenTitle.textContent = `Events (Total of ${displayTotal.toLocaleString()} Events - Last 24h)`;
  }
  
  if (eventsFullscreenPageInfo) {
    const globalPage = Math.floor(eventOffset / EVENTS_PANEL_PAGE_SIZE) + eventsFullscreenPage + 1;
    const totalGlobalPages = totalEventsInDB > 0
      ? Math.ceil(totalEventsInDB / EVENTS_PANEL_PAGE_SIZE)
      : totalPages;
    eventsFullscreenPageInfo.textContent = `Page: ${globalPage}/${totalGlobalPages}`;
  }
  
  if (eventsFullscreenPrevBtn) {
    eventsFullscreenPrevBtn.disabled = eventsFullscreenPage <= 0 && eventOffset <= 0;
  }
  
  if (eventsFullscreenNextBtn) {
    const moreServerEvents = totalEventsInDB > eventOffset + latestEvents.length;
    eventsFullscreenNextBtn.disabled = eventsFullscreenPage >= totalPages - 1 && !moreServerEvents;
  }
}

if (eventsFullscreenPrevBtn) {
  eventsFullscreenPrevBtn.addEventListener("click", () => {
    if (eventsFullscreenPage > 0) {
      eventsFullscreenPage = Math.max(0, eventsFullscreenPage - 1);
      renderEventsFullscreen();
    } else if (eventOffset > 0) {
      eventOffset = Math.max(0, eventOffset - 200);
      eventsFullscreenPage = 0;
      fetchEvents();
    }
  });
}

if (eventsFullscreenNextBtn) {
  eventsFullscreenNextBtn.addEventListener("click", () => {
    const totalLocalPages = Math.max(1, Math.ceil(applyEventsCardTypeFilter(orderEventsForDisplay(latestEvents || [])).length / EVENTS_PANEL_PAGE_SIZE));
    if (eventsFullscreenPage < totalLocalPages - 1) {
      eventsFullscreenPage = Math.min(totalLocalPages - 1, eventsFullscreenPage + 1);
      renderEventsFullscreen();
    } else if (totalEventsInDB > eventOffset + latestEvents.length) {
      eventOffset += 200;
      eventsFullscreenPage = 0;
      fetchEvents();
    }
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
          wfc.isScanRunning = isScanRunning;
          wfc.selectedDecoderMode = selectedDecoderMode;
          const { viewport, rulerRange } = wfc.processLiveFrame(frame);
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
          const explorerInfo = viewport.simulated ? ` | explorer zoom x${wfc.explorerZoom}` : "";
          wfc.clearGenericStatus();
          waterfallStatus.textContent = `FFT bins: ${viewport.fftDb.length} | ${startHz} Hz - ${endHz} Hz | dB ${minDb}..${maxDb} | nf ${noiseFloor}dB${peaksInfo}${agcInfo}${explorerInfo} | ${wfc.renderer.toUpperCase()}`;
          updateQuality(minDb, maxDb);
        }
      } catch (err) {
        if (isScanRunning) {
          wfc.setGenericStatus("No live spectrum data available. Check SDR device connection and backend status.");
        } else {
          wfc.clearGenericStatus();
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
          wfc.setGenericStatus();
        } else {
          wfc.clearGenericStatus();
        }
        spectrumWs = null;
      }
    };
  } catch (err) {
    wsStatus.textContent = "WS: disconnected";
    if (isScanRunning) {
      wfc.setGenericStatus();
    } else {
      wfc.clearGenericStatus();
    }
  }
}

function ensureWaterfallFallback() {
  if (spectrumFallbackTimer) {
    clearInterval(spectrumFallbackTimer);
  }
  spectrumFallbackTimer = setInterval(() => {
    const staleMs = Date.now() - wfc.lastFrameTs;
    if (wfc.lastFrameTs === 0 || staleMs > 2500) {
      if (isScanRunning) {
        wfc.setGenericStatus();
      } else {
        wfc.clearGenericStatus();
      }
      wfc.drawSpectrumIdle();
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
      wfc.setGenericStatus();
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
    if (data.asr) {
      if (ssbAsrEnabledCheck) ssbAsrEnabledCheck.checked = data.asr.enabled !== false;
      if (ssbAsrAvailableBadge) {
        if (data.asr.available) {
          ssbAsrAvailableBadge.textContent = "Whisper installed";
          ssbAsrAvailableBadge.className = "badge bg-success ms-2";
          if (ssbAsrEnabledCheck) ssbAsrEnabledCheck.disabled = false;
        } else {
          ssbAsrAvailableBadge.textContent = "Whisper not installed";
          ssbAsrAvailableBadge.className = "badge bg-warning text-dark ms-2";
          if (ssbAsrEnabledCheck) { ssbAsrEnabledCheck.checked = false; ssbAsrEnabledCheck.disabled = true; }
        }
      }
    }
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
    audio_config: buildAudioConfigPayload(),
    asr: { enabled: ssbAsrEnabledCheck ? ssbAsrEnabledCheck.checked : true },
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

if (saveAsrSettingsBtn) {
  saveAsrSettingsBtn.addEventListener("click", async () => {
    const enabled = ssbAsrEnabledCheck ? ssbAsrEnabledCheck.checked : true;
    try {
      const resp = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeader() },
        body: JSON.stringify({ asr: { enabled } }),
      });
      if (!resp.ok) {
        const message = await parseApiError(resp, "Failed to save ASR setting");
        showToastError(message);
        return;
      }
      showToast(enabled ? "ASR voice transcription enabled" : "ASR voice transcription disabled");
    } catch (err) {
      showToastError("Failed to save ASR setting");
    }
  });
}

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
      
      // During active scan: allow mode change but prevent deselection.
      // Also check latestScanState as a fallback in case isScanRunning was
      // briefly set false by a syncScanState race between polls.
      if (isScanRunning || latestScanState?.state === "running") {
        if (selectedDecoderMode === mode) {
          // Trying to deselect during scan - block it
          showToast("Cannot deselect mode while scanning. Stop the scan first.");
          return;
        }
        // Changing to different mode during scan - clear caches and notify backend
        wfc.clearMarkerCaches();
        latestEvents = []; // Clear events from previous mode
        renderEventsPanelFromCache(); // Refresh empty panel
        
        selectedDecoderMode = mode;
        wfc.recenterForMode(mode);
        // Sync the events panel filter so only events from this mode are shown
        eventsSearchModeInput.value = mode;
        refreshModeButtons();
        logLine(`Mode changed during scan: ${mode}`);
        
        wfc.showTransition(`Switching to mode ${mode}...`);

        const _modeAbort = new AbortController();
        const _modeTimeout = setTimeout(() => _modeAbort.abort(), 15000);
        try {
          const response = await fetch("/api/scan/mode", {
            method: "POST",
            headers: { "Content-Type": "application/json", ...getAuthHeader() },
            body: JSON.stringify({ decoder_mode: mode.toLowerCase() }),
            signal: _modeAbort.signal
          });
          clearTimeout(_modeTimeout);
          if (!response.ok) {
            showToastError(`Failed to switch mode: HTTP ${response.status}`);
          } else {
            showToast(`Mode switched to ${mode}`);
            fetchEvents();
            fetchTotal();
          }
        } catch (err) {
          clearTimeout(_modeTimeout);
          showToastError(`Failed to switch mode: ${err.name === "AbortError" ? "timeout" : err.message}`);
        } finally {
          wfc.hideTransition();
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
        wfc.recenterForMode(mode);
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
        wfc.renderRuler(Number(payload.band.start_hz), Number(payload.band.end_hz));
        wfc.updateVFODisplay(Number(payload.band.start_hz), Number(payload.band.end_hz));
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
        wfc.setGenericStatus("No SDR device detected. Connect your device and start a scan.");
        wfc.drawSpectrumIdle("No SDR device detected. Connect your device and start a scan.");
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


// ---------------------------------------------------------------------------
// Global delegated tooltip for TXT (event-decoded-help) buttons
// Renders a fixed-position overlay so it escapes overflow:hidden containers.
// ---------------------------------------------------------------------------
(function () {
  let _tipEl = null;
  function _ensureTip() {
    if (_tipEl) return _tipEl;
    _tipEl = document.createElement("div");
    _tipEl.className = "event-decoded-tooltip-overlay";
    _tipEl.style.display = "none";
    document.body.appendChild(_tipEl);
    return _tipEl;
  }
  document.addEventListener("mouseover", (e) => {
    const btn = e.target.closest(".event-decoded-help[data-tooltip]");
    if (!btn) return;
    const text = btn.getAttribute("data-tooltip");
    if (!text) return;
    const tip = _ensureTip();
    tip.textContent = text;
    tip.style.display = "";
    const r = btn.getBoundingClientRect();
    const tipW = tip.offsetWidth;
    let left = r.left + r.width / 2 - tipW / 2;
    if (left < 8) left = 8;
    if (left + tipW > window.innerWidth - 8) left = window.innerWidth - tipW - 8;
    let top = r.top - tip.offsetHeight - 6;
    if (top < 4) top = r.bottom + 6;
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  });
  document.addEventListener("mouseout", (e) => {
    const btn = e.target.closest(".event-decoded-help[data-tooltip]");
    if (!btn || !_tipEl) return;
    _tipEl.style.display = "none";
  });
})();
