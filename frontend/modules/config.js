/*
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
*/

/**
 * Application Configuration
 * Constants and default settings
 */

export const DEVICE_AUTO_PROFILES = {
  rtl: { 
    sample_rate: 2048000, 
    gain: 30, 
    ppm_correction: 0, 
    frequency_offset_hz: 0, 
    gain_profile: "auto" 
  },
  hackrf: { 
    sample_rate: 2000000, 
    gain: 40, 
    ppm_correction: 0, 
    frequency_offset_hz: 0, 
    gain_profile: "auto" 
  },
  airspy: { 
    sample_rate: 2500000, 
    gain: 21, 
    ppm_correction: 0, 
    frequency_offset_hz: 0, 
    gain_profile: "auto" 
  },
  sdrplay: { 
    sample_rate: 2048000, 
    gain: 50, 
    ppm_correction: 0, 
    frequency_offset_hz: 0, 
    gain_profile: "auto" 
  },
  lime: { 
    sample_rate: 2000000, 
    gain: 50, 
    ppm_correction: 0, 
    frequency_offset_hz: 0, 
    gain_profile: "auto" 
  },
};

export const WATERFALL_CONFIG = {
  DEFAULT_ZOOM: 1.0,
  MIN_ZOOM: 0.5,
  MAX_ZOOM: 10.0,
  ZOOM_STEP: 0.5,
  SCROLL_HEIGHT: 512,
  DEFAULT_RENDERER: "2d"
};

export const PAGINATION = {
  DEFAULT_PAGE_SIZE: 50,
  MAX_PAGE_SIZE: 1000
};

export const API_ENDPOINTS = {
  HEALTH: "/api/health",
  DEVICES: "/api/devices",
  SCAN_START: "/api/scan/start",
  SCAN_STOP: "/api/scan/stop",
  SCAN_STATUS: "/api/scan/status",
  EVENTS: "/api/events",
  EVENTS_EXPORT_CSV: "/api/events/export/csv",
  EVENTS_EXPORT_JSON: "/api/events/export/json",
  SETTINGS: "/api/settings",
  LOGS: "/api/logs",
  ADMIN_DEVICE_SETUP: "/api/admin/device/setup",
  ADMIN_AUDIO_DETECT: "/api/admin/audio/detect",
  ADMIN_PURGE: "/api/admin/events/purge",
  DECODERS_STATUS: "/api/decoders/status",
  DECODERS_START: "/api/decoders/start",
  DECODERS_STOP: "/api/decoders/stop",
};

export const WEBSOCKET_ENDPOINTS = {
  SPECTRUM: "/ws/spectrum",
  EVENTS: "/ws/events",
  LOGS: "/ws/logs",
  STATUS: "/ws/status"
};

export const TOAST_DURATION = 3000;

export const RECONNECT_DELAY = 3000;

export const ONBOARDING_STEPS = [
  {
    title: "Bem-vindo ao 4ham Spectrum Analysis",
    text: "Esta aplicação permite monitorizar o espectro de rádio amador em tempo real."
  },
  {
    title: "Configuração do Dispositivo",
    text: "Configure o seu dispositivo SDR nas definições. Suportamos RTL-SDR, HackRF, Airspy e outros."
  },
  {
    title: "Scan de Bandas",
    text: "Selecione uma banda e inicie o scan para começar a monitorizar."
  },
  {
    title: "Eventos e Decoders",
    text: "A aplicação deteta automaticamente sinais e decodifica modos digitais como FT8, APRS e CW."
  },
  {
    title: "Waterfall",
    text: "Visualize o espectro em tempo real com o waterfall interativo."
  }
];
