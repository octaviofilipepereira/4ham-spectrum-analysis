// © 2026 Octávio Filipe Gonçalves – CT7BFV
// License: GNU AGPL-3.0
// Propagation 3D Globe — requires d3.min.js + topojson.min.js loaded first.
// Features: orthographic projection, drag-to-rotate, scroll/button zoom, fullscreen modal.

(function () {
  "use strict";

  // ── Band colour palette ────────────────────────────────────────────────────
  const BAND_COLORS = {
    "160m": "#ff0000", "80m": "#ff1493", "40m": "#ffa500",
    "60m": "#facc15",
    "20m": "#00bfff",  "17m": "#00ff00", "15m": "#9400ff",
    "12m": "#00ffff",  "10m": "#ff4500", "6m":  "#ffff00",
    "2m":  "#7fff00",  "70cm": "#ff69b4",
  };
  const DEFAULT_COLOR = "#9ca3af";
  const bandColor = (b) => BAND_COLORS[(b || "").toLowerCase()] || DEFAULT_COLOR;
  const MAP_BAND_FILTER_STORAGE_KEY = "4ham_map_band_filter";
  const MAP_ARCS_TOGGLE_STORAGE_KEY = "4ham_map_arcs_toggle";
  const MAP_ALLOWED_BAND_FILTERS = new Set([
    "all", "160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m", "2m", "70cm",
  ]);

  // ── Auth ─────────────────────────────────────────────────────────────────
  const authHeader = () => {
    const u = localStorage.getItem("authUser");
    const p = localStorage.getItem("authPass");
    return u && p ? { Authorization: "Basic " + btoa(u + ":" + p) } : {};
  };

  const getPropagationViewMode = () => {
    if (typeof window._getPropagationViewMode === "function") {
      return String(window._getPropagationViewMode() || "GENERIC").trim().toUpperCase();
    }
    return "GENERIC";
  };

  const isBeaconMapData = (data) => String(data?.kind || "").trim().toLowerCase() === "beacon";

  function formatWindowLabel(windowMinutes) {
    return windowMinutes >= 1440 ? `${Math.round(windowMinutes / 1440)}d` : `${windowMinutes}min`;
  }

  function formatUtcTimestamp(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return String(value || "-");
    }
    return date.toISOString().replace(".000Z", " UTC").replace("T", " ");
  }

  function renderTooltipHtml(contact, isBeaconMap) {
    const snrValue = Number(contact?.snr_db);
    const snrLabel = Number.isFinite(snrValue) ? `${snrValue.toFixed(1)} dB` : "-";
    const distanceValue = Number(contact?.distance_km);
    const distanceLabel = Number.isFinite(distanceValue) ? `${distanceValue.toLocaleString()} km` : "-";

    if (isBeaconMap) {
      const dashValue = Number(contact?.dash_levels_detected);
      const dashLabel = Number.isFinite(dashValue) ? `${dashValue}/4` : "-";
      const whenLabel = formatUtcTimestamp(contact?.last_detection_utc || contact?.timestamp);
      return `<strong>${contact.callsign}</strong> · ${contact.location}<br>`
        + `${contact.band} · ${contact.state} · 100 W ${snrLabel} · dashes ${dashLabel}<br>`
        + `Last detection ${whenLabel} · ${distanceLabel}`;
    }

    return `<strong>${contact.callsign}</strong> · ${contact.country}<br>`
      + `${contact.band} · ${contact.mode} · SNR ${snrLabel} · ${distanceLabel}`;
  }

  // ── State ────────────────────────────────────────────────────────────────
  let _worldData    = null;
  let _refreshTimer = null;
  let _lastData     = null;
  let _inlineContainerId = "propagationMap";
  const _modalContainerId = "propagationMapModal";
  let _beaconRefreshTimer = null;
  const _viewStateByContainer = new Map();

  function getViewState(containerId) {
    if (!_viewStateByContainer.has(containerId)) {
      _viewStateByContainer.set(containerId, {
        rotation: null,
        zoomScale: 1,
        pointerInside: false,
        interactionActive: false,
        interactionTimer: null,
        pendingPayload: null,
      });
    }
    return _viewStateByContainer.get(containerId);
  }

  function isInteractionBlocked(viewState) {
    return Boolean(viewState?.pointerInside || viewState?.interactionActive);
  }

  function syncCameraState(sourceContainerId, targetContainerId) {
    const source = _viewStateByContainer.get(sourceContainerId);
    if (!source) {
      return;
    }
    const target = getViewState(targetContainerId);
    if (Array.isArray(source.rotation) && source.rotation.length === 3) {
      target.rotation = source.rotation.slice();
    }
    if (Number.isFinite(Number(source.zoomScale)) && Number(source.zoomScale) > 0) {
      target.zoomScale = Number(source.zoomScale);
    }
  }

  function queuePendingPayload(containerId, payload) {
    const viewState = getViewState(containerId);
    viewState.pendingPayload = payload;
  }

  function scheduleInteractionRelease(containerId) {
    const viewState = getViewState(containerId);
    clearTimeout(viewState.interactionTimer);
    viewState.interactionActive = true;
    viewState.interactionTimer = setTimeout(() => {
      viewState.interactionActive = false;
      flushPendingRender(containerId);
    }, 350);
  }

  async function flushPendingRender(containerId) {
    const viewState = getViewState(containerId);
    if (isInteractionBlocked(viewState) || !viewState.pendingPayload) {
      return;
    }
    const payload = viewState.pendingPayload;
    viewState.pendingPayload = null;
    if (!payload.data) {
      await render(payload.containerId, payload.windowMinutes, payload.isModal);
      return;
    }
    await drawResolvedData(payload.containerId, payload.windowMinutes, payload.isModal, payload.data);
  }

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
    const allContacts = Array.isArray(data.contacts) ? data.contacts : [];
    const selectedBand = getBandFilter();
    const showArcs = getArcsEnabled();
    const contacts = selectedBand === "all"
      ? allContacts
      : allContacts.filter((contact) => String(contact?.band || "").trim().toLowerCase() === selectedBand);
    const isBeaconMap = isBeaconMapData(data);
    const sLat = station.lat ?? 39.5;
    const sLon = station.lon ?? -8.0;
    const viewState = getViewState(container.id);

    container.innerHTML = "";

    // Per-container gradient id so inline + modal can coexist
    const gradId = "oceanGrad_" + container.id;
    const baseScale = Math.min(W, H) * 0.44;
    let kScale = Math.max(0.25, Math.min(12, Number(viewState.zoomScale) || 1));
    const initialRotation = Array.isArray(viewState.rotation) && viewState.rotation.length === 3
      ? viewState.rotation
      : [-sLon, -sLat, 0];

    const proj = d3.geoOrthographic()
      .rotate(initialRotation)
      .scale(baseScale * kScale)
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
      const x = 5, y = H - 14 - i * 20;
      legG.append("rect").attr("x", x).attr("y", y - 11).attr("width", 14).attr("height", 12)
        .attr("fill", bandColor(band)).attr("rx", 2);
      legG.append("text").attr("x", x + 18).attr("y", y)
        .attr("fill", "#cbd5e1").attr("font-size", "15px").attr("font-family", "monospace").text(band);
    });
    const win = data.window_minutes || 60;
    const totalCount = allContacts.length;
    const shownCount = contacts.length;
    const mapUnit = isBeaconMap ? "detections" : "contacts";
    const countLabelText = selectedBand === "all"
      ? `${shownCount} ${mapUnit} · ${formatWindowLabel(win)}`
      : `${shownCount}/${totalCount} ${mapUnit} · ${selectedBand.toUpperCase()} · ${formatWindowLabel(win)}`;
    const countLabel = svg.append("text")
      .attr("x", W - 6).attr("y", H - 6).attr("text-anchor", "end")
      .attr("fill", "#64748b").attr("font-size", "14px").attr("font-family", "monospace")
      .attr("pointer-events", "none")
      .text(countLabelText);

    const tip = getTooltip();

    function persistViewState() {
      viewState.rotation = proj.rotate().slice();
      viewState.zoomScale = Math.max(0.25, Math.min(12, proj.scale() / baseScale));
    }

    // ── redraw: called on every rotate/zoom interaction ───────────────────
    function redraw() {
      spherePath.attr("d", path);
      gratPath.attr("d", path);
      if (countryPaths) countryPaths.attr("d", path);

      // Great-circle arcs as GeoJSON LineString — D3+orthographic clips automatically
      arcG.selectAll("path").remove();
      if (showArcs) {
        contacts.forEach((c) => {
          if (c.lat == null || c.lon == null) return;
          arcG.append("path")
            .datum({ type: "LineString", coordinates: [[sLon, sLat], [c.lon, c.lat]] })
            .attr("d", path)
            .attr("fill", "none")
            .attr("stroke", bandColor(c.band))
            .attr("stroke-width", isBeaconMap ? 2.2 : 1.8)
            .attr("stroke-opacity", isBeaconMap ? 0.92 : 0.85);
        });
      }

      // Dots — only on visible hemisphere (geoDistance < 90°)
      dotG.selectAll("*").remove();
      const center = proj.invert([W / 2, H / 2]);
      contacts.forEach((c) => {
        if (c.lat == null || c.lon == null) return;
        if (d3.geoDistance([c.lon, c.lat], center) >= Math.PI / 2) return;
        const pp = proj([c.lon, c.lat]);
        if (!pp) return;
        dotG.append("circle")
          .attr("cx", pp[0]).attr("cy", pp[1]).attr("r", isBeaconMap ? 5.2 : 4.5)
          .attr("fill", bandColor(c.band)).attr("stroke", "#fff").attr("stroke-width", 0.7)
          .attr("opacity", 0.92).style("cursor", "pointer")
          .on("mousemove", (evt) => {
            tip.innerHTML = renderTooltipHtml(c, isBeaconMap);
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
      persistViewState();
    }

    redraw();

    svg
      .on("mouseenter", () => {
        viewState.pointerInside = true;
      })
      .on("mouseleave", async () => {
        viewState.pointerInside = false;
        tip.style.display = "none";
        await flushPendingRender(container.id);
      });

    // ── Drag = rotate globe ───────────────────────────────────────────────
    svg.call(
      d3.drag()
        .on("start", () => {
          viewState.interactionActive = true;
          svg.style("cursor", "grabbing");
        })
        .on("drag", (event) => {
          const [rx, ry, rz] = proj.rotate();
          proj.rotate([rx + event.dx * 0.25, ry - event.dy * 0.25, rz]);
          redraw();
        })
        .on("end", async () => {
          viewState.interactionActive = false;
          svg.style("cursor", "grab");
          await flushPendingRender(container.id);
        })
    );

    // ── Ctrl/⌘ + scroll wheel = zoom; plain wheel = page scroll ──────────
    svg.node().addEventListener("wheel", (event) => {
      if (!(event.ctrlKey || event.metaKey)) return;  // let page scroll
      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
      kScale = Math.max(0.25, Math.min(12, kScale * factor));
      proj.scale(baseScale * kScale);
      redraw();
      scheduleInteractionRelease(container.id);
    }, { passive: false });

    // ── Double-click = reset view ─────────────────────────────────────────
    svg.on("dblclick", () => {
      proj.rotate([-sLon, -sLat]).scale(baseScale);
      kScale = 1;
      redraw();
      scheduleInteractionRelease(container.id);
    });

    // ── Programmatic controls ─────────────────────────────────────────────
    const controls = {
      zoomIn:  () => { kScale = Math.min(kScale * 1.6, 12);   proj.scale(baseScale * kScale); redraw(); scheduleInteractionRelease(container.id); },
      zoomOut: () => { kScale = Math.max(kScale / 1.6, 0.25); proj.scale(baseScale * kScale); redraw(); scheduleInteractionRelease(container.id); },
      reset:   () => { proj.rotate([-sLon, -sLat]).scale(baseScale); kScale = 1; redraw(); scheduleInteractionRelease(container.id); },
    };

    return { controls };
  }

  // ── Overlay button bar ────────────────────────────────────────────────────
  function addControls(wrapper, controls, showFullscreen) {
    const btnCss =
      "width:40px;height:40px;border:none;border-radius:6px;"
      + "background:rgba(20,30,50,0.92);color:#e2e8f0;font-size:20px;cursor:pointer;"
      + "display:flex;align-items:center;justify-content:center;margin-bottom:5px;"
      + "border:1px solid #2a4a6a;font-weight:600;";

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
    bar.appendChild(btn("↻",  "Reset view", controls.reset));
    if (showFullscreen) {
      bar.appendChild(btn("⤢", "Open fullscreen", () => {
        const el = document.getElementById("mapFullscreenModal");
        if (el && window.bootstrap) bootstrap.Modal.getOrCreateInstance(el).show();
      }));
    }

    wrapper.style.position = "relative";
    wrapper.appendChild(bar);
  }

  // ── Fetch ────────────────────────────────────────────────────────────────
  async function fetchData(windowMinutes) {
    const endpoint = getPropagationViewMode() === "BEACON"
      ? "/api/beacons/map/contacts"
      : "/api/map/contacts";
    const r = await fetch(
      `${endpoint}?window_minutes=${windowMinutes}&limit=2000`,
      { headers: authHeader() }
    );
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }

  // ── Render into a container ───────────────────────────────────────────────
  async function drawResolvedData(containerId, windowMinutes, isModal, data) {
    if (!window.d3 || !window.topojson) return;
    if (!data) return;
    const container = document.getElementById(containerId);
    if (!container) return;
    const viewState = getViewState(containerId);
    if (isInteractionBlocked(viewState)) {
      queuePendingPayload(containerId, { containerId, windowMinutes, isModal, data });
      return;
    }

    const rect = container.getBoundingClientRect();
    const W = rect.width  || (isModal ? window.innerWidth  - 48 : 420);
    const H = isModal
      ? Math.max(window.innerHeight - 150, 300)
      : (rect.height > 80 ? rect.height : Math.min(W * 1.1, 680));

    const world = await loadWorld();
    if (isInteractionBlocked(viewState)) {
      queuePendingPayload(containerId, { containerId, windowMinutes, isModal, data });
      return;
    }

    const { controls } = drawGlobe(container, W, H, data, world);
    addControls(container, controls, !isModal);
  }

  async function render(containerId, windowMinutes, isModal) {
    if (!window.d3 || !window.topojson) return;
    const viewState = getViewState(containerId);
    if (isInteractionBlocked(viewState)) {
      queuePendingPayload(containerId, { containerId, windowMinutes, isModal, data: null });
      return;
    }

    let data;
    try {
      data = await fetchData(windowMinutes);
      if (!isModal) _lastData = data;
    } catch {
      console.warn("[map] fetch failed");
      return;
    }

    await drawResolvedData(containerId, windowMinutes, isModal, data);
  }

  // ── Read selected window from UI dropdown ─────────────────────────────────
  function getWindowMinutes() {
    const sel = document.getElementById("mapWindowSelect");
    return sel ? parseInt(sel.value, 10) || 60 : 60;
  }

  function getBandFilter() {
    const sel = document.getElementById("mapBandFilter");
    const raw = sel ? String(sel.value || "all").trim().toLowerCase() : "all";
    return MAP_ALLOWED_BAND_FILTERS.has(raw) ? raw : "all";
  }

  function getArcsEnabled() {
    const toggle = document.getElementById("mapArcsToggle");
    return toggle ? Boolean(toggle.checked) : true;
  }

  function restoreMapUiPreferences() {
    const bandSel = document.getElementById("mapBandFilter");
    if (bandSel) {
      let savedBand = "all";
      try {
        savedBand = String(localStorage.getItem(MAP_BAND_FILTER_STORAGE_KEY) || "all").trim().toLowerCase();
      } catch (_) {}
      bandSel.value = MAP_ALLOWED_BAND_FILTERS.has(savedBand) ? savedBand : "all";
    }

    const arcsToggle = document.getElementById("mapArcsToggle");
    if (arcsToggle) {
      let savedArcs = "1";
      try {
        savedArcs = String(localStorage.getItem(MAP_ARCS_TOGGLE_STORAGE_KEY) || "1").trim();
      } catch (_) {}
      arcsToggle.checked = savedArcs !== "0";
    }
  }

  function persistMapBandFilterPreference() {
    try {
      localStorage.setItem(MAP_BAND_FILTER_STORAGE_KEY, getBandFilter());
    } catch (_) {}
  }

  function persistMapArcsPreference() {
    try {
      localStorage.setItem(MAP_ARCS_TOGGLE_STORAGE_KEY, getArcsEnabled() ? "1" : "0");
    } catch (_) {}
  }

  // ── Public API ────────────────────────────────────────────────────────────
  const PropMap = {
    init(containerId, windowMinutes) {
      windowMinutes = windowMinutes || getWindowMinutes();
      _inlineContainerId = containerId || _inlineContainerId;
      render(containerId, windowMinutes, false);
      if (_refreshTimer) clearInterval(_refreshTimer);
      _refreshTimer = setInterval(() => render(containerId, getWindowMinutes(), false), 60000);
    },

    refresh(containerId, windowMinutes) {
      render(containerId || "propagationMap", windowMinutes || getWindowMinutes(), false);
    },

    async renderModal() {
      const c = document.getElementById(_modalContainerId);
      if (!c) return;
      const win = getWindowMinutes();

      // Keep fullscreen view aligned with the latest inline camera state.
      syncCameraState(_inlineContainerId, _modalContainerId);

      if (_lastData) {
        await drawResolvedData(c.id, win, true, _lastData);
      }
      try {
        const fresh = await fetchData(win);
        _lastData = fresh;
        await drawResolvedData(c.id, win, true, fresh);
      } catch {
        // Silently ignore fetch errors in modal
      }
    },
  };

  window.PropMap = PropMap;

  window.addEventListener("beacon-observation", () => {
    if (getPropagationViewMode() !== "BEACON") {
      return;
    }
    clearTimeout(_beaconRefreshTimer);
    _beaconRefreshTimer = setTimeout(() => {
      PropMap.refresh(_inlineContainerId, getWindowMinutes());
      const modalEl = document.getElementById("mapFullscreenModal");
      if (modalEl && modalEl.classList.contains("show")) {
        PropMap.renderModal();
      }
    }, 250);
  });

  document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("propagationMap")) {
      restoreMapUiPreferences();

      // Double rAF ensures flex layout AND paint have completed before measuring
      requestAnimationFrame(() => {
        requestAnimationFrame(() => PropMap.init("propagationMap"));
      });

      const refreshInlineAndModal = () => {
        PropMap.refresh("propagationMap");
        const fullscreenModalEl = document.getElementById("mapFullscreenModal");
        if (fullscreenModalEl && fullscreenModalEl.classList.contains("show")) {
          PropMap.renderModal();
        }
      };

      // Re-render immediately when user changes the time window
      const sel = document.getElementById("mapWindowSelect");
      if (sel) {
        sel.addEventListener("change", refreshInlineAndModal);
      }

      // Re-render immediately when user changes the selected band filter
      const bandSel = document.getElementById("mapBandFilter");
      if (bandSel) {
        bandSel.addEventListener("change", () => {
          persistMapBandFilterPreference();
          refreshInlineAndModal();
        });
      }

      // Re-render immediately when user toggles map arcs
      const arcsToggle = document.getElementById("mapArcsToggle");
      if (arcsToggle) {
        arcsToggle.addEventListener("change", () => {
          persistMapArcsPreference();
          refreshInlineAndModal();
        });
      }
    }

    const modalEl = document.getElementById("mapFullscreenModal");
    if (modalEl) {
      modalEl.addEventListener("shown.bs.modal", () => PropMap.renderModal());
      modalEl.addEventListener("hide.bs.modal", () => {
        const tip = document.getElementById("mapTooltip");
        if (tip) tip.style.display = "none";
      });
      modalEl.addEventListener("hidden.bs.modal", async () => {
        syncCameraState(_modalContainerId, _inlineContainerId);
        if (_lastData) {
          await drawResolvedData(_inlineContainerId, getWindowMinutes(), false, _lastData);
        } else {
          PropMap.refresh(_inlineContainerId, getWindowMinutes());
        }
      });
    }
  });
})();

