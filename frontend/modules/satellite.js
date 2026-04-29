/*
 * frontend/modules/satellite.js
 * © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0
 *
 * Satellite Predict module:
 *  - Init: fetch /api/satellite/status, show/hide nav button
 *  - Lightbox with 4 tabs: Station | Catalog | TLEs | Preferences
 *  - Install card shown when not installed
 *  - TLE badge rendering
 *  - /ws/satellite subscription for tle_status_changed
 */

import { getAuthHeader } from "./utils.js";

const API = "/api/satellite";
let _i18n = {};
let _lang = "en";
let _ws = null;

// ── Initialise ────────────────────────────────────────────────────────────────

export async function initSatellite(lang = "en") {
  _lang = lang;
  await _loadI18n();
  await _refreshStatus();
}

// ── i18n ──────────────────────────────────────────────────────────────────────

async function _loadI18n() {
  try {
    const res = await fetch("/i18n/satellite.json");
    const all = await res.json();
    _i18n = all[_lang] || all["en"] || {};
  } catch {
    _i18n = {};
  }
}

function t(key, vars = {}) {
  let s = _i18n[key] || key;
  for (const [k, v] of Object.entries(vars)) {
    s = s.replace(`{${k}}`, v);
  }
  return s;
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function _api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...getAuthHeader() };
  const res = await fetch(`${API}${path}`, { headers, ...opts });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Status + button visibility ────────────────────────────────────────────────

async function _refreshStatus() {
  try {
    const status = await _api("/status");
    _renderNavButton(status.installed);
    _renderStatusBadge(status);
    if (status.installed) {
      _connectWs();
    }
  } catch {
    _renderNavButton(false);
  }
}

function _renderNavButton(installed) {
  const btn = document.getElementById("satelliteNavBtn");
  if (!btn) return;
  // Button is always visible so the user can open the modal to install.
  // We only annotate state via a CSS class for optional styling.
  btn.classList.remove("d-none");
  btn.classList.toggle("satellite-nav--installed", !!installed);
}

function _renderStatusBadge(status) {
  const el = document.getElementById("satelliteInstallStatus");
  if (!el) return;
  const labels = {
    installed: t("statusInstalled"),
    installing: t("statusInstalling"),
    error: t("statusError"),
    idle: t("statusIdle"),
  };
  el.textContent = labels[status.state] || status.state;
  el.className =
    "badge " +
    ({
      installed: "bg-success",
      installing: "bg-warning text-dark",
      error: "bg-danger",
      idle: "bg-secondary",
    }[status.state] || "bg-secondary");

  // Show/hide install button
  const installBtn = document.getElementById("satelliteInstallBtn");
  if (installBtn) {
    installBtn.disabled = status.state === "installing" || status.installed;
    installBtn.textContent =
      status.state === "installing" ? t("installing") : t("install");
    installBtn.classList.toggle("d-none", !!status.installed);
  }
  const uninstallBtn = document.getElementById("satelliteUninstallBtn");
  if (uninstallBtn) {
    uninstallBtn.classList.toggle("d-none", !status.installed);
  }
  // Hide the entire install card when the module is already installed —
  // the Uninstall button now lives in the modal header next to the badge.
  const installCard = document.getElementById("satelliteInstallCard");
  if (installCard) {
    installCard.classList.toggle("d-none", !!status.installed);
  }
  const promptEl = document.getElementById("satelliteInstallPrompt");
  if (promptEl) {
    promptEl.classList.toggle("d-none", !!status.installed);
  }
}

// ── WebSocket ─────────────────────────────────────────────────────────────────

function _connectWs() {
  if (_ws && _ws.readyState < 2) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const authHdr = getAuthHeader();
  _ws = new WebSocket(`${proto}://${location.host}/ws/satellite`);
  _ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === "tle_status_changed") {
        _renderTleBadge(msg);
      }
    } catch {}
  };
  _ws.onclose = () => {
    // reconnect after 15s
    setTimeout(_connectWs, 15000);
  };
}

// ── TLE badge ─────────────────────────────────────────────────────────────────

function _renderTleBadge(badge) {
  const el = document.getElementById("satelliteTleBadge");
  if (!el) return;
  const colors = { green: "bg-success", yellow: "bg-warning text-dark", red: "bg-danger" };
  el.className = "badge " + (colors[badge.badge] || "bg-secondary");
  if (badge.badge === "green") {
    el.textContent = t("tleBadgeGreen");
  } else if (badge.badge === "yellow") {
    el.textContent = t("tleBadgeYellow", { days: badge.age_days ?? "?" });
  } else {
    el.textContent = t("tleBadgeRed");
  }

  const lastEl = document.getElementById("satelliteTleLastRefresh");
  if (lastEl) {
    lastEl.textContent = badge.last_refresh
      ? new Date(badge.last_refresh).toLocaleString()
      : t("never");
  }
}

