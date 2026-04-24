/*
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
*/

/**
 * External Mirrors admin UI module.
 *
 * Drives the External Mirrors section embedded in the Admin Config modal
 * plus the dedicated mirrorFormModal (create/edit) and mirrorAuditModal
 * (audit log) overlays defined in frontend/index.html.
 *
 * Backend contract: see backend/app/api/external_mirrors.py
 *   GET    /api/admin/mirrors
 *   POST   /api/admin/mirrors
 *   GET    /api/admin/mirrors/{id}
 *   PATCH  /api/admin/mirrors/{id}
 *   DELETE /api/admin/mirrors/{id}
 *   POST   /api/admin/mirrors/{id}/enable|disable|rotate-token|test
 *   GET    /api/admin/mirrors/{id}/audit?limit=
 *
 * Plaintext tokens are returned ONLY by create + rotate-token and shown
 * once in the mirrorFormModal alert box.
 */

const BASE = "/api/admin/mirrors";

let getAuthHeaderRef = () => ({});
let toastRef = (msg) => console.log(msg);
let toastErrorRef = (msg) => console.warn(msg);

let mirrorFormModal = null;
let mirrorAuditModal = null;

/**
 * Initialise the module. Wires up DOM listeners.
 *
 * @param {object} deps
 * @param {function():object} deps.getAuthHeader - returns Basic auth headers.
 * @param {function(string):void} [deps.showToast]
 * @param {function(string):void} [deps.showToastError]
 */
export function initExternalMirrorsUI(deps = {}) {
  if (typeof deps.getAuthHeader === "function") {
    getAuthHeaderRef = deps.getAuthHeader;
  }
  if (typeof deps.showToast === "function") {
    toastRef = deps.showToast;
  }
  if (typeof deps.showToastError === "function") {
    toastErrorRef = deps.showToastError;
  }

  const refreshBtn = document.getElementById("mirrorsRefresh");
  const addBtn = document.getElementById("mirrorsAdd");
  const saveBtn = document.getElementById("mirrorFormSave");
  const formModalEl = document.getElementById("mirrorFormModal");
  const auditModalEl = document.getElementById("mirrorAuditModal");

  if (formModalEl && window.bootstrap?.Modal) {
    mirrorFormModal = window.bootstrap.Modal.getOrCreateInstance(formModalEl);
  }
  if (auditModalEl && window.bootstrap?.Modal) {
    mirrorAuditModal = window.bootstrap.Modal.getOrCreateInstance(auditModalEl);
  }

  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => loadMirrors());
  }
  if (addBtn) {
    addBtn.addEventListener("click", () => openCreateForm());
  }
  if (saveBtn) {
    saveBtn.addEventListener("click", () => submitForm());
  }

  // Auto-fill the slug from the friendly display name. The user can still
  // override it manually; once they edit the slug field directly we stop
  // mirroring (tracked via data-user-edited).
  const displayEl = document.getElementById("mirrorFormDisplayName");
  const nameEl = document.getElementById("mirrorFormName");
  if (displayEl && nameEl) {
    displayEl.addEventListener("input", () => {
      if (nameEl.disabled) return; // edit mode: name is immutable
      if (nameEl.dataset.userEdited === "1") return;
      nameEl.value = slugify(displayEl.value);
    });
    nameEl.addEventListener("input", () => {
      nameEl.dataset.userEdited = "1";
    });
  }
}

async function apiCall(path, options = {}) {
  const headers = { ...getAuthHeaderRef(), ...(options.headers || {}) };
  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const resp = await fetch(`${BASE}${path}`, { ...options, headers });
  let payload = null;
  try {
    payload = await resp.json();
  } catch (_e) {
    payload = null;
  }
  if (!resp.ok) {
    const detail = payload?.detail || `HTTP ${resp.status}`;
    const err = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    err.status = resp.status;
    err.payload = payload;
    throw err;
  }
  return payload;
}

