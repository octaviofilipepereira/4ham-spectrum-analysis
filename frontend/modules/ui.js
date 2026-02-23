/*
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
*/

/**
 * UI Utilities
 * Toast notifications, modals, and other UI helpers
 */

import { elements } from './dom.js';
import { TOAST_DURATION } from './config.js';

/**
 * Show a toast notification
 */
export function showToast(message, type = 'info', duration = TOAST_DURATION) {
  if (!elements.toast) return;
  
  const toast = elements.toast;
  
  // Remove existing type classes
  toast.classList.remove('bg-success', 'bg-danger', 'bg-warning', 'bg-info');
  
  // Add appropriate type class
  switch (type) {
    case 'success':
      toast.classList.add('bg-success');
      break;
    case 'error':
    case 'danger':
      toast.classList.add('bg-danger');
      break;
    case 'warning':
      toast.classList.add('bg-warning');
      break;
    default:
      toast.classList.add('bg-info');
  }
  
  // Set message
  toast.textContent = message;
  
  // Show toast
  toast.classList.remove('d-none');
  toast.classList.add('show');
  
  // Auto-hide after duration
  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => {
      toast.classList.add('d-none');
    }, 300);
  }, duration);
}

/**
 * Update status indicator
 */
export function updateStatus(message, type = 'info') {
  if (!elements.status) return;
  
  const status = elements.status;
  
  // Remove existing type classes
  status.classList.remove('alert-success', 'alert-danger', 'alert-warning', 'alert-info');
  
  // Add appropriate type class
  switch (type) {
    case 'success':
      status.classList.add('alert-success');
      break;
    case 'error':
    case 'danger':
      status.classList.add('alert-danger');
      break;
    case 'warning':
      status.classList.add('alert-warning');
      break;
    default:
      status.classList.add('alert-info');
  }
  
  status.textContent = message;
}

/**
 * Update WebSocket connection status
 */
export function updateWsStatus(connected) {
  if (!elements.wsStatus) return;
  
  const wsStatus = elements.wsStatus;
  
  if (connected) {
    wsStatus.classList.remove('badge-danger');
    wsStatus.classList.add('badge-success');
    wsStatus.textContent = 'Connected';
  } else {
    wsStatus.classList.remove('badge-success');
    wsStatus.classList.add('badge-danger');
    wsStatus.textContent = 'Disconnected';
  }
}

/**
 * Format frequency for display
 */
export function formatFrequency(freqHz) {
  if (freqHz >= 1e9) {
    return `${(freqHz / 1e9).toFixed(3)} GHz`;
  } else if (freqHz >= 1e6) {
    return `${(freqHz / 1e6).toFixed(3)} MHz`;
  } else if (freqHz >= 1e3) {
    return `${(freqHz / 1e3).toFixed(1)} kHz`;
  } else {
    return `${freqHz} Hz`;
  }
}

/**
 * Format timestamp for display
 */
export function formatTimestamp(timestamp) {
  try {
    const date = new Date(timestamp);
    return date.toLocaleString();
  } catch (e) {
    return timestamp;
  }
}

/**
 * Normalize number input value
 */
export function normalizeNumberInputValue(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

/**
 * Download a file blob
 */
export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * Escape HTML to prevent XSS
 */
export function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Debounce function calls
 */
export function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

/**
 * Throttle function calls
 */
export function throttle(func, limit) {
  let inThrottle;
  return function executedFunction(...args) {
    if (!inThrottle) {
      func(...args);
      inThrottle = true;
      setTimeout(() => inThrottle = false, limit);
    }
  };
}
