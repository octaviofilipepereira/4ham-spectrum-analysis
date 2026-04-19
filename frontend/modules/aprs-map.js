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

// ── Maidenhead grid → lat/lon ────────────────────────────────────────────
function maidenheadToLatLon(locator) {
  const loc = String(locator || "").trim().toUpperCase();
  if (loc.length < 4) return null;
  const A = "A".charCodeAt(0);
  const lon = (loc.charCodeAt(0) - A) * 20 - 180;
  const lat = (loc.charCodeAt(1) - A) * 10 - 90;
  const lonSub = Number(loc[2]) * 2;
  const latSub = Number(loc[3]) * 1;
  let finalLon = lon + lonSub + 1;   // centre of subsquare
  let finalLat = lat + latSub + 0.5;
  if (loc.length >= 6) {
    const lonSS = (loc.charCodeAt(4) - A) * (2 / 24);
    const latSS = (loc.charCodeAt(5) - A) * (1 / 24);
    finalLon = lon + lonSub + lonSS + (1 / 24);
    finalLat = lat + latSub + latSS + (0.5 / 24);
  }
  return { lat: finalLat, lon: finalLon };
}

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

  constructor(containerId) {
    this.#container = document.getElementById(containerId);
  }

  // ── Lifecycle ──────────────────────────────────────────────────────────

  /**
   * Initialise (or re‐centre) the map.
   * @param {string} locator  - Maidenhead grid square (e.g. "IN51mu")
   * @param {string} callsign - Station callsign (e.g. "CT7BFV")
   */
  init(locator, callsign) {
    this.#stationCall = callsign || "";
    const qth = maidenheadToLatLon(locator);
    if (qth) {
      this.#qthLat = qth.lat;
      this.#qthLon = qth.lon;
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
      existing.data = { ...existing.data, ...evt, lastSeenMs: now };
      if (!existing.data.firstSeenMs) existing.data.firstSeenMs = now;
      if (hasPosition) {
        existing.marker.setLatLng([lat, lon]);
      }
      existing.marker.setPopupContent(this.#buildPopup(existing.data));
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
    }).addTo(this.#map);

    const data = { ...evt, firstSeenMs: now, lastSeenMs: now };
    marker.bindPopup(this.#buildPopup(data));
    this.#markers.set(callsign, { marker, data, lastSeenMs: now });
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

  // ── Private ───────────────────────────────────────────────────────────

  #buildPopup(data) {
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

    // Source badge
    const isRF = String(data.source || "").toLowerCase() !== "aprs_is";
    const sourceBadge = isRF
      ? '<span class="aprs-source-badge aprs-source-rf">RF 144.800</span>'
      : '<span class="aprs-source-badge aprs-source-is">APRS-IS</span>';

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