function setListStatus(message, level = "info") {
  const el = document.getElementById("mirrorsStatus");
  if (!el) return;
  el.classList.remove("d-none", "alert-info", "alert-success", "alert-warning", "alert-danger");
  if (!message) {
    el.classList.add("d-none");
    el.textContent = "";
    return;
  }
  const cls = {
    info: "alert-info",
    success: "alert-success",
    warning: "alert-warning",
    danger: "alert-danger",
  }[level] || "alert-info";
  el.classList.add(cls);
  el.textContent = message;
}

function setFormStatus(message, level = "info") {
  const el = document.getElementById("mirrorFormStatus");
  if (!el) return;
  el.classList.remove("d-none", "alert-info", "alert-success", "alert-warning", "alert-danger");
  if (!message) {
    el.classList.add("d-none");
    el.textContent = "";
    return;
  }
  const cls = {
    info: "alert-info",
    success: "alert-success",
    warning: "alert-warning",
    danger: "alert-danger",
  }[level] || "alert-info";
  el.classList.add(cls);
  el.textContent = message;
}

function showPlaintextToken(token) {
  const box = document.getElementById("mirrorFormTokenBox");
  const value = document.getElementById("mirrorFormTokenValue");
  if (box && value) {
    value.textContent = token;
    box.classList.remove("d-none");
  }
}

function clearPlaintextToken() {
  const box = document.getElementById("mirrorFormTokenBox");
  const value = document.getElementById("mirrorFormTokenValue");
  if (box) box.classList.add("d-none");
  if (value) value.textContent = "";
}

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  } catch (_e) {
    return iso;
  }
}

function fmtScopes(scopes) {
  if (!Array.isArray(scopes) || !scopes.length) return "—";
  return scopes.join(", ");
}

/**
 * Load and render the mirrors list.
 */
export async function loadMirrors() {
  const tbody = document.querySelector("#mirrorsTable tbody");
  const empty = document.getElementById("mirrorsEmpty");
  if (!tbody) return;
  setListStatus("");
  tbody.innerHTML = "";
  try {
    // Fetch list and per-mirror replication health in parallel. Health is
    // best-effort: if the endpoint is unavailable (older backend) we still
    // render the list without lag annotations.
    const [data, healthData] = await Promise.all([
      apiCall("?include_disabled=true"),
      apiCall("/health").catch(() => null),
    ]);
    const mirrors = Array.isArray(data?.mirrors) ? data.mirrors : [];
    const healthByName = new Map();
    const healthList = Array.isArray(healthData?.mirrors) ? healthData.mirrors : [];
    for (const h of healthList) {
      if (h?.name) healthByName.set(h.name, h);
    }
    if (!mirrors.length) {
      if (empty) empty.classList.remove("d-none");
      return;
    }
    if (empty) empty.classList.add("d-none");
    for (const m of mirrors) {
      tbody.appendChild(renderRow(m, healthByName.get(m.name)));
    }
    renderHealthSummary(healthList);
  } catch (err) {
    setListStatus(`Failed to load mirrors: ${err.message}`, "danger");
  }
}

function renderHealthSummary(healthList) {
  if (!Array.isArray(healthList) || !healthList.length) return;
  const worst = healthList.reduce((acc, h) => {
    const order = { ok: 0, disabled: 0, lagging: 1, stalled: 2 };
    return (order[h.status] ?? 0) > (order[acc.status] ?? 0) ? h : acc;
  }, healthList[0]);
  const level = worst.status === "stalled"
    ? "danger"
    : worst.status === "lagging"
    ? "warning"
    : "success";
  const counts = healthList.map(
    (h) => `${h.name}: ${h.status} (cs lag ${h.lag_ids?.callsign_events ?? "?"}, oc lag ${h.lag_ids?.occupancy_events ?? "?"})`,
  ).join(" | ");
  setListStatus(`Replication: ${counts}`, level);
}

