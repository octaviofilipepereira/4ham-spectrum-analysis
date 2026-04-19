// ─────────────────────────────────────────────────────────────────────────────
// APRSMapController — Leaflet map for APRS mode.
// Replaces the waterfall panel when APRS decoder mode is active.
//
// Features:
//  • Centred on the station QTH (Maidenhead grid → lat/lon)
//  • Range‐circle showing configurable radius (default 50 km)
//  • Live markers for every APRS station with position
//  • Rich popups: callsign, coords, path, message, symbol, timestamps
//  • Marker TTL: 30 min without activity → marker removed
//  • On enter: loads recent APRS events from the DB
// ─────────────────────────────────────────────────────────────────────────────

/* global L */

export const APRS_MARKER_TTL_MS = 30 * 60 * 1000; // 30 minutes
const APRS_RANGE_KM = 50;
const APRS_CLEANUP_INTERVAL_MS = 60 * 1000; // check every minute
const APRS_RECENT_WINDOW_MIN = 30; // load events from last 30 min on init

import { maidenheadToLatLon } from "./utils.js";

// ── APRS symbol → emoji (best-effort) ───────────────────────────────────
function aprsSymbolEmoji(table, code) {
  if (!code) return "📡";
  const c = code.charCodeAt ? code : String.fromCharCode(code);
  // Primary table symbols
  const map = {
    ">": "🚗", "k": "🚚", "b": "🚲", "R": "🚐", "Y": "⛵",
    "f": "🚒", "a": "🚑", "U": "🚌", "v": "🚐", "j": "🏍️",
    "[": "🏃", "O": "🎈", "^": "✈️", "X": "🚁", "'": "✈️",
    "-": "🏠", "#": "📡", "&": "⛽", "n": "📶", "r": "📻",
    "I": "📻", "/": "⚡", "\\": "⚡", "_": "🌤️", "W": "🌊",
  };
  return map[c] || "📍";
}

// ─────────────────────────────────────────────────────────────────────────────

export class APRSMapController {
  #container;
  #map = null;
  #qthMarker = null;
  #rangeCircle = null;
  #markers = new Map(); // callsign → { marker, data, lastSeenMs }
  #cleanupTimer = null;
  #qthLat = 39.5;
  #qthLon = -8.0;
  #stationCall = "";
  #activeFilter = "all"; // "all" | "rf" | "tcp"

  constructor(containerId) {
    this.#container = document.getElementById(containerId);
  }

  // ── Lifecycle ──────────────────────────────────────────────────────────