// ── Lightbox tabs ─────────────────────────────────────────────────────────────

export async function openSatelliteModal() {
  const modalEl = document.getElementById("satelliteModal");
  if (!modalEl) return;
  const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
  await _loadTabStation();
  await _loadTabCatalog();
  await _loadTabTles();
  modal.show();
}

async function _loadTabStation() {
  const settings = await _api("/status").catch(() => ({}));
  const saved = await fetch("/api/settings", { headers: getAuthHeader() })
    .then((r) => r.json())
    .catch(() => ({}));
  const station = (saved.satellite || {}).station || saved.station || {};
  const satCfg = saved.satellite || {};

  _setVal("satLat", station.lat ?? "");
  _setVal("satLon", station.lon ?? "");
  _setVal("satAlt", station.alt ?? "");
  _setVal("satMinEl", satCfg.min_elevation ?? 5);
}

async function _loadTabCatalog() {
  const listEl = document.getElementById("satelliteCatalogList");
  if (!listEl) return;
  try {
    const catalog = await _api("/catalog");
    if (!catalog.length) {
      listEl.innerHTML = `<tr><td colspan="5" class="text-muted">${t("noPasses")}</td></tr>`;
      return;
    }
    listEl.innerHTML = catalog
      .map(
        (s) => `
      <tr>
        <td>${s.norad_id}</td>
        <td>${_esc(s.name)}</td>
        <td>${s.downlink_hz ? (s.downlink_hz / 1e6).toFixed(3) + " MHz" : "—"}</td>
        <td>${s.mode || "—"}</td>
        <td>
          <div class="form-check form-switch mb-0">
            <input class="form-check-input sat-enable-toggle" type="checkbox"
              data-norad="${s.norad_id}" ${s.enabled ? "checked" : ""} />
          </div>
        </td>
      </tr>`
      )
      .join("");
    // Wire toggles
    listEl.querySelectorAll(".sat-enable-toggle").forEach((cb) => {
      cb.addEventListener("change", async () => {
        const norad = Number(cb.dataset.norad);
        const enabled = cb.checked;
        await _api(`/catalog/${norad}/enable?enabled=${enabled}`, { method: "POST" }).catch(
          () => { cb.checked = !enabled; }
        );
      });
    });
  } catch (e) {
    listEl.innerHTML = `<tr><td colspan="5" class="text-danger">${_esc(e.message)}</td></tr>`;
  }
}

async function _loadTabTles() {
  try {
    const badge = await _api("/tles/status");
    _renderTleBadge(badge);
  } catch {}
}

// ── Install / Uninstall ───────────────────────────────────────────────────────

export function bindSatelliteButtons() {
  const installBtn = document.getElementById("satelliteInstallBtn");
  if (installBtn) {
    installBtn.addEventListener("click", _doInstall);
  }
  const uninstallBtn = document.getElementById("satelliteUninstallBtn");
  if (uninstallBtn) {
    uninstallBtn.addEventListener("click", _doUninstall);
  }
  const refreshTleBtn = document.getElementById("satelliteRefreshTleBtn");
  if (refreshTleBtn) {
    refreshTleBtn.addEventListener("click", _doRefreshTle);
  }
  const refreshCatBtn = document.getElementById("satelliteRefreshCatBtn");
  if (refreshCatBtn) {
    refreshCatBtn.addEventListener("click", _doRefreshCatalog);
  }
  const importTleInput = document.getElementById("satelliteImportTleInput");
  if (importTleInput) {
    importTleInput.addEventListener("change", _doImportTle);
  }
  const importCatInput = document.getElementById("satelliteImportCatInput");
  if (importCatInput) {
    importCatInput.addEventListener("change", _doImportCatalog);
  }
  const saveStationBtn = document.getElementById("satelliteSaveStationBtn");
  if (saveStationBtn) {
    saveStationBtn.addEventListener("click", _doSaveStation);
  }
  const openBtn = document.getElementById("satelliteNavBtn");
  if (openBtn) {
    openBtn.addEventListener("click", openSatelliteModal);
  }
}

