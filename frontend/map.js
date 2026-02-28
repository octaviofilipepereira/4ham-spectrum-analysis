// © 2026 Octávio Filipe Gonçalves – CT7BFV
// License: GNU AGPL-3.0
// Propagation 3D Globe — requires d3.min.js + topojson.min.js loaded first.
// Features: orthographic projection, drag-to-rotate, scroll/button zoom, fullscreen modal.

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

  // ── Auth ─────────────────────────────────────────────────────────────────
  const authHeader = () => {
    const u = localStorage.getItem("authUser");
    const p = localStorage.getItem("authPass");
    return u && p ? { Authorization: "Basic " + btoa(u + ":" + p) } : {};
  };

  // ── State ────────────────────────────────────────────────────────────────
  let _worldData    = null;
  let _refreshTimer = null;
  let _lastData     = null;

  // ── World atlas ──────────────────────────────────────────────────────────
  async function loadWorld() {
    if (_worldData) return _worldData;
    try { const r = await fetch("/lib/countries-110m.json"); _worldData = await r.json(); }
    catch (e) { _worldData = null; }
    return _worldData;
  }

  // ── Tooltip ──────────────────────────────────────────────────────────────
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

  // ── 3-D Globe ────────────────────────────────────────────────────────────
  // Returns { controls: {zoomIn, zoomOut, reset} }
  function drawGlobe(container, W, H, data, world) {
    const station  = data.station  || {};
    const contacts = data.contacts || [];
    const sLat = station.lat ?? 39.5;
    const sLon = station.lon ?? -8.0;

    container.innerHTML = "";

    // Per-container gradient id so inline + modal can coexist
    const gradId = "oceanGrad_" + container.id;
    const baseScale = Math.min(W, H) * 0.44;
    let kScale = 1;                          // current zoom multiplier

    const proj = d3.geoOrthographic()
      .rotate([-sLon, -sLat])
      .scale(baseScale)
      .translate([W / 2, H / 2])
      .clipAngle(90);                        // only visible hemisphere

    const path = d3.geoPath().projection(proj);
    const graticule = d3.geoGraticule()();

    // ── SVG scaffold ─────────────────────────────────────────────────────
    const svg = d3.select(container).append("svg")
      .attr("width", "100%").attr("height", "100%")
      .attr("viewBox", `0 0 ${W} ${H}`)
      .attr("preserveAspectRatio", "xMidYMid meet")
      .style("background", "#0d1117").style("border-radius", "6px")
      .style("cursor", "grab").style("display", "block");

    // Radial gradient for ocean depth effect
    const defs = svg.append("defs");
    const grad = defs.append("radialGradient")
      .attr("id", gradId)
      .attr("gradientUnits", "userSpaceOnUse")
      .attr("cx", W / 2).attr("cy", H / 2).attr("r", baseScale);
    grad.append("stop").attr("offset", "0%").attr("stop-color", "#0e3266");
    grad.append("stop").attr("offset", "70%").attr("stop-color", "#0a1e3d");
    grad.append("stop").attr("offset", "100%").attr("stop-color", "#050d1a");

    // Atmosphere glow (slightly larger circle behind sphere)
    const atmosphereGlow = svg.append("circle")
      .attr("cx", W / 2).attr("cy", H / 2).attr("r", baseScale + 6)
      .attr("fill", "none")
      .attr("stroke", "#1e4fa0").attr("stroke-width", 8).attr("stroke-opacity", 0.18);

    const spherePath = svg.append("path").datum({ type: "Sphere" })
      .attr("fill", `url(#${gradId})`).attr("stroke", "#1e3a5f").attr("stroke-width", 0.6);
    const gratPath  = svg.append("path").datum(graticule)
      .attr("fill", "none").attr("stroke", "#1a3a5c").attr("stroke-width", 0.3);

    let countryPaths;
    if (world) {
      countryPaths = svg.append("g").selectAll("path")
        .data(topojson.feature(world, world.objects.countries).features)
        .join("path").attr("fill", "#1a3050").attr("stroke", "#2a4f78").attr("stroke-width", 0.4);
    }

    const arcG  = svg.append("g").attr("class", "arcs");
    const dotG  = svg.append("g").attr("class", "dots");
    const homeG = svg.append("g").attr("class", "home");

    // ── Legend (fixed overlay, inside SVG but pointer-events:none) ────────
    const bandsPresent = [...new Set(contacts.map((c) => c.band).filter(Boolean))].sort();
    const legG = svg.append("g").attr("class", "legend").attr("pointer-events", "none");
    bandsPresent.slice(0, 8).forEach((band, i) => {
      const x = 8, y = H - 14 - i * 16;
      legG.append("rect").attr("x", x).attr("y", y - 9).attr("width", 12).attr("height", 10)
        .attr("fill", bandColor(band)).attr("rx", 2);
      legG.append("text").attr("x", x + 16).attr("y", y)
        .attr("fill", "#cbd5e1").attr("font-size", "10px").attr("font-family", "monospace").text(band);
    });
    const win = data.window_minutes || 60;
    const countLabel = svg.append("text")
      .attr("x", W - 6).attr("y", H - 6).attr("text-anchor", "end")
      .attr("fill", "#64748b").attr("font-size", "9px").attr("font-family", "monospace")
      .attr("pointer-events", "none")
      .text(`${contacts.length} contacts · ${win >= 1440 ? Math.round(win / 1440) + "d" : win + "min"}`);

    const tip = getTooltip();

    // ── redraw: called on every rotate/zoom interaction ───────────────────
    function redraw() {
      spherePath.attr("d", path);
      gratPath.attr("d", path);
      if (countryPaths) countryPaths.attr("d", path);

      // Great-circle arcs as GeoJSON LineString — D3+orthographic clips automatically
      arcG.selectAll("path").remove();
      contacts.forEach((c) => {
        if (c.lat == null || c.lon == null) return;
        arcG.append("path")
          .datum({ type: "LineString", coordinates: [[sLon, sLat], [c.lon, c.lat]] })
          .attr("d", path)
          .attr("fill", "none")
          .attr("stroke", bandColor(c.band))
          .attr("stroke-width", 1.3)
          .attr("stroke-opacity", 0.65);
      });

      // Dots — only on visible hemisphere (geoDistance < 90°)
      dotG.selectAll("*").remove();
      const center = proj.invert([W / 2, H / 2]);
      contacts.forEach((c) => {
        if (c.lat == null || c.lon == null) return;
        if (d3.geoDistance([c.lon, c.lat], center) >= Math.PI / 2) return;
        const pp = proj([c.lon, c.lat]);
        if (!pp) return;
        const snrStr  = c.snr_db      != null ? `${c.snr_db > 0 ? "+" : ""}${c.snr_db} dB` : "—";
        const distStr = c.distance_km != null ? `${c.distance_km.toLocaleString()} km` : "—";
        dotG.append("circle")
          .attr("cx", pp[0]).attr("cy", pp[1]).attr("r", 4.5)
          .attr("fill", bandColor(c.band)).attr("stroke", "#fff").attr("stroke-width", 0.7)
          .attr("opacity", 0.92).style("cursor", "pointer")
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
      homeG.selectAll("*").remove();
      if (d3.geoDistance([sLon, sLat], center) < Math.PI / 2) {
        const home = proj([sLon, sLat]);
        if (home) {
          homeG.append("circle").attr("cx", home[0]).attr("cy", home[1]).attr("r", 7)
            .attr("fill", "#facc15").attr("stroke", "#fff").attr("stroke-width", 1.6);
          homeG.append("text").attr("x", home[0] + 10).attr("y", home[1] + 5)
            .attr("fill", "#facc15").attr("font-size", "11px").attr("font-family", "monospace")
            .attr("pointer-events", "none")
            .text(station.callsign || "QTH");
        }
      }

      // Update gradient radius to match current scale
      grad.attr("r", proj.scale());
      atmosphereGlow.attr("r", proj.scale() + 6);
    }

    redraw();

    // ── Drag = rotate globe ───────────────────────────────────────────────
    svg.call(
      d3.drag()
        .on("start", () => svg.style("cursor", "grabbing"))
        .on("drag", (event) => {
          const [rx, ry, rz] = proj.rotate();
          proj.rotate([rx + event.dx * 0.25, ry - event.dy * 0.25, rz]);
          redraw();
        })
        .on("end", () => svg.style("cursor", "grab"))
    );

    // ── Scroll wheel = zoom (scale only) ─────────────────────────────────
    svg.node().addEventListener("wheel", (event) => {
      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
      kScale = Math.max(0.25, Math.min(12, kScale * factor));
      proj.scale(baseScale * kScale);
      redraw();
    }, { passive: false });

    // ── Double-click = reset view ─────────────────────────────────────────
    svg.on("dblclick", () => {
      proj.rotate([-sLon, -sLat]).scale(baseScale);
      kScale = 1;
      redraw();
    });

    // ── Programmatic controls ─────────────────────────────────────────────
    const controls = {
      zoomIn:  () => { kScale = Math.min(kScale * 1.6, 12);   proj.scale(baseScale * kScale); redraw(); },
      zoomOut: () => { kScale = Math.max(kScale / 1.6, 0.25); proj.scale(baseScale * kScale); redraw(); },
      reset:   () => { proj.rotate([-sLon, -sLat]).scale(baseScale); kScale = 1; redraw(); },
    };

    return { controls };
  }

  // ── Overlay button bar ────────────────────────────────────────────────────
  function addControls(wrapper, controls, showFullscreen) {
    const btnCss =
      "width:30px;height:30px;border:none;border-radius:5px;"
      + "background:rgba(20,30,50,0.88);color:#e2e8f0;font-size:17px;cursor:pointer;"
      + "display:flex;align-items:center;justify-content:center;margin-bottom:4px;"
      + "border:1px solid #2a4a6a;";

    const bar = document.createElement("div");
    bar.style.cssText =
      "position:absolute;top:8px;right:8px;display:flex;flex-direction:column;z-index:10;";

    const btn = (html, title, fn) => {
      const b = document.createElement("button");
      b.title = title; b.innerHTML = html; b.style.cssText = btnCss;
      b.addEventListener("click", (e) => { e.stopPropagation(); fn(); });
      return b;
    };

    bar.appendChild(btn("+",  "Zoom in",    controls.zoomIn));
    bar.appendChild(btn("−",  "Zoom out",   controls.zoomOut));
    bar.appendChild(btn("⌂",  "Reset view", controls.reset));
    if (showFullscreen) {
      bar.appendChild(btn("⛶", "Open fullscreen", () => {
        const el = document.getElementById("mapFullscreenModal");
        if (el && window.bootstrap) bootstrap.Modal.getOrCreateInstance(el).show();
      }));
    }

    wrapper.style.position = "relative";
    wrapper.appendChild(bar);
  }

  // ── Fetch ────────────────────────────────────────────────────────────────
  async function fetchData(windowMinutes) {
    const r = await fetch(
      `/api/map/contacts?window_minutes=${windowMinutes}&limit=500`,
      { headers: authHeader() }
    );
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }

  // ── Render into a container ───────────────────────────────────────────────
  async function render(containerId, windowMinutes, isModal) {
    if (!window.d3 || !window.topojson) return;
    const container = document.getElementById(containerId);
    if (!container) return;

    const rect = container.getBoundingClientRect();
    const W = rect.width  || (isModal ? window.innerWidth  - 48 : 420);
    const H = isModal
      ? Math.max(window.innerHeight - 150, 300)
      : (rect.height > 80 ? rect.height : Math.min(W * 0.9, 520));

    let data;
    try {
      data = await fetchData(windowMinutes);
      if (!isModal) _lastData = data;
    } catch (e) { console.warn("[map] fetch:", e); return; }

    const world = await loadWorld();
    const { controls } = drawGlobe(container, W, H, data, world);
    addControls(container, controls, !isModal);
  }

  // ── Public API ────────────────────────────────────────────────────────────
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

      if (_lastData) {
        const { controls } = drawGlobe(c, W, H, _lastData, world);
        addControls(c, controls, false);
      }
      try {
        const fresh = await fetchData(60);
        _lastData = fresh;
        const { controls } = drawGlobe(c, W, H, fresh, world);
        addControls(c, controls, false);
      } catch (_) {}
    },
  };

  window.PropMap = PropMap;

  document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("propagationMap")) {
      // rAF ensures flex layout has resolved before we measure clientHeight
      requestAnimationFrame(() => PropMap.init("propagationMap", 60));
    }

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

