/*
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
*/

/**
 * DOM Element References
 * Centralized access to DOM elements used throughout the application
 */

export const elements = {
  // Status and info
  status: document.getElementById("status"),
  wsStatus: document.getElementById("wsStatus"),
  copyrightYear: document.getElementById("copyrightYear"),
  
  // Events
  events: document.getElementById("events"),
  eventsSearchCallsign: document.getElementById("eventsSearchCallsign"),
  eventsSearchMode: document.getElementById("eventsSearchMode"),
  eventsSearchGrid: document.getElementById("eventsSearchGrid"),
  eventsSearchReport: document.getElementById("eventsSearchReport"),
  eventsPrev: document.getElementById("eventsPrev"),
  eventsNext: document.getElementById("eventsNext"),
  eventsPageInfo: document.getElementById("eventsPageInfo"),
  eventsSearchResults: document.getElementById("eventsSearchResults"),
  eventsTotal: document.getElementById("eventsTotal"),
  prevPage: document.getElementById("prevPage"),
  nextPage: document.getElementById("nextPage"),
  
  // Waterfall
  waterfall: document.getElementById("waterfall"),
  waterfallCanvas: document.getElementById("waterfallCanvas"),
  waterfallStatus: document.getElementById("waterfallStatus"),
  waterfallModeBadge: document.getElementById("waterfallModeBadge"),
  waterfallFullscreenBtn: document.getElementById("waterfallFullscreenBtn"),
  waterfallExplorerToggle: document.getElementById("waterfallExplorerToggle"),
  waterfallZoom: document.getElementById("waterfallZoom"),
  waterfallResetViewBtn: document.getElementById("waterfallResetViewBtn"),
  waterfallModeOverlay: document.getElementById("waterfallModeOverlay"),
  waterfallRuler: document.getElementById("waterfallRuler"),
  
  // Scan controls
  startBtn: document.getElementById("startScan"),
  deviceSelect: document.getElementById("deviceSelect"),
  bandSelect: document.getElementById("bandSelect"),
  gainInput: document.getElementById("gain"),
  sampleRateInput: document.getElementById("sampleRate"),
  recordPathInput: document.getElementById("recordPath"),
  
  // Filters
  bandFilter: document.getElementById("bandFilter"),
  modeFilter: document.getElementById("modeFilter"),
  callsignFilter: document.getElementById("callsignFilter"),
  startFilter: document.getElementById("startFilter"),
  endFilter: document.getElementById("endFilter"),
  favoriteFilter: document.getElementById("favoriteFilter"),
  
  // Export
  exportCsv: document.getElementById("exportCsv"),
  exportJson: document.getElementById("exportJson"),
  exportPng: document.getElementById("exportPng"),
  exportPresets: document.getElementById("exportPresets"),
  importPresets: document.getElementById("importPresets"),
  
  // Settings
  authUser: document.getElementById("authUser"),
  authPass: document.getElementById("authPass"),
  saveSettings: document.getElementById("saveSettings"),
  testConfig: document.getElementById("testConfig"),
  refreshDevices: document.getElementById("refreshDevices"),
  resetDefaults: document.getElementById("resetDefaults"),
  resetAllConfig: document.getElementById("resetAllConfig"),
  showNonSdrDevices: document.getElementById("showNonSdrDevices"),
  
  // Station info
  stationCallsign: document.getElementById("stationCallsign"),
  stationOperator: document.getElementById("stationOperator"),
  stationLocator: document.getElementById("stationLocator"),
  stationQth: document.getElementById("stationQth"),
  
  // Device config
  deviceClass: document.getElementById("deviceClass"),
  devicePpm: document.getElementById("devicePpm"),
  deviceOffsetHz: document.getElementById("deviceOffsetHz"),
  deviceGainProfile: document.getElementById("deviceGainProfile"),
  saveDeviceConfig: document.getElementById("saveDeviceConfig"),
  
  // Audio config
  audioInputDevice: document.getElementById("audioInputDevice"),
  audioOutputDevice: document.getElementById("audioOutputDevice"),
  audioSampleRate: document.getElementById("audioSampleRate"),
  audioRxGain: document.getElementById("audioRxGain"),
  audioTxGain: document.getElementById("audioTxGain"),
  saveAudioConfig: document.getElementById("saveAudioConfig"),
  
  // Admin
  adminDeviceSetup: document.getElementById("adminDeviceSetup"),
  adminAudioAutoDetect: document.getElementById("adminAudioAutoDetect"),
  purgeInvalidEvents: document.getElementById("purgeInvalidEvents"),
  adminSetupStatus: document.getElementById("adminSetupStatus"),
  
  // Bands and presets
  bandName: document.getElementById("bandName"),
  bandStart: document.getElementById("bandStart"),
  bandEnd: document.getElementById("bandEnd"),
  saveBand: document.getElementById("saveBand"),
  presetName: document.getElementById("presetName"),
  savePreset: document.getElementById("savePreset"),
  deletePreset: document.getElementById("deletePreset"),
  presetSelect: document.getElementById("presetSelect"),
  favoriteBands: document.getElementById("favoriteBands"),
  addFavorite: document.getElementById("addFavorite"),
  removeFavorite: document.getElementById("removeFavorite"),
  
  // Logs
  logs: document.getElementById("logs"),
  
  // Quick bands
  quickBandButtons: Array.from(document.querySelectorAll("[data-quick-band]")),
  
  // Toast
  toast: document.getElementById("toast"),
  
  // Login
  loginUser: document.getElementById("loginUser"),
  loginPass: document.getElementById("loginPass"),
  loginSave: document.getElementById("loginSave"),
  loginStatus: document.getElementById("loginStatus"),
  
  // Onboarding
  onboarding: document.getElementById("onboarding"),
  onboardingTitle: document.getElementById("onboardingTitle"),
  onboardingText: document.getElementById("onboardingText"),
  onboardingPrev: document.getElementById("onboardingPrev"),
  onboardingNext: document.getElementById("onboardingNext"),
  
  // Quality and propagation
  qualityBar: document.getElementById("qualityBar"),
  qualityLabel: document.getElementById("qualityLabel"),
  summaryMatrixTable: document.getElementById("summaryMatrixTable"),
  summaryMatrixCaption: document.getElementById("summaryMatrixCaption"),
  propagationScore: document.getElementById("propagationScore"),
  propagationBands: document.getElementById("propagationBands"),
  compactToggle: document.getElementById("compactToggle"),
  
  // Decoders
  decoderStatus: document.getElementById("decoderStatus"),
  externalFtStatus: document.getElementById("externalFtStatus"),
  kissStatus: document.getElementById("kissStatus"),
  decoderLastEvent: document.getElementById("decoderLastEvent"),
  agcStatus: document.getElementById("agcStatus"),
  ft8Toggle: document.getElementById("ft8Toggle"),
  aprsToggle: document.getElementById("aprsToggle"),
  cwToggle: document.getElementById("cwToggle"),
  ssbToggle: document.getElementById("ssbToggle"),
  saveModes: document.getElementById("saveModes"),
};