async function _doInstall() {
  const btn = document.getElementById("satelliteInstallBtn");
  const logEl = document.getElementById("satelliteInstallLog");
  btn.disabled = true;
  btn.textContent = t("installing");
  if (logEl) logEl.textContent = "";

  try {
    const { job_id } = await _api("/install", { method: "POST" });
    _pollJob(job_id, logEl);
  } catch (e) {
    if (logEl) logEl.textContent = `Error: ${e.message}`;
    btn.disabled = false;
    btn.textContent = t("install");
  }
}

function _pollJob(job_id, logEl) {
  const interval = setInterval(async () => {
    try {
      const job = await _api(`/install/${job_id}`);
      if (logEl) logEl.textContent = job.log || "";
      if (job.state === "done") {
        clearInterval(interval);
        await _refreshStatus();
        await _loadTabCatalog();
        await _loadTabTles();
      } else if (job.state === "error") {
        clearInterval(interval);
        const btn = document.getElementById("satelliteInstallBtn");
        if (btn) { btn.disabled = false; btn.textContent = t("install"); }
        await _refreshStatus();
      }
    } catch {}
  }, 1500);
}

async function _doUninstall() {
  if (!confirm("Uninstall Satellite module? (pass data kept)")) return;
  await _api("/uninstall?purge=false", { method: "POST" }).catch(() => {});
  await _refreshStatus();
}

async function _doRefreshTle() {
  const btn = document.getElementById("satelliteRefreshTleBtn");
  if (btn) btn.disabled = true;
  try {
    await _api("/tles/refresh", { method: "POST" });
    await _loadTabTles();
  } catch {}
  if (btn) btn.disabled = false;
}

async function _doRefreshCatalog() {
  const btn = document.getElementById("satelliteRefreshCatBtn");
  if (btn) btn.disabled = true;
  try {
    await _api("/catalog/refresh", { method: "POST" });
    await _loadTabCatalog();
  } catch {}
  if (btn) btn.disabled = false;
}

async function _doImportTle(ev) {
  const file = ev.target.files[0];
  if (!file) return;
  const buf = await file.arrayBuffer();
  const headers = { ...getAuthHeader(), "Content-Type": "text/plain" };
  try {
    const res = await fetch(`${API}/tles/import`, { method: "POST", body: buf, headers });
    const data = await res.json();
    if (res.ok) {
      alert(`TLE import: ${data.imported} imported, ${data.ignored} ignored.`);
      await _loadTabTles();
    } else {
      alert(`TLE import error: ${data.detail}`);
    }
  } catch (e) {
    alert(`TLE import error: ${e.message}`);
  }
  ev.target.value = "";
}

async function _doImportCatalog(ev) {
  const file = ev.target.files[0];
  if (!file) return;
  const buf = await file.arrayBuffer();
  const headers = { ...getAuthHeader(), "Content-Type": "application/json" };
  try {
    const res = await fetch(`${API}/catalog/import`, { method: "POST", body: buf, headers });
    const data = await res.json();
    if (res.ok) {
      alert(`Catalog import: ${data.imported} imported, ${data.ignored} ignored.`);
      await _loadTabCatalog();
    } else {
      alert(`Catalog import error: ${data.detail}`);
    }
  } catch (e) {
    alert(`Catalog import error: ${e.message}`);
  }
  ev.target.value = "";
}

async function _doSaveStation() {
  const lat = parseFloat(_getVal("satLat"));
  const lon = parseFloat(_getVal("satLon"));
  const alt = parseFloat(_getVal("satAlt") || "0");
  const minEl = parseFloat(_getVal("satMinEl") || "5");
  if (isNaN(lat) || isNaN(lon)) {
    alert("Invalid lat/lon.");
    return;
  }
  try {
    await _api("/settings", {
      method: "POST",
      body: JSON.stringify({ station: { lat, lon, alt }, min_elevation: minEl }),
    });
    const btn = document.getElementById("satelliteSaveStationBtn");
    if (btn) {
      const orig = btn.textContent;
      btn.textContent = t("saved");
      setTimeout(() => { btn.textContent = orig; }, 1500);
    }
  } catch (e) {
    alert(`Save error: ${e.message}`);
  }
}

// ── Passes panel (below catalog) ──────────────────────────────────────────────

export async function loadPassesPanel() {
  const el = document.getElementById("satellitePassesList");
  if (!el) return;
  if (!(await _isInstalled())) {
    el.innerHTML = "";
    return;
  }
  try {
    const passes = await _api("/passes?hours=24");
    if (!passes.length) {
      el.innerHTML = await _renderNoPassesDiagnostic();
      return;
    }
    el.innerHTML = passes.slice(0, 12).map(_renderPassCard).join("");
  } catch {
    el.innerHTML = "";
  }
}

