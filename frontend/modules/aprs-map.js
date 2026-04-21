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

// Local time in Portuguese format DD/MM/YYYY HH:MM (24h).
function _fmtPtLocal(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) return "—";
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(date.getDate())}/${pad(date.getMonth() + 1)}/${date.getFullYear()} `
    + `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

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
  #stackByCall = new Map(); // callsign → vertical stack index (collision)
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
      // Track per-source last event (path/raw/msg/timestamp) — RF + LoRa + TCP
      const src = String(evt.source || "").toLowerCase();
      const hadRF = [...existing.perSource.keys()].some((s) => s !== "aprs_is" && s !== "lora_aprs");
      if (src) {
        existing.perSource.set(src, {
          path: evt.path || "",
          raw: evt.raw || "",
          msg: evt.msg || "",
          ts: evt.timestamp || new Date().toISOString(),
        });
      }
      const hasRF = [...existing.perSource.keys()].some((s) => s !== "aprs_is" && s !== "lora_aprs");
      existing.data = { ...existing.data, ...evt, lastSeenMs: now };
      if (!existing.data.firstSeenMs) existing.data.firstSeenMs = now;
      if (hasPosition) {
        existing.marker.setLatLng([lat, lon]);
      }
      // If station gained RF source, rebuild icon so RF style prevails
      if (hasRF && !hadRF) {
        const emoji = aprsSymbolEmoji(existing.data.symbol_table, existing.data.symbol_code);
        existing.marker.setIcon(this.#buildStationIcon(callsign, "aprs-marker-rf", emoji));
      }
      existing.marker.setPopupContent(this.#buildPopup(existing.data, existing.perSource));
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
    const src = String(evt.source || "").toLowerCase();
    let sourceClass;
    if (src === "aprs_is") sourceClass = "aprs-marker-is";
    else if (src === "lora_aprs") sourceClass = "aprs-marker-lora";
    else sourceClass = "aprs-marker-rf";
    const marker = L.marker([lat, lon], {
      icon: this.#buildStationIcon(callsign, sourceClass, emoji),
    });

    const perSource = new Map();
    if (src) {
      perSource.set(src, {
        path: evt.path || "",
        raw: evt.raw || "",
        msg: evt.msg || "",
        ts: evt.timestamp || new Date().toISOString(),
      });
    }
    const data = { ...evt, firstSeenMs: now, lastSeenMs: now };
    marker.bindPopup(this.#buildPopup(data, perSource));
    this.#markers.set(callsign, { marker, data, perSource, lastSeenMs: now });
    // Only add to map if it passes the active filter
    if (this.#matchesFilter(this.#markers.get(callsign))) {
      marker.addTo(this.#map);
    }
  }

  /**
   * Load a batch of historical events (e.g. from DB on APRS mode entry).
   *
   * Pre-pass: for each callsign, find the most recent event carrying a
   * valid position. Position-less events (digipeated status frames, MIC-E
   * messages without coords, etc.) inherit that position so they still
   * register as markers and contribute their per-source path/timestamp.
   *
   * @param {Array<object>} events - APRS events from the API
   * @param {Map<string, {lat:number, lon:number, ts?:string}>} [positionSnapshot]
   *        Optional callsign → last-known-position map (typically derived
   *        from a wider time window) used as a fallback when no positioned
   *        event exists in `events` for a given callsign.
   */
  loadHistory(events, positionSnapshot) {
    if (!Array.isArray(events)) return;

    // Build per-callsign latest known position from the batch itself.
    const positionByCall = new Map();
    for (const evt of events) {
      const call = String(evt?.callsign || "").trim().toUpperCase();
      if (!call) continue;
      const lat = Number(evt.lat);
      const lon = Number(evt.lon);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
      if (lat === 0 && lon === 0) continue;
      const tsMs = evt.timestamp ? Date.parse(evt.timestamp) : 0;
      const prev = positionByCall.get(call);
      if (!prev || tsMs >= prev.tsMs) {
        positionByCall.set(call, { lat, lon, tsMs });
      }
    }
    // Fall back to the optional wider snapshot for callsigns not positioned
    // in the current activity batch.
    if (positionSnapshot instanceof Map) {
      for (const [call, pos] of positionSnapshot) {
        const key = String(call || "").trim().toUpperCase();
        if (!key || positionByCall.has(key)) continue;
        const lat = Number(pos?.lat);
        const lon = Number(pos?.lon);
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
        positionByCall.set(key, { lat, lon, tsMs: 0 });
      }
    }

    // Resolve marker collisions: when several callsigns share virtually the
    // same coordinate (e.g. CQ0PCB and CQ0DCO-B at the Coimbra repeater
    // site, ~40 m apart) their 120-px wide labels overlap and only the
    // last-drawn marker is visible. A purely geographic offset is too
    // small at typical APRS zoom levels, so we stack the labels vertically
    // by adjusting iconAnchor Y. Compute per-callsign stack index here and
    // store it on the controller so addEvent() can pick it up.
    // Use a 3x3 neighborhood scan over a fine bucket grid so two stations
    // 40 m apart that fall on opposite sides of a bucket boundary still
    // collide. Bucket size = ~110 m, neighborhood reach = ~330 m.
    const COLLISION_BUCKET_DEG = 0.001; // ~110 m at PT latitudes
    const stackByCall = new Map();
    const grid = new Map(); // "bx|by" -> [callsign, ...]
    for (const [call, pos] of positionByCall) {
      const bx = Math.round(pos.lat / COLLISION_BUCKET_DEG);
      const by = Math.round(pos.lon / COLLISION_BUCKET_DEG);
      const key = `${bx}|${by}`;
      if (!grid.has(key)) grid.set(key, []);
      grid.get(key).push(call);
    }
    const visited = new Set();
    for (const [call, pos] of positionByCall) {
      if (visited.has(call)) continue;
      const bx = Math.round(pos.lat / COLLISION_BUCKET_DEG);
      const by = Math.round(pos.lon / COLLISION_BUCKET_DEG);
      const cluster = [];
      for (let dx = -1; dx <= 1; dx++) {
        for (let dy = -1; dy <= 1; dy++) {
          const neighbours = grid.get(`${bx + dx}|${by + dy}`);
          if (!neighbours) continue;
          for (const c of neighbours) if (!visited.has(c)) cluster.push(c);
        }
      }
      cluster.forEach((c) => visited.add(c));
      if (cluster.length < 2) continue;
      cluster.sort();
      cluster.forEach((c, i) => stackByCall.set(c, i));
    }
    this.#stackByCall = stackByCall;

    // Iterate oldest → newest so per-source timestamps reflect the most
    // recent frame and the rendered marker icon picks the latest source.
    const sorted = events.slice().sort((a, b) => {
      const ta = a?.timestamp ? Date.parse(a.timestamp) : 0;
      const tb = b?.timestamp ? Date.parse(b.timestamp) : 0;
      return ta - tb;
    });
    for (const evt of sorted) {
      const call = String(evt?.callsign || "").trim().toUpperCase();
      const lat = Number(evt.lat);
      const lon = Number(evt.lon);
      const hasPos = Number.isFinite(lat) && Number.isFinite(lon) && (lat !== 0 || lon !== 0);
      // Always honour the (possibly collision-resolved) per-callsign
      // position so positioned beacons and digipeated frames render at
      // the same offset coordinate and don't snap back over a neighbour.
      if (call && positionByCall.has(call)) {
        const p = positionByCall.get(call);
        this.addEvent({ ...evt, lat: p.lat, lon: p.lon });
      } else if (hasPos) {
        this.addEvent(evt);
      } else {
        this.addEvent(evt);
      }
    }
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

  /** Check if a marker entry matches the active filter (uses perSource Map keys). */
  #matchesFilter(entry) {
    if (this.#activeFilter === "all") return true;
    const perSource = entry.perSource || new Map();
    if (this.#activeFilter === "rf") {
      // VHF RF only — Direwolf (anything not aprs_is and not lora_aprs).
      for (const s of perSource.keys()) {
        if (s !== "aprs_is" && s !== "lora_aprs") return true;
      }
      return false;
    }
    if (this.#activeFilter === "lora") {
      return perSource.has("lora_aprs");
    }
    if (this.#activeFilter === "rf_tcp") {
      // RF + APRS-IS — excludes LoRa
      for (const s of perSource.keys()) {
        if (s !== "lora_aprs") return true;
      }
      return false;
    }
    if (this.#activeFilter === "lora_tcp") {
      // LoRa + APRS-IS — excludes RF
      return perSource.has("lora_aprs") || perSource.has("aprs_is");
    }
    // tcp filter
    return perSource.has("aprs_is");
  }

  // ── Private ───────────────────────────────────────────────────────────

  /** Build a station icon. When the callsign collides with others at the
   *  same geographic point (per #stackByCall), the icon includes a vertical
   *  leader line and a small dot marking the exact coordinate, with the
   *  label sitting above it; each colliding station gets a taller leader so
   *  every label is readable.
   */
  #buildStationIcon(callsign, sourceClass, emoji) {
    const stackIdx = this.#stackByCall.get(callsign);
    if (stackIdx === undefined) {
      // Solitary marker — keep the original compact icon.
      return L.divIcon({
        className: `aprs-station-icon ${sourceClass}`,
        html: `<span class="aprs-station-label">${emoji} ${callsign}</span>`,
        iconSize: [120, 28],
        iconAnchor: [60, 14],
      });
    }
    // Stacked marker — label + leader line + anchor dot.
    const labelH = 22;
    const dotH = 8;
    const stepPx = 28; // gap between successive labels
    const leaderH = 6 + stackIdx * stepPx; // bottom-most: 6 px, next: 34, 62, ...
    const totalH = labelH + leaderH + dotH;
    return L.divIcon({
      className: `aprs-station-icon ${sourceClass}`,
      html:
        `<div class="aprs-station-stack">` +
          `<span class="aprs-station-label">${emoji} ${callsign}</span>` +
          `<span class="aprs-station-leader" style="height:${leaderH}px"></span>` +
          `<span class="aprs-station-anchor"></span>` +
        `</div>`,
      iconSize: [120, totalH],
      iconAnchor: [60, totalH - dotH / 2],
    });
  }

  #buildPopup(data, perSource) {
    const callsign = data.callsign || "—";
    const lat = Number(data.lat);
    const lon = Number(data.lon);
    const latStr = Number.isFinite(lat) ? lat.toFixed(4) + "°" : "—";
    const lonStr = Number.isFinite(lon) ? lon.toFixed(4) + "°" : "—";
    const emoji = aprsSymbolEmoji(data.symbol_table, data.symbol_code);
    const firstSeen = data.firstSeenMs ? _fmtPtLocal(new Date(data.firstSeenMs)) : "—";
    const lastSeen = data.lastSeenMs ? _fmtPtLocal(new Date(data.lastSeenMs)) : "—";

    // Per-source tracking (path/raw/msg/ts for each source this station was heard on)
    const ps = perSource instanceof Map ? perSource : new Map();
    const hasRF = [...ps.keys()].some((s) => s !== "aprs_is" && s !== "lora_aprs");
    const hasLoRa = ps.has("lora_aprs");
    const hasTCP = ps.has("aprs_is");
    let sourceBadge = "";
    if (hasRF) sourceBadge += '<span class="aprs-source-badge aprs-source-rf">📻 RF</span>';
    if (hasLoRa) sourceBadge += '<span class="aprs-source-badge aprs-source-lora">📡 LoRa</span>';
    if (hasTCP) sourceBadge += '<span class="aprs-source-badge aprs-source-is">🌐 APRS-IS</span>';

    // Distance from QTH
    let distText = "";
    if (Number.isFinite(lat) && Number.isFinite(lon)) {
      const d = this.#haversineKm(this.#qthLat, this.#qthLon, lat, lon);
      distText = `<tr><td><strong>Distance</strong></td><td>${d.toFixed(1)} km</td></tr>`;
    }

    // Build per-source rows (RF / LoRa / APRS-IS) — each with its own path/time
    const srcLabels = {
      direwolf: { icon: "📻", name: "RF" },
      lora_aprs: { icon: "📡", name: "LoRa" },
      aprs_is: { icon: "🌐", name: "APRS-IS" },
    };
    const orderedKeys = ["direwolf", "lora_aprs", "aprs_is"];
    let perSourceRows = "";
    for (const key of orderedKeys) {
      if (!ps.has(key)) continue;
      const info = ps.get(key) || {};
      const label = srcLabels[key] || { icon: "❓", name: key };
      const path = info.path || "—";
      const tsStr = info.ts ? _fmtPtLocal(new Date(info.ts)) : "—";
      perSourceRows += `<tr><td><strong>${label.icon} ${label.name}</strong></td>`
        + `<td><code style="font-size:11px">${this.#escapeHtml(path)}</code>`
        + ` <span style="color:#888;font-size:10px">(${tsStr})</span></td></tr>`;
    }
    // Also handle unknown sources (shouldn't happen normally)
    for (const key of ps.keys()) {
      if (orderedKeys.includes(key)) continue;
      const info = ps.get(key) || {};
      const path = info.path || "—";
      const tsStr = info.ts ? _fmtPtLocal(new Date(info.ts)) : "—";
      perSourceRows += `<tr><td><strong>${this.#escapeHtml(key)}</strong></td>`
        + `<td><code style="font-size:11px">${this.#escapeHtml(path)}</code>`
        + ` <span style="color:#888;font-size:10px">(${tsStr})</span></td></tr>`;
    }

    // Latest message/raw (from most recent event across any source)
    const msg = data.msg || "";
    const raw = data.raw || "";

    return `
      <div class="aprs-popup">
        <div class="aprs-popup__header">${emoji} <strong>${callsign}</strong> ${sourceBadge}</div>
        <table class="aprs-popup__table">
          <tr><td><strong>Position</strong></td><td>${latStr} N &nbsp; ${lonStr} E</td></tr>
          ${distText}
          ${perSourceRows}
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
