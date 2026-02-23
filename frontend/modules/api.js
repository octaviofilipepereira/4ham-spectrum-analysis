/*
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
*/

/**
 * API Client
 * Handles all REST API calls to the backend
 */

import { API_ENDPOINTS } from './config.js';
import { showToast } from './ui.js';

/**
 * Make a fetch request with optional authentication
 */
async function fetchWithAuth(url, options = {}) {
  const auth = getStoredAuth();
  
  const headers = {
    'Content-Type': 'application/json',
    ...options.headers
  };
  
  if (auth && auth.user && auth.pass) {
    const credentials = btoa(`${auth.user}:${auth.pass}`);
    headers['Authorization'] = `Basic ${credentials}`;
  }
  
  const response = await fetch(url, {
    ...options,
    headers
  });
  
  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || `HTTP ${response.status}`);
  }
  
  return response;
}

/**
 * Get stored authentication credentials
 */
function getStoredAuth() {
  try {
    const user = localStorage.getItem('auth_user');
    const pass = localStorage.getItem('auth_pass');
    return { user, pass };
  } catch (e) {
    return { user: null, pass: null };
  }
}

/**
 * Store authentication credentials
 */
export function storeAuth(user, pass) {
  try {
    localStorage.setItem('auth_user', user);
    localStorage.setItem('auth_pass', pass);
    return true;
  } catch (e) {
    console.error('Failed to store auth:', e);
    return false;
  }
}

/**
 * Clear stored authentication
 */
export function clearAuth() {
  try {
    localStorage.removeItem('auth_user');
    localStorage.removeItem('auth_pass');
  } catch (e) {
    console.error('Failed to clear auth:', e);
  }
}

// ========================================
// Health API
// ========================================

export async function checkHealth() {
  const response = await fetchWithAuth(API_ENDPOINTS.HEALTH);
  return response.json();
}

// ========================================
// Device API
// ========================================

export async function getDevices(includeNonSdr = false) {
  const url = `${API_ENDPOINTS.DEVICES}?include_non_sdr=${includeNonSdr}`;
  const response = await fetchWithAuth(url);
  return response.json();
}

// ========================================
// Scan API
// ========================================

export async function startScan(config) {
  const response = await fetchWithAuth(API_ENDPOINTS.SCAN_START, {
    method: 'POST',
    body: JSON.stringify(config)
  });
  return response.json();
}

export async function stopScan() {
  const response = await fetchWithAuth(API_ENDPOINTS.SCAN_STOP, {
    method: 'POST'
  });
  return response.json();
}

export async function getScanStatus() {
  const response = await fetchWithAuth(API_ENDPOINTS.SCAN_STATUS);
  return response.json();
}

// ========================================
// Events API
// ========================================

export async function getEvents(params = {}) {
  const queryParams = new URLSearchParams();
  
  Object.keys(params).forEach(key => {
    if (params[key] !== null && params[key] !== undefined && params[key] !== '') {
      queryParams.append(key, params[key]);
    }
  });
  
  const url = `${API_ENDPOINTS.EVENTS}?${queryParams.toString()}`;
  const response = await fetchWithAuth(url);
  return response.json();
}

export async function exportEventsCsv(params = {}) {
  const queryParams = new URLSearchParams(params);
  const url = `${API_ENDPOINTS.EVENTS_EXPORT_CSV}?${queryParams.toString()}`;
  const response = await fetchWithAuth(url);
  return response.blob();
}

export async function exportEventsJson(params = {}) {
  const queryParams = new URLSearchParams(params);
  const url = `${API_ENDPOINTS.EVENTS_EXPORT_JSON}?${queryParams.toString()}`;
  const response = await fetchWithAuth(url);
  return response.blob();
}

// ========================================
// Settings API
// ========================================

export async function getSettings() {
  const response = await fetchWithAuth(API_ENDPOINTS.SETTINGS);
  return response.json();
}

export async function updateSettings(settings) {
  const response = await fetchWithAuth(API_ENDPOINTS.SETTINGS, {
    method: 'POST',
    body: JSON.stringify(settings)
  });
  return response.json();
}

// ========================================
// Logs API
// ========================================

export async function getLogs(limit = 100) {
  const url = `${API_ENDPOINTS.LOGS}?limit=${limit}`;
  const response = await fetchWithAuth(url);
  return response.json();
}

// ========================================
// Admin API
// ========================================

export async function adminDeviceSetup() {
  const response = await fetchWithAuth(API_ENDPOINTS.ADMIN_DEVICE_SETUP, {
    method: 'POST'
  });
  return response.json();
}

export async function adminAudioDetect() {
  const response = await fetchWithAuth(API_ENDPOINTS.ADMIN_AUDIO_DETECT, {
    method: 'POST'
  });
  return response.json();
}

export async function adminPurgeInvalidEvents() {
  const response = await fetchWithAuth(API_ENDPOINTS.ADMIN_PURGE, {
    method: 'POST'
  });
  return response.json();
}

// ========================================
// Decoders API
// ========================================

export async function getDecodersStatus() {
  const response = await fetchWithAuth(API_ENDPOINTS.DECODERS_STATUS);
  return response.json();
}

export async function startDecoder(decoderType) {
  const response = await fetchWithAuth(`${API_ENDPOINTS.DECODERS_START}/${decoderType}`, {
    method: 'POST'
  });
  return response.json();
}

export async function stopDecoder(decoderType) {
  const response = await fetchWithAuth(`${API_ENDPOINTS.DECODERS_STOP}/${decoderType}`, {
    method: 'POST'
  });
  return response.json();
}