function renderRow(m, health) {
  const tr = document.createElement("tr");
  tr.dataset.mirrorId = m.id;
  const enabledBadge = m.enabled
    ? '<span class="badge bg-success">on</span>'
    : '<span class="badge bg-secondary">off</span>';
  const statusBadge = m.last_push_status
    ? `<span class="badge bg-${m.last_push_status === "ok" ? "success" : "danger"}">${m.last_push_status}</span>`
    : '<span class="text-muted">—</span>';
  const autoDisabledNote = m.auto_disabled_at
    ? ` <span class="text-danger small" title="Auto-disabled at ${fmtDate(m.auto_disabled_at)}">⛔</span>`
    : "";
  let healthBadge = "";
  if (health && health.status) {
    const cls = {
      ok: "bg-success",
      lagging: "bg-warning text-dark",
      stalled: "bg-danger",
      disabled: "bg-secondary",
    }[health.status] || "bg-secondary";
    const csLag = health.lag_ids?.callsign_events;
    const ocLag = health.lag_ids?.occupancy_events;
    healthBadge =
      ` <span class="badge ${cls}" title="cs lag ${csLag} ids, oc lag ${ocLag} ids">${health.status}</span>`;
  }
  tr.innerHTML = `
    <td><strong></strong><br><small class="text-muted"></small></td>
    <td><code class="small text-break"></code></td>
    <td><span class="small"></span></td>
    <td><span class="small"></span></td>
    <td>${statusBadge}</td>
    <td><span class="small text-muted"></span></td>
    <td><span class="small"></span>${autoDisabledNote}</td>
    <td>${enabledBadge}</td>
    <td>
      <div class="btn-group btn-group-sm" role="group">
        <button class="btn btn-outline-secondary" data-action="edit">Edit</button>
        <button class="btn btn-outline-${m.enabled ? "warning" : "success"}" data-action="${m.enabled ? "disable" : "enable"}">${m.enabled ? "Disable" : "Enable"}</button>
        <button class="btn btn-outline-info" data-action="rotate">Rotate</button>
        <button class="btn btn-outline-primary" data-action="test">Test</button>
        <button class="btn btn-outline-secondary" data-action="audit">Audit</button>
        <button class="btn btn-outline-danger" data-action="delete">Delete</button>
      </div>
    </td>`;
  const cells = tr.children;
  cells[0].querySelector("strong").textContent = m.display_name || m.name;
  cells[0].querySelector("small").textContent =
    (m.display_name ? m.name + " \u00b7 " : "") + fmtScopes(m.data_scopes);
  cells[1].querySelector("code").textContent = m.endpoint_url;
  cells[2].querySelector("span").textContent = `${m.push_interval_seconds}s`;
  cells[3].querySelector("span").textContent = fmtDate(m.last_push_at);
  cells[5].querySelector("span").textContent = m.last_push_watermark ?? "—";
  if (healthBadge) cells[5].insertAdjacentHTML("beforeend", healthBadge);
  cells[6].querySelector("span").textContent = String(m.consecutive_failures ?? 0);

  tr.querySelectorAll("button[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => handleRowAction(m, btn.dataset.action));
  });
  return tr;
}

async function handleRowAction(mirror, action) {
  switch (action) {
    case "edit":
      openEditForm(mirror);
      break;
    case "enable":
    case "disable":
      try {
        await apiCall(`/${mirror.id}/${action}`, { method: "POST" });
        toastRef(`Mirror "${mirror.name}" ${action}d`);
        await loadMirrors();
      } catch (err) {
        toastErrorRef(`Failed to ${action}: ${err.message}`);
      }
      break;
    case "rotate":
      if (!confirm(`Rotate token for "${mirror.name}"? The current token will stop working immediately.`)) return;
      try {
        const res = await apiCall(`/${mirror.id}/rotate-token`, { method: "POST" });
        openEditForm(mirror);
        if (res?.plaintext_token) {
          showPlaintextToken(res.plaintext_token);
          setFormStatus("Token rotated. Copy the new token above — it will not be shown again.", "warning");
        }
        await loadMirrors();
      } catch (err) {
        toastErrorRef(`Rotate failed: ${err.message}`);
      }
      break;
    case "test":
      try {
        setListStatus(`Testing mirror "${mirror.name}"…`, "info");
        const res = await apiCall(`/${mirror.id}/test`, { method: "POST" });
        const okFlag = !!res?.success;
        const status = res?.status_code;
        const attempts = res?.attempts;
        if (okFlag) {
          setListStatus(`Test push to "${mirror.name}" OK (HTTP ${status ?? "?"}, attempts=${attempts ?? "?"})`, "success");
        } else {
          const errMsg = res?.error || `HTTP ${status ?? "?"}`;
          setListStatus(`Test push to "${mirror.name}" failed: ${errMsg}`, "warning");
        }
      } catch (err) {
        setListStatus(`Test failed: ${err.message}`, "danger");
      }
      break;
    case "audit":
      await openAudit(mirror);
      break;
    case "delete":
      if (!confirm(`Delete mirror "${mirror.name}"? This cannot be undone.`)) return;
      try {
        await apiCall(`/${mirror.id}`, { method: "DELETE" });
        toastRef(`Mirror "${mirror.name}" deleted`);
        await loadMirrors();
      } catch (err) {
        toastErrorRef(`Delete failed: ${err.message}`);
      }
      break;
    default:
      break;
  }
}

