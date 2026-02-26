// © 2026 Octávio Filipe Gonçalves – CT7BFV
// License: GNU AGPL-3.0
// Propagation World Map — requires d3.min.js + topojson.min.js loaded first.
// Features: D3 zoom/pan, zoom buttons (+/−/reset), fullscreen modal.

(function () {
  "use strict";

  // ── Band colour palette ────────────────────────────────────────────────────
  const BAND_COLORS = {
    "160m": "#cc2200", "80m": "#e0507a", "40m": "#f5a623",
    "20m": "#3b82f6",  "17m": "#22c55e", "15m": "#a855f7",
    "12m": "#06b6d4",  "10m": "#ef4444", "6m":  "#f97316",
    "2m":  "#84cc16",  "70cm": "#ec4899",
  };
  const DEFAULT_COLOR = "#9ca3af";
  const bandColor = (b) => BAND_COLORS[(b || "").toLowerCase()] || DEFAULT_COLOR;

  // ── Auth ──────────────────────────────────────────────────────────────────
  const authHeader = () => {
    const u = localStorage.getItem("authUser");
    const p = localStorage.getItem("authPass");
    return u && p ? { Authorization: "Basic " + btoa(u + ":" + p) } : {};
  };

  // ── State ─────────────────────────────────────────────────────────────────
  let _worldData   = null;
  let _refreshTimer = null;
  let _lastData    = null;  // cached API response for modal reuse

  // ── World atlas (lazy loaded once) ───────────────────────────────────────
  async function loadWorld() {
    if (_worldData) return _worldData;
    try {
      const r = await fetch("/lib/countries-110m.json");
      _worldData = await r.json();
    } catch (e) { _worldData = null; }
    return _worldData;
  }

  // ── Great-circle arc ──────────────────────────────────────────────────────
  function gcArc(proj, lon1, lat1, lon2, lat2) {
    const interp = d3.geoInterpolate([lon1, lat1], [lon2, lat2]);
    return d3.range(0, 1.01, 0.025).map((t) => proj(interp(t))).filter(Boolean);
  }
  const pts2path = (pts) =>
    pts.length < 2 ? "" : "M" + pts[0] + pts.slice(1).map((p) => "L" + p).join("");

  // ── Shared tooltip ────────────────────────────────────────────────────────
  let _tip = null;
  function getTooltip() {
    if (_tip) return _tip;
    _tip = document.createElement("div");
    _tip.id = "mapTooltip";
    _tip.style.cssText =
      "position:fixed;background:#1e293b;color:#e2e8f0;padding:5px 9px;"
      + "border-radius:5px;font-size:11px;pointer-events:none;display:none;"
      + "z-index:9999;white-space:nowrap;border:1px solid #334155;";
    document.body.appendChild(_tip);
    return _tip;
  }

  // ── Core draw ─────────────────────────────────────────────────────────────
  // Returns {svg (d3 selection), zoom (d3 zoom behaviour)}
  function drawMap(container, W, H, data, world) {
    const station  = data.station  || {};
    const contacts = data.contacts || [];
    const sLat = station.lat ?? 39.5;
    const sLon = station.lon ?? -8.0;

    container.innerHTML = "";

    const svg = d3.select(container)
      .append("svg")
      .attr("width", W).attr("height", H)
      .attr("viewBox", `0 0 ${W} ${H}`)
      .style("background", "#0d1117").style("border-radius", "6px")
      .style("cursor", "grab").style("display", "block");

    const g = svg.append("g").attr("class", "map-root");

    const proj = d3.geoAzimuthalEquidistant()
      .rotate([-sLon, -sLat])
      .scale(Math.min(W, H) * 0.42)
      .translate([W / 2, H / 2])
      .clipAngle(180);
    const path = d3.geoPath().projection(proj);

    g.append("path").datum({ type: "Sphere" })
      .attr("d", path).attr("fill", "#0d2137").attr("stroke", "#1e3a5f").attr("stroke-width", 0.8);
    g.append("path").datum(d3.geoGraticule()())
      .attr("d", path).attr("fill", "none").attr("stroke", "#1e3a5f").attr("stroke-width", 0.4);
    if (world) {
      g.append("g").selectAll("path")
        .data(topojson.feature(world, world.objects.countries).features)
        .join("path").attr("d", path)
        .attr("fill", "#1c3048").attr("stroke", "#2d5278").attr("stroke-width", 0.4);
    }

    // Arcs
    const arcG = g.append("g").attr("class", "arcs");
    contacts.forEach((c) => {
      if (c.lat == null || c.lon == null) return;
      const pts = gcArc(proj, sLon, sLat, c.lon, c.lat);
      if (pts.length < 2) return;
      arcG.append("path").attr("d", pts2path(pts))
        .attr("fill", "none").attr("stroke", bandColor(c.band))
        .attr("stroke-width", 1.4).attr("stroke-opacity", 0.5);
    });

    // Dots
    const tip = getTooltip();
    const dotG = g.append("g").attr("class", "dots");
    contacts.forEach((c) => {
      if (c.lat == null || c.lon == null) return;
      const pp = proj([c.lon, c.lat]);
      if (!pp) return;
      const snrStr  = c.snr_db      != null ? `${c.snr_db > 0 ? "+" : ""}${c.snr_db} dB` : "—";
      const distStr = c.distance_km != null ? `${c.distance_km.toLocaleString()} km` : "—";
      dotG.append("circle")
        .attr("cx", pp[0]).attr("cy", pp[1]).attr("r", 4)
        .attr("fill", bandColor(c.band)).attr("stroke", "#fff").attr("stroke-width", 0.6)
        .attr("opacity", 0.9).style("cursor", "pointer")
        .on("mousemove", (evt) => {
          tip.innerHTML = `<strong>${c.callsign}</strong> · ${c.country}<br>`
            + `${c.band} · ${c.mode} · SNR ${snrStr} · ${distStr}`;
          tip.style.display = "block";
          tip.style.left = evt.clientX + 14 + "px";
          tip.style.top  = evt.clientY - 34 + "px";
        })
        .on("mouseleave", () => { tip.style.display = "none"; });
    });

    // Home marker
    const home = proj([sLon, sLat]);
    if (home) {
      g.append("circle").attr("cx", home[0]).attr("cy", home[1]).attr("r", 6)
        .attr("fill", "#facc15").attr("stroke", "#fff").attr("stroke-width", 1.5);
      g.append("text").attr("x", home[0] + 9).attr("y", home[1] + 5)
        .attr("fill", "#facc15").attr("font-size", "11px").attr("font-family", "monospace")
        .text(station.callsign || "QTH");
    }

    // Legend (fixed — outside the pannable group)
    const bandsPresent = [...new Set(contacts.map((c) => c.band).filter(Boolean))].sort();
    const legG = svg.append("g").attr("class", "legend").attr("pointer-events", "none");
    bandsPresent.slice(0, 8).forEach((band, i) => {
      const x = 8, y = H - 12 - i * 15;
      legG.append("rect").attr("x", x).attr("y", y - 8).attr("width", 12).attr("height", 9)
        .attr("fill", bandColor(band)).attr("rx", 2);
      legG.append("text").attr("x", x + 16).attr("y", y)
        .attr("fill", "#cbd5e1").attr("font-size", "10px").attr("font-family", "monospace").text(band);
    });

    const win = data.window_minutes || 60;
    svg.append("text").attr("x", W - 6).attr("y", H - 6).attr("text-anchor", "end")
      .attr("fill", "#64748b").attr("font-size", "9px").attr("font-family", "monospace")
      .attr("pointer-events", "none")
      .text(`${contacts.length} contacts · ${win >= 1440 ? Math.round(win / 1440) + "d" : win + "min"}`);

    // ── D3 zoom + pan ────────────────────────────────────────────────────────
    const zoom = d3.zoom()
      .scaleExtent([0.35, 24])
      .on("zoom", (event) => {
        g.attr("transform", event.transform);
        svg.style("cursor", event.transform.k > 1 ? "move" : "grab");
      });

    svg.call(zoom);
    svg.on("dblclick.zoom", null);  // disable default dblclick
    svg.on("dblclick", () =>
      svg.transition().duration(420).call(zoom.transform, d3.zoomIdentity)
    );

    return { svg, zoom };
  }

  // ── Overlay control buttons ───────────────────────────────────────────────
  function addControls(wrapper, svgSel, zoom, showFullscreen) {
    const btnCss =
      "width:30px;height:30px;border:none;border-radius:5px;"
      + "background:rgba(30,41,59,0.88);color:#e2e8f0;font-size:17px;cursor:pointer;"
      + "display:flex;align-items:center;justify-content:center;margin-bottom:4px;"
      + "border:1px solid #334155;";

    const bar = document.createElement("div");
    bar.style.cssText = "position:absolute;top:8px;right:8px;display:flex;flex-direction:column;z-index:10;";

    const btn = (html, title, fn) => {
      const b = document.createElement("button");
      b.title = title; b.innerHTML = html; b.style.cssText = btnCss;
      b.addEventListener("click", (e) => { e.stopPropagation(); fn(); });
      return b;
    };

    bar.appendChild(btn("+",  "Zoom in",    () => svgSel.transition().duration(240).call(zoom.scaleBy, 1.6)));
    bar.appendChild(btn("−",  "Zoom out",   () => svgSel.transition().duration(240).call(zoom.scaleBy, 1 / 1.6)));
    bar.appendChild(btn("⌂",  "Reset view", () => svgSel.transition().duration(380).call(zoom.transform, d3.zoomIdentity)));

    if (showFullscreen) {
      bar.appendChild(btn("⛶", "Open fullscreen", () => {
        const el = document.getElementById("mapFullscreenModal");
        if (el && window.bootstrap) bootstrap.Modal.getOrCreateInstance(el).show();
      }));
    }

    wrapper.style.position = "relative";
    wrapper.appendChild(bar);
  }

  // ── Fetch ─────────────────────────────────────────────────────────────────
  async function fetchData(windowMinutes) {
    const r = await fetch(
      `/api/map/contacts?window_minutes=${windowMinutes}&limit=500`,
      { headers: authHeader() }
    );
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }

  // ── Render into a container ────────────────────────────────────────────────
  async function render(containerId, windowMinutes, isModal) {
    if (!window.d3 || !window.topojson) return;
    const container = document.getElementById(containerId);
    if (!container) return;

    const W = container.clientWidth  || (isModal ? window.innerWidth  - 48 : 420);
    const H = isModal ? Math.max(window.innerHeight - 150, 300) : Math.min(W * 0.6, 320);

    let data;
    try {
      data = await fetchData(windowMinutes);
      if (!isModal) _lastData = data;
    } catch (e) { console.warn("[map] fetch:", e); return; }

    const world = await loadWorld();
    const { svg, zoom } = drawMap(container, W, H, data, world);
    addControls(container, svg, zoom, !isModal);
  }

  // ── Public API ─────────────────────────────────────────────────────────────
  const PropMap = {
    init(containerId, windowMinutes) {
      windowMinutes = windowMinutes || 60;
      render(containerId, windowMinutes, false);
      if (_refreshTimer) clearInterval(_refreshTimer);
      _refreshTimer = setInterval(() => render(containerId, windowMinutes, false), 60000);
    },

    refresh(containerId, windowMinutes) {
      render(containerId || "propagationMap", windowMinutes || 60, false);
    },

    async renderModal() {
      const c = document.getElementById("propagationMapModal");
      if (!c) return;
      const W = c.clientWidth  || window.innerWidth  - 48;
      const H = Math.max(window.innerHeight - 150, 300);
      const world = await loadWorld();

      // Instant render with cached data
      if (_lastData) {
        const { svg, zoom } = drawMap(c, W, H, _lastData, world);
        addControls(c, svg, zoom, false);
      }

      // Then refresh in background
      try {
        const fresh = await fetchData(60);
        _lastData = fresh;
        const { svg, zoom } = drawMap(c, W, H, fresh, world);
        addControls(c, svg, zoom, false);
      } catch (_) {}
    },
  };

  window.PropMap = PropMap;

  document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("propagationMap")) PropMap.init("propagationMap", 60);

    const modalEl = document.getElementById("mapFullscreenModal");
    if (modalEl) {
      modalEl.addEventListener("shown.bs.modal", () => PropMap.renderModal());
      modalEl.addEventListener("hide.bs.modal", () => {
        const tip = document.getElementById("mapTooltip");
        if (tip) tip.style.display = "none";
      });
    }
  });
})();