function _renderPassCard(p) {
  const aosDate = new Date(p.aos);
  const losDate = new Date(p.los);
  const now = Date.now();
  const aosMs = aosDate.getTime();
  const losMs = losDate.getTime();
  const durationMin = Math.max(1, Math.round((losMs - aosMs) / 60000));
  const aosTime = aosDate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const losTime = losDate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const isActive = aosMs <= now && losMs >= now;
  const countdown = isActive
    ? `<span class="badge bg-danger">LIVE</span>`
    : `<span class="badge bg-info text-dark">in ${_fmtCountdown(aosMs - now)}</span>`;
  const el = p.max_elevation ?? 0;
  let elClass = "bg-secondary";
  if (el >= 30) elClass = "bg-success";
  else if (el >= 15) elClass = "bg-primary";
  else if (el >= 5) elClass = "bg-warning text-dark";
  const elBadge = `<span class="badge ${elClass}">${el.toFixed(1)}°</span>`;
  const az = p.max_az != null ? `${Math.round(p.max_az)}°` : "—";
  const name = _esc(p.satellite_name || `NORAD ${p.norad_id}`);
  return `
    <div class="satellite-pass-card${isActive ? " is-active" : ""}">
      <div class="satellite-pass-card__head">
        <span class="satellite-pass-card__name" title="${name}">${name}</span>
        ${countdown}
      </div>
      <div class="satellite-pass-card__body">
        <div class="satellite-pass-card__time">
          <span class="satellite-pass-card__label">AOS</span>
          <span class="satellite-pass-card__value">${aosTime}</span>
          <span class="satellite-pass-card__arrow">→</span>
          <span class="satellite-pass-card__label">LOS</span>
          <span class="satellite-pass-card__value">${losTime}</span>
          <span class="satellite-pass-card__duration">(${durationMin} min)</span>
        </div>
        <div class="satellite-pass-card__metrics">
          <span class="satellite-pass-card__metric"><span class="satellite-pass-card__label">El&nbsp;max</span> ${elBadge}</span>
          <span class="satellite-pass-card__metric"><span class="satellite-pass-card__label">Az&nbsp;max</span> <span class="satellite-pass-card__value">${az}</span></span>
        </div>
      </div>
    </div>`;
}

function _fmtCountdown(ms) {
  if (ms < 0) return "now";
  const totalMin = Math.round(ms / 60000);
  if (totalMin < 60) return `${totalMin} min`;
  const h = Math.floor(totalMin / 60);
  const m = totalMin % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

async function _renderNoPassesDiagnostic() {
  const reasons = [];
  try {
    const settings = await _api("/settings").catch(() => ({}));
    const station = settings.station || {};
    const lat = parseFloat(station.lat);
    const lon = parseFloat(station.lon);
    if (!isFinite(lat) || !isFinite(lon) || (lat === 0 && lon === 0)) {
      reasons.push("Station coordinates not configured (Station tab → Latitude/Longitude).");
    }
  } catch {}
  try {
    const cat = await _api("/catalog").catch(() => []);
    const enabled = (cat || []).filter((s) => s.enabled);
    const withTle = enabled.filter((s) => s.tle_line1 && s.tle_line2);
    if (!cat.length) {
      reasons.push("Satellite catalog is empty (Catalog tab → Refresh from SatNOGS).");
    } else if (!enabled.length) {
      reasons.push("No satellites enabled in the catalog (Catalog tab).");
    } else if (!withTle.length) {
      reasons.push("Enabled satellites have no TLE (TLEs tab → Refresh from Celestrak).");
    }
  } catch {}
  try {
    const tle = await _api("/tles/status").catch(() => ({}));
    if (tle && tle.badge === "red") {
      reasons.push("TLE data is stale or missing (TLEs tab → Refresh).");
    }
  } catch {}
  if (!reasons.length) {
    reasons.push(
      "No satellite is predicted to rise above the minimum elevation in the next 24 h. " +
        "Try lowering the minimum elevation or enabling more satellites."
    );
  }
  const items = reasons.map((r) => `<li>${_esc(r)}</li>`).join("");
  return `<div class="alert alert-secondary small mb-0"><div class="fw-semibold mb-1">${_esc(
    t("noPasses")
  )}</div><ul class="mb-0 ps-3">${items}</ul></div>`;
}

async function _isInstalled() {
  try {
    const s = await _api("/status");
    return s.installed;
  } catch {
    return false;
  }
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function _setVal(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = val;
}
function _getVal(id) {
  const el = document.getElementById(id);
  return el ? el.value : "";
}
function _esc(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