function slugify(value) {
  if (!value) return "";
  let s;
  try {
    s = value.normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
  } catch (_) {
    s = value;
  }
  s = s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  if (!s) return "";
  if (!/^[a-z0-9]/.test(s)) s = "m-" + s;
  return s.slice(0, 64);
}

function resetForm() {
  document.getElementById("mirrorFormId").value = "";
  const displayEl = document.getElementById("mirrorFormDisplayName");
  if (displayEl) displayEl.value = "";
  document.getElementById("mirrorFormName").value = "";
  document.getElementById("mirrorFormName").disabled = false;
  document.getElementById("mirrorFormName").dataset.userEdited = "";
  document.getElementById("mirrorFormEndpoint").value = "";
  document.getElementById("mirrorFormInterval").value = "300";
  document.getElementById("mirrorFormRetention").value = "";
  document.getElementById("mirrorFormEnabled").checked = true;
  document.querySelectorAll(".mirror-scope").forEach((cb) => {
    cb.checked = true;
  });
  setFormStatus("");
  clearPlaintextToken();
}

function openCreateForm() {
  resetForm();
  document.getElementById("mirrorFormTitle").textContent = "Add Mirror";
  if (mirrorFormModal) mirrorFormModal.show();
}

function openEditForm(mirror) {
  resetForm();
  const label = mirror.display_name || mirror.name;
  document.getElementById("mirrorFormTitle").textContent = `Edit Mirror \u2014 ${label}`;
  document.getElementById("mirrorFormId").value = String(mirror.id);
  const displayEl = document.getElementById("mirrorFormDisplayName");
  if (displayEl) displayEl.value = mirror.display_name || "";
  document.getElementById("mirrorFormName").value = mirror.name;
  document.getElementById("mirrorFormName").disabled = true; // name immutable post-create
  document.getElementById("mirrorFormName").dataset.userEdited = "1";
  document.getElementById("mirrorFormEndpoint").value = mirror.endpoint_url;
  document.getElementById("mirrorFormInterval").value = String(mirror.push_interval_seconds);
  document.getElementById("mirrorFormRetention").value = mirror.retention_days ?? "";
  document.getElementById("mirrorFormEnabled").checked = !!mirror.enabled;
  const scopes = Array.isArray(mirror.data_scopes) ? mirror.data_scopes : [];
  document.querySelectorAll(".mirror-scope").forEach((cb) => {
    cb.checked = scopes.includes(cb.value);
  });
  if (mirrorFormModal) mirrorFormModal.show();
}

function collectScopes() {
  const scopes = [];
  document.querySelectorAll(".mirror-scope").forEach((cb) => {
    if (cb.checked) scopes.push(cb.value);
  });
  return scopes;
}

