// © 2026 Octávio Filipe Gonçalves – CT7BFV
// License: GNU AGPL-3.0
// Propagation World Map — requires d3.min.js + topojson.min.js loaded first.

(function () {
  "use strict";

  // ── Band colour palette (standard ham convention) ──────────────────────────
  const BAND_COLORS = {
    "160m": "#cc2200",
    "80m":  "#e0507a",
    "40m":  "#f5a623",
    "20m":  "#3b82f6",
    "17m":  "#22c55e",
    "15m":  "#a855f7",
    "12m":  "#06b6d4",
    "10m":  "#ef4444",
    "6m":   "#f97316",
    "2m":   "#84cc16",
    "70cm": "#ec4899",
  };
  const DEFAULT_COLOR = "#9ca3af";

  function bandColor(band) {
    return BAND_COLORS[(band || "").toLowerCase()] || DEFAULT_COLOR;
  }

  // ── Get auth header from localStorage (same as app.js) ───────────────────
  function authHeader() {
    const u = localStorage.getItem("authUser");
    const p = localStorage.getItem("authPass");
    if (u && p) return { Authorization: "Basic " + btoa(u + ":" + p) };
    return {};
  }

  // ── Main module ───────────────────────────────────────────────────────────
  let _worldData = null;
  let _refreshTimer = null;
  let _lastStation = null;

  async function loadWorld() {
    if (_worldData) return _worldData;
    try {
      const resp = await fetch("/lib/countries-110m.json");
      _worldData = await resp.json();
    } catch (e) {
      console.warn("[map] Failed to load world atlas:", e);
      _worldData = null;
    }
    return _worldData;
  }

  function greatCircleArc(proj, lon1, lat1, lon2, lat2) {
    const line = d3.geoInterpolate([lon1, lat1], [lon2, lat2]);
    const points = d3.range(0, 1.01, 0.02).map((t) => line(t));
    return points.map((p) => proj(p)).filter(Boolean);
  }

  function pointsToPath(pts) {
    if (!pts || pts.length < 2) return "";
    return "M" + pts[0].join(",") + pts.slice(1).map((p) => "L" + p.join(",")).join("");
  }

  async function render(containerId, windowMinutes) {
    const d3g = window.d3;
    const topo = window.topojson;
    if (!d3g || !topo) {
      console.warn("[map] d3 or topojson not loaded");
      return;
    }

    const container = document.getElementById(containerId);
    if (!container) return;

    // Dimensions
    const W = container.clientWidth || 400;
    const H = Math.min(W * 0.6, 320);

    // Fetch contacts from backend
    let data;
    try {
      const resp = await fetch(
        `/api/map/contacts?window_minutes=${windowMinutes}&limit=500`,
        { headers: authHeader() }
      );
      if (!resp.ok) throw new Error(resp.status);
      data = await resp.json();
    } catch (e) {
      console.warn("[map] Could not fetch contacts:", e);
      return;
    }

    const station = data.station || {};
    const contacts = data.contacts || [];
    const sLat = station.lat ?? 39.5;
    const sLon = station.lon ?? -8.0;
    _lastStation = station;

    const world = await loadWorld();

    // Clear and re-draw SVG
    container.innerHTML = "";
    const svg = d3g
      .select(container)
      .append("svg")
      .attr("width", W)
      .attr("height", H)
      .attr("viewBox", `0 0 ${W} ${H}`)
      .style("background", "#0d1117")
      .style("border-radius", "6px");

    const proj = d3g
      .geoAzimuthalEquidistant()
      .rotate([-sLon, -sLat])
      .scale(Math.min(W, H) * 0.42)
      .translate([W / 2, H / 2])
      .clipAngle(180);

    const path = d3g.geoPath().projection(proj);

    // Graticule (grid lines)
    const graticule = d3g.geoGraticule()();
    svg
      .append("path")
      .datum(graticule)
      .attr("d", path)
      .attr("fill", "none")
      .attr("stroke", "#1e3a5f")
      .attr("stroke-width", 0.5);

    // World sphere
    svg
      .append("path")
      .datum({ type: "Sphere" })
      .attr("d", path)
      .attr("fill", "#0d2137")
      .attr("stroke", "#1e3a5f")
      .attr("stroke-width", 0.8);

    // Country outlines
    if (world) {
      const countries = topo.feature(world, world.objects.countries);
      svg
        .append("g")
        .selectAll("path")
        .data(countries.features)
        .join("path")
        .attr("d", path)
        .attr("fill", "#1c3048")
        .attr("stroke", "#2d5278")
        .attr("stroke-width", 0.4);
    }

    // ── Draw arcs (great circle) from station to each contact ────────────────
    const arcG = svg.append("g").attr("class", "arcs");

    contacts.forEach((c) => {
      const dLat = c.lat;
      const dLon = c.lon;
      if (dLat == null || dLon == null) return;
      const pts = greatCircleArc(proj, sLon, sLat, dLon, dLat);
      if (pts.length < 2) return;
      arcG
        .append("path")
        .attr("d", pointsToPath(pts))
        .attr("fill", "none")
        .attr("stroke", bandColor(c.band))
        .attr("stroke-width", 1.2)
        .attr("stroke-opacity", 0.55);
    });

    // ── Contact dots ─────────────────────────────────────────────────────────
    const dotG = svg.append("g").attr("class", "dots");

    // Tooltip element (positioned absolutely in the container parent)
    let tip = document.getElementById("mapTooltip");
    if (!tip) {
      tip = document.createElement("div");
      tip.id = "mapTooltip";
      tip.style.cssText =
        "position:absolute;background:#1e293b;color:#e2e8f0;padding:5px 9px;border-radius:5px;"
        + "font-size:11px;pointer-events:none;display:none;z-index:99;white-space:nowrap;"
        + "border:1px solid #334155;";
      document.body.appendChild(tip);
    }

    contacts.forEach((c) => {
      const dLat = c.lat;
      const dLon = c.lon;
      if (dLat == null || dLon == null) return;
      const projected = proj([dLon, dLat]);
      if (!projected) return;
      const [px, py] = projected;
      if (px < 0 || px > W || py < 0 || py > H) return;

      const snrStr = c.snr_db != null ? `${c.snr_db > 0 ? "+" : ""}${c.snr_db} dB` : "—";
      const distStr = c.distance_km != null ? `${c.distance_km.toLocaleString()} km` : "—";

      dotG
        .append("circle")
        .attr("cx", px)
        .attr("cy", py)
        .attr("r", 3.5)
        .attr("fill", bandColor(c.band))
        .attr("stroke", "#fff")
        .attr("stroke-width", 0.6)
        .attr("opacity", 0.85)
        .style("cursor", "pointer")
        .on("mousemove", function (event) {
          tip.innerHTML =
            `<strong>${c.callsign}</strong> · ${c.country}<br>`
            + `${c.band} · ${c.mode} · SNR ${snrStr} · ${distStr}`;
          tip.style.display = "block";
          tip.style.left = event.pageX + 12 + "px";
          tip.style.top = event.pageY - 28 + "px";
        })
        .on("mouseleave", function () {
          tip.style.display = "none";
        });
    });

    // ── Station marker (home) ─────────────────────────────────────────────────
    const home = proj([sLon, sLat]);
    if (home) {
      svg
        .append("circle")
        .attr("cx", home[0])
        .attr("cy", home[1])
        .attr("r", 5)
        .attr("fill", "#facc15")
        .attr("stroke", "#fff")
        .attr("stroke-width", 1.2);
      svg
        .append("text")
        .attr("x", home[0] + 8)
        .attr("y", home[1] + 4)
        .attr("fill", "#facc15")
        .attr("font-size", "10px")
        .attr("font-family", "monospace")
        .text(station.callsign || "QTH");
    }

    // ── Legend (bands present) ────────────────────────────────────────────────
    const bandsPresent = [...new Set(contacts.map((c) => c.band).filter(Boolean))].sort();
    const legG = svg.append("g").attr("class", "legend");
    bandsPresent.slice(0, 6).forEach((band, i) => {
      const x = 8;
      const y = H - 12 - i * 14;
      legG.append("rect").attr("x", x).attr("y", y - 7).attr("width", 12).attr("height", 8).attr("fill", bandColor(band)).attr("rx", 2);
      legG.append("text").attr("x", x + 16).attr("y", y).attr("fill", "#cbd5e1").attr("font-size", "9px").attr("font-family", "monospace").text(band);
    });

    // ── Count label ───────────────────────────────────────────────────────────
    svg
      .append("text")
      .attr("x", W - 6)
      .attr("y", H - 6)
      .attr("text-anchor", "end")
      .attr("fill", "#64748b")
      .attr("font-size", "9px")
      .attr("font-family", "monospace")
      .text(`${contacts.length} contacts · ${windowMinutes >= 1440 ? Math.round(windowMinutes/1440)+"d" : windowMinutes+"min"}`);
  }

  // ── Public API ────────────────────────────────────────────────────────────
  function init(containerId, windowMinutes) {
    windowMinutes = windowMinutes || 60;
    render(containerId, windowMinutes);
    if (_refreshTimer) clearInterval(_refreshTimer);
    _refreshTimer = setInterval(() => render(containerId, windowMinutes), 60000);
  }

  function refresh(containerId, windowMinutes) {
    render(containerId || "propagationMap", windowMinutes || 60);
  }

  window.PropMap = { init, refresh };

  // Auto-init when DOM is ready
  document.addEventListener("DOMContentLoaded", function () {
    const el = document.getElementById("propagationMap");
    if (el) init("propagationMap", 60);
  });
})();