  /**
   * Initialise (or re‐centre) the map.
   * @param {string} locator  - Maidenhead grid square (e.g. "IN51mu")
   * @param {string} callsign - Station callsign (e.g. "CT7BFV")
   * @param {number|null} exactLat - Optional exact latitude (overrides locator)
   * @param {number|null} exactLon - Optional exact longitude (overrides locator)
   */
  init(locator, callsign, exactLat = null, exactLon = null) {
    this.#stationCall = callsign || "";
    if (Number.isFinite(exactLat) && Number.isFinite(exactLon)) {
      this.#qthLat = exactLat;
      this.#qthLon = exactLon;
    } else {
      const qth = maidenheadToLatLon(locator);
      if (qth) {
        this.#qthLat = qth.lat;
        this.#qthLon = qth.lon;
      }
    }

    if (!this.#map) {
      this.#map = L.map(this.#container, {
        center: [this.#qthLat, this.#qthLon],
        zoom: 11,
        zoomControl: true,
        attributionControl: true,
        scrollWheelZoom: false,
      });
      // Ctrl+scroll to zoom (prevents accidental zoom while scrolling the page)
      this.#container.addEventListener("wheel", (e) => {
        if (e.ctrlKey) {
          e.preventDefault();
          const delta = e.deltaY < 0 ? 1 : -1;
          this.#map.zoomIn(delta);
        }
      }, { passive: false });
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 18,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>',
      }).addTo(this.#map);
    } else {
      this.#map.setView([this.#qthLat, this.#qthLon], 11);
    }

    // QTH marker
    if (this.#qthMarker) this.#map.removeLayer(this.#qthMarker);
    this.#qthMarker = L.marker([this.#qthLat, this.#qthLon], {
      icon: L.divIcon({
        className: "aprs-qth-icon",
        html: `<span class="aprs-qth-label">📻 ${this.#stationCall || "QTH"}</span>`,
        iconSize: [80, 28],
        iconAnchor: [40, 14],
      }),
      zIndexOffset: 1000,
    }).addTo(this.#map);
    this.#qthMarker.bindPopup(
      `<strong>${this.#stationCall || "QTH"}</strong><br>` +
      `Grid: ${locator || "—"}<br>` +
      `${this.#qthLat.toFixed(4)}°N  ${this.#qthLon.toFixed(4)}°E`
    );

    // Range circle
    if (this.#rangeCircle) this.#map.removeLayer(this.#rangeCircle);
    this.#rangeCircle = L.circle([this.#qthLat, this.#qthLon], {
      radius: APRS_RANGE_KM * 1000,
      color: "#00bfff",
      fillColor: "#00bfff",
      fillOpacity: 0.05,
      weight: 1,
      dashArray: "6 4",
    }).addTo(this.#map);

    // Start cleanup timer
    if (!this.#cleanupTimer) {
      this.#cleanupTimer = setInterval(() => this.#expireMarkers(), APRS_CLEANUP_INTERVAL_MS);
    }

    // Force Leaflet to recalculate layout (container may have been hidden)
    setTimeout(() => this.#map?.invalidateSize(), 200);
  }

  /** Show the map container. */
  show() {
    if (this.#container) this.#container.hidden = false;
    setTimeout(() => this.#map?.invalidateSize(), 100);
  }

  /** Hide the map container. */
  hide() {
    if (this.#container) this.#container.hidden = true;
  }

  /** Clean up on mode switch away from APRS. */
  destroy() {
    if (this.#cleanupTimer) {
      clearInterval(this.#cleanupTimer);
      this.#cleanupTimer = null;
    }
    // Keep map instance alive (just hide) — avoids re-download of tiles
  }

  /** Return true if the map has been initialised. */
  get isReady() { return this.#map !== null; }

  /** Notify Leaflet that the container size changed (e.g. fullscreen toggle). */
  invalidateSize() { if (this.#map) this.#map.invalidateSize(); }

  // ── Marker management ─────────────────────────────────────────────────

  /**
   * Add or update a station marker from an APRS event.
   * @param {object} evt - event with callsign, lat, lon, path, msg, etc.
   */
  addEvent(evt) {
    if (!evt || !this.#map) return;
    const callsign = String(evt.callsign || "").trim().toUpperCase();
    if (!callsign) return;
    const lat = Number(evt.lat);
    const lon = Number(evt.lon);
    const hasPosition = Number.isFinite(lat) && Number.isFinite(lon) && (lat !== 0 || lon !== 0);

    const now = Date.now();
    const existing = this.#markers.get(callsign);

    if (existing) {
      // Update existing marker data
      existing.lastSeenMs = now;
      // Track all sources this station was received from (RF + TCP)
      const src = String(evt.source || "").toLowerCase();
      if (src) existing.sources.add(src);
      existing.data = { ...existing.data, ...evt, lastSeenMs: now };
      if (!existing.data.firstSeenMs) existing.data.firstSeenMs = now;
      if (hasPosition) {
        existing.marker.setLatLng([lat, lon]);
      }
      existing.marker.setPopupContent(this.#buildPopup(existing.data, existing.sources));
      // Re-evaluate filter visibility (source may have changed)
      const visible = this.#matchesFilter(existing);
      if (visible && !this.#map.hasLayer(existing.marker)) {
        existing.marker.addTo(this.#map);
      }
      return;
    }

    // New station — only add if we have position
    if (!hasPosition) return;

    const emoji = aprsSymbolEmoji(evt.symbol_table, evt.symbol_code);
    const isRF = String(evt.source || "").toLowerCase() !== "aprs_is";
    const sourceClass = isRF ? "aprs-marker-rf" : "aprs-marker-is";
    const marker = L.marker([lat, lon], {
      icon: L.divIcon({
        className: `aprs-station-icon ${sourceClass}`,
        html: `<span class="aprs-station-label">${emoji} ${callsign}</span>`,
        iconSize: [120, 28],
        iconAnchor: [60, 14],
      }),
    });

    const sources = new Set();
    const src = String(evt.source || "").toLowerCase();
    if (src) sources.add(src);
    const data = { ...evt, firstSeenMs: now, lastSeenMs: now };
    marker.bindPopup(this.#buildPopup(data, sources));
    this.#markers.set(callsign, { marker, data, sources, lastSeenMs: now });
    // Only add to map if it passes the active filter
    if (this.#matchesFilter(this.#markers.get(callsign))) {
      marker.addTo(this.#map);
    }
  }

  /** Load a batch of historical events (e.g. from DB on APRS mode entry). */
  loadHistory(events) {
    if (!Array.isArray(events)) return;
    events.forEach((evt) => this.addEvent(evt));
  }

  /** Remove all station markers (not QTH). */
  clearMarkers() {
    for (const [, entry] of this.#markers) {
      this.#map?.removeLayer(entry.marker);
    }
    this.#markers.clear();
  }

  get markerCount() { return this.#markers.size; }

  /** Return the count of currently visible markers (respects active filter). */
  get filteredMarkerCount() {
    if (this.#activeFilter === "all") return this.#markers.size;
    let count = 0;
    for (const [, entry] of this.#markers) {
      if (this.#matchesFilter(entry)) count++;
    }
    return count;
  }

  /**
   * Filter markers by source: "all", "rf", or "tcp".
   * @param {string} filter
   */
  applyFilter(filter) {
    this.#activeFilter = filter;
    for (const [, entry] of this.#markers) {
      const visible = this.#matchesFilter(entry);
      if (visible && !this.#map.hasLayer(entry.marker)) {
        entry.marker.addTo(this.#map);
      } else if (!visible && this.#map.hasLayer(entry.marker)) {
        this.#map.removeLayer(entry.marker);
      }
    }
  }

  /** Check if a marker entry matches the active filter (uses sources Set). */
  #matchesFilter(entry) {
    if (this.#activeFilter === "all") return true;
    const sources = entry.sources || new Set();
    if (this.#activeFilter === "rf") {
      // Any non-aprs_is source counts as RF
      for (const s of sources) {
        if (s !== "aprs_is") return true;
      }
      return false;
    }
    // tcp filter
    return sources.has("aprs_is");
  }

  // ── Private ───────────────────────────────────────────────────────────

  #buildPopup(data, sources) {
    const callsign = data.callsign || "—";
    const lat = Number(data.lat);
    const lon = Number(data.lon);
    const latStr = Number.isFinite(lat) ? lat.toFixed(4) + "°" : "—";
    const lonStr = Number.isFinite(lon) ? lon.toFixed(4) + "°" : "—";
    const path = data.path || "—";
    const msg = data.msg || "";
    const raw = data.raw || "";
    const emoji = aprsSymbolEmoji(data.symbol_table, data.symbol_code);
    const firstSeen = data.firstSeenMs ? new Date(data.firstSeenMs).toLocaleTimeString() : "—";
    const lastSeen = data.lastSeenMs ? new Date(data.lastSeenMs).toLocaleTimeString() : "—";

    // Source badges — show all sources this station was received from
    const srcSet = sources || new Set();
    const hasRF = [...srcSet].some((s) => s !== "aprs_is");
    const hasTCP = srcSet.has("aprs_is");
    let sourceBadge = "";
    if (hasRF) sourceBadge += '<span class="aprs-source-badge aprs-source-rf">📻 RF</span>';
    if (hasTCP) sourceBadge += '<span class="aprs-source-badge aprs-source-is">🌐 APRS-IS</span>';

    // Distance from QTH
    let distText = "";
    if (Number.isFinite(lat) && Number.isFinite(lon)) {
      const d = this.#haversineKm(this.#qthLat, this.#qthLon, lat, lon);
      distText = `<tr><td><strong>Distance</strong></td><td>${d.toFixed(1)} km</td></tr>`;
    }

    return `
      <div class="aprs-popup">
        <div class="aprs-popup__header">${emoji} <strong>${callsign}</strong> ${sourceBadge}</div>
        <table class="aprs-popup__table">
          <tr><td><strong>Position</strong></td><td>${latStr} N &nbsp; ${lonStr} E</td></tr>
          ${distText}
          <tr><td><strong>Path</strong></td><td>${this.#escapeHtml(path)}</td></tr>
          ${msg ? `<tr><td><strong>Comment</strong></td><td>${this.#escapeHtml(msg)}</td></tr>` : ""}
          ${raw && raw !== msg ? `<tr><td><strong>Raw</strong></td><td style="font-size:10px;word-break:break-all">${this.#escapeHtml(raw)}</td></tr>` : ""}
          <tr><td><strong>First seen</strong></td><td>${firstSeen}</td></tr>
          <tr><td><strong>Last seen</strong></td><td>${lastSeen}</td></tr>
        </table>
      </div>`;
  }

  #expireMarkers() {
    const now = Date.now();
    for (const [callsign, entry] of this.#markers) {
      if ((now - entry.lastSeenMs) > APRS_MARKER_TTL_MS) {
        this.#map?.removeLayer(entry.marker);
        this.#markers.delete(callsign);
      }
    }
  }

  #haversineKm(lat1, lon1, lat2, lon2) {
    const R = 6371;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) ** 2 +
              Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
              Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }

  #escapeHtml(str) {
    const d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
  }
}