async function submitForm() {
  const id = document.getElementById("mirrorFormId").value.trim();
  const displayEl = document.getElementById("mirrorFormDisplayName");
  const displayName = displayEl ? displayEl.value.trim() : "";
  const name = document.getElementById("mirrorFormName").value.trim();
  const endpoint = document.getElementById("mirrorFormEndpoint").value.trim();
  const interval = parseInt(document.getElementById("mirrorFormInterval").value, 10);
  const retentionRaw = document.getElementById("mirrorFormRetention").value.trim();
  const enabled = document.getElementById("mirrorFormEnabled").checked;
  const scopes = collectScopes();

  if (!name || !endpoint) {
    setFormStatus("Name and endpoint are required.", "danger");
    return;
  }
  if (!Number.isFinite(interval) || interval < 10) {
    setFormStatus("Interval must be at least 10 seconds.", "danger");
    return;
  }
  if (!scopes.length) {
    setFormStatus("Select at least one data scope.", "danger");
    return;
  }

  const payload = {
    endpoint_url: endpoint,
    push_interval_seconds: interval,
    data_scopes: scopes,
    enabled,
    display_name: displayName || null,
  };
  if (retentionRaw) {
    const r = parseInt(retentionRaw, 10);
    if (Number.isFinite(r) && r > 0) payload.retention_days = r;
  } else {
    payload.retention_days = null;
  }

  try {
    if (id) {
      await apiCall(`/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
      setFormStatus("Mirror updated.", "success");
      toastRef(`Mirror "${name}" updated`);
      await loadMirrors();
    } else {
      const createPayload = { name, ...payload };
      const res = await apiCall("", { method: "POST", body: JSON.stringify(createPayload) });
      if (res?.plaintext_token) {
        showPlaintextToken(res.plaintext_token);
        setFormStatus("Mirror created. Copy the token above — it will not be shown again.", "warning");
        // switch form into edit mode so user can keep working without losing the token display
        if (res?.mirror?.id) {
          document.getElementById("mirrorFormId").value = String(res.mirror.id);
          document.getElementById("mirrorFormName").disabled = true;
          document.getElementById("mirrorFormTitle").textContent = `Edit Mirror — ${res.mirror.name}`;
        }
      } else {
        setFormStatus("Mirror created.", "success");
      }
      toastRef(`Mirror "${name}" created`);
      await loadMirrors();
    }
  } catch (err) {
    setFormStatus(`Save failed: ${err.message}`, "danger");
  }
}

async function openAudit(mirror) {
  const nameEl = document.getElementById("mirrorAuditName");
  const body = document.getElementById("mirrorAuditBody");
  if (nameEl) nameEl.textContent = mirror.display_name || mirror.name;
  if (body) body.innerHTML = '<tr><td colspan="4" class="text-muted">Loading…</td></tr>';
  if (mirrorAuditModal) mirrorAuditModal.show();
  try {
    const res = await apiCall(`/${mirror.id}/audit?limit=200`);
    const events = Array.isArray(res?.audit) ? res.audit : [];
    if (!body) return;
    if (!events.length) {
      body.innerHTML = '<tr><td colspan="4" class="text-muted">No audit events.</td></tr>';
      return;
    }
    body.innerHTML = "";
    for (const ev of events) {
      const tr = document.createElement("tr");
      const tsTd = document.createElement("td");
      tsTd.className = "small";
      tsTd.textContent = fmtDate(ev.ts);
      const evTd = document.createElement("td");
      evTd.innerHTML = `<code class="small"></code>`;
      evTd.querySelector("code").textContent = ev.event || "—";
      const actorTd = document.createElement("td");
      actorTd.className = "small";
      actorTd.textContent = ev.actor || "—";
      const detailsTd = document.createElement("td");
      detailsTd.innerHTML = `<pre class="small mb-0" style="max-width:560px;white-space:pre-wrap;"></pre>`;
      detailsTd.querySelector("pre").textContent = ev.details ? JSON.stringify(ev.details, null, 2) : "";
      tr.append(tsTd, evTd, actorTd, detailsTd);
      body.appendChild(tr);
    }
  } catch (err) {
    if (body) {
      body.innerHTML = `<tr><td colspan="4" class="text-danger">Failed: ${err.message}</td></tr>`;
    }
  }
}
