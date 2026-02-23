/*
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
*/

/**
 * WebSocket Manager
 * Handles WebSocket connections with automatic reconnection
 */

import { WEBSOCKET_ENDPOINTS, RECONNECT_DELAY } from './config.js';
import { updateWsStatus, showToast } from './ui.js';

export class WebSocketManager {
  constructor(endpoint, onMessage) {
    this.endpoint = endpoint;
    this.onMessage = onMessage;
    this.ws = null;
    this.reconnectTimer = null;
    this.manualClose = false;
  }

  /**
   * Connect to the WebSocket
   */
  connect() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      return; // Already connected
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}${this.endpoint}`;

    try {
      this.ws = new WebSocket(wsUrl);
      
      this.ws.onopen = () => {
        console.log(`WebSocket connected: ${this.endpoint}`);
        updateWsStatus(true);
        if (this.reconnectTimer) {
          clearTimeout(this.reconnectTimer);
          this.reconnectTimer = null;
        }
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (this.onMessage) {
            this.onMessage(data);
          }
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e);
        }
      };

      this.ws.onerror = (error) => {
        console.error(`WebSocket error on ${this.endpoint}:`, error);
      };

      this.ws.onclose = () => {
        console.log(`WebSocket closed: ${this.endpoint}`);
        updateWsStatus(false);
        
        // Attempt reconnection if not manually closed
        if (!this.manualClose) {
          this.scheduleReconnect();
        }
      };
    } catch (e) {
      console.error(`Failed to create WebSocket: ${this.endpoint}`, e);
      this.scheduleReconnect();
    }
  }

  /**
   * Schedule a reconnection attempt
   */
  scheduleReconnect() {
    if (this.reconnectTimer) {
      return; // Already scheduled
    }

    this.reconnectTimer = setTimeout(() => {
      console.log(`Attempting to reconnect: ${this.endpoint}`);
      this.reconnectTimer = null;
      this.connect();
    }, RECONNECT_DELAY);
  }

  /**
   * Close the WebSocket connection
   */
  close() {
    this.manualClose = true;
    
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    
    updateWsStatus(false);
  }

  /**
   * Send a message through the WebSocket
   */
  send(data) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
      return true;
    }
    return false;
  }
}

/**
 * Create WebSocket managers for all endpoints
 */
export function createWebSocketManagers(handlers) {
  const managers = {
    spectrum: new WebSocketManager(
      WEBSOCKET_ENDPOINTS.SPECTRUM,
      handlers.onSpectrum
    ),
    events: new WebSocketManager(
      WEBSOCKET_ENDPOINTS.EVENTS,
      handlers.onEvent
    ),
    logs: new WebSocketManager(
      WEBSOCKET_ENDPOINTS.LOGS,
      handlers.onLog
    ),
    status: new WebSocketManager(
      WEBSOCKET_ENDPOINTS.STATUS,
      handlers.onStatus
    )
  };

  return managers;
}

/**
 * Connect all WebSocket managers
 */
export function connectAll(managers) {
  Object.values(managers).forEach(manager => manager.connect());
}

/**
 * Close all WebSocket managers
 */
export function closeAll(managers) {
  Object.values(managers).forEach(manager => manager.close());
}
