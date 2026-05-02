# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-03-15 16:00 UTC

import sqlite3
import json
import threading
from datetime import datetime, timedelta, timezone


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS devices (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  name TEXT,
  capabilities TEXT
);

CREATE TABLE IF NOT EXISTS scans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  band TEXT NOT NULL,
  start_hz INTEGER NOT NULL,
  end_hz INTEGER NOT NULL,
  step_hz INTEGER NOT NULL,
  dwell_ms INTEGER NOT NULL,
  mode TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bands (
    name TEXT PRIMARY KEY,
    start_hz INTEGER NOT NULL,
    end_hz INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS exports (
    id TEXT PRIMARY KEY,
    format TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS occupancy_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER,
  timestamp TEXT NOT NULL,
  band TEXT,
  frequency_hz INTEGER NOT NULL,
  bandwidth_hz INTEGER NOT NULL,
  power_dbm REAL,
  snr_db REAL,
    crest_db REAL,
  threshold_dbm REAL,
  occupied INTEGER NOT NULL,
  mode TEXT,
  confidence REAL,
  device TEXT
);

CREATE TABLE IF NOT EXISTS callsign_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER,
  timestamp TEXT NOT NULL,
  band TEXT,
  frequency_hz INTEGER NOT NULL,
  mode TEXT NOT NULL,
  callsign TEXT NOT NULL,
  snr_db REAL,
    crest_db REAL,
  df_hz INTEGER,
  confidence REAL,
  raw TEXT,
    grid TEXT,
    report TEXT,
    time_s INTEGER,
    dt_s REAL,
    is_new INTEGER,
    path TEXT,
    payload TEXT,
    lat REAL,
    lon REAL,
    msg TEXT,
  source TEXT,
  device TEXT,
  rf_gated INTEGER
);

CREATE INDEX IF NOT EXISTS idx_occ_time ON occupancy_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_callsign_time ON callsign_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_callsign_value ON callsign_events(callsign);
-- Composite indices used by the /api/events/stats and /api/events/count
-- endpoints, which group/filter by mode within a recent timestamp window.
-- Without these, COUNT(*) GROUP BY mode falls back to a full table scan
-- of the ~800k row event tables (HAR analysis 2026-04-30 showed ~1 s per call).
CREATE INDEX IF NOT EXISTS idx_occ_mode_time ON occupancy_events(mode, timestamp);
CREATE INDEX IF NOT EXISTS idx_callsign_mode_time ON callsign_events(mode, timestamp);

CREATE TABLE IF NOT EXISTS rotation_presets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  config TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
  session_hash TEXT PRIMARY KEY,
  user TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preset_schedules (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  preset_id  INTEGER NOT NULL REFERENCES rotation_presets(id) ON DELETE CASCADE,
  start_hhmm TEXT NOT NULL,
  end_hhmm   TEXT NOT NULL,
  enabled    INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

-- ── External Mirrors (push of dashboard data to remote read-only hosts) ──
CREATE TABLE IF NOT EXISTS external_mirrors (
  id                      INTEGER PRIMARY KEY AUTOINCREMENT,
  name                    TEXT    NOT NULL UNIQUE,
  endpoint_url            TEXT    NOT NULL,
  auth_token_hash         TEXT    NOT NULL,
  enabled                 INTEGER NOT NULL DEFAULT 1,
  push_interval_seconds   INTEGER NOT NULL DEFAULT 300,
  data_scopes             TEXT    NOT NULL DEFAULT '[]',
  retention_days          INTEGER,
  last_push_at            TEXT,
  last_push_status        TEXT,
  last_push_watermark     INTEGER NOT NULL DEFAULT 0,
  consecutive_failures    INTEGER NOT NULL DEFAULT 0,
  auto_disabled_at        TEXT,
  created_at              TEXT    NOT NULL,
  created_by              TEXT    NOT NULL,
  updated_at              TEXT
);

CREATE TABLE IF NOT EXISTS external_mirror_audit (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  mirror_id  INTEGER NOT NULL REFERENCES external_mirrors(id) ON DELETE CASCADE,
  ts         TEXT    NOT NULL,
  event      TEXT    NOT NULL,
  actor      TEXT,
  details    TEXT
);

CREATE INDEX IF NOT EXISTS idx_ext_mirror_audit_mirror_ts
  ON external_mirror_audit(mirror_id, ts DESC);

-- ── NCDXF/IARU Beacon Analysis ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS beacon_observations (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  slot_start_utc     TEXT    NOT NULL,
  slot_index         INTEGER NOT NULL,
  beacon_callsign    TEXT    NOT NULL,
  beacon_index       INTEGER NOT NULL,
  beacon_location    TEXT,
  beacon_status      TEXT,
  band_name          TEXT    NOT NULL,
  freq_hz            INTEGER NOT NULL,
  detected           INTEGER NOT NULL DEFAULT 0,
  id_confirmed       INTEGER NOT NULL DEFAULT 0,
  id_confidence      REAL,
  drift_ms           REAL,
  dash_levels_detected INTEGER NOT NULL DEFAULT 0,
  snr_db_100w        REAL,
  snr_db_10w         REAL,
  snr_db_1w          REAL,
  snr_db_100mw       REAL,
  recorded_at        TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_beacon_obs_time
  ON beacon_observations(slot_start_utc DESC);
CREATE INDEX IF NOT EXISTS idx_beacon_obs_callsign
  ON beacon_observations(beacon_callsign, slot_start_utc DESC);
CREATE INDEX IF NOT EXISTS idx_beacon_obs_band
  ON beacon_observations(band_name, slot_start_utc DESC);
"""


class Database:
    def __init__(self, path):
        self.path = path
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # Performance pragmas:
        # - WAL: allows concurrent readers while a writer is active and avoids
        #   blocking every read on the writer fsync, which was a major source
        #   of API latency under polling load (HAR analysis 2026-04-30).
        # - synchronous=NORMAL: sufficient durability with WAL; full sync on
        #   every commit is overkill for a logging workload.
        # - temp_store=MEMORY: keeps temporary B-trees off disk for COUNT(*)
        #   group-by queries used by /api/events/stats.
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA temp_store=MEMORY")
        except sqlite3.DatabaseError:
            # Pragmas are best-effort; a corrupt or read-only DB will still
            # surface its real error in the next operation.
            pass
        self._lock = threading.RLock()  # Thread-safe access to SQLite connection
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(_SCHEMA_SQL)
        self.conn.commit()
        self._ensure_columns()

    def _ensure_columns(self):
        self._add_column("occupancy_events", "scan_id INTEGER")
        self._add_column("callsign_events", "scan_id INTEGER")
        self._add_column("callsign_events", "grid TEXT")
        self._add_column("callsign_events", "report TEXT")
        self._add_column("callsign_events", "time_s INTEGER")
        self._add_column("callsign_events", "dt_s REAL")
        self._add_column("callsign_events", "is_new INTEGER")
        self._add_column("callsign_events", "path TEXT")
        self._add_column("callsign_events", "payload TEXT")
        self._add_column("callsign_events", "lat REAL")
        self._add_column("callsign_events", "lon REAL")
        self._add_column("callsign_events", "msg TEXT")
        self._add_column("callsign_events", "power_dbm REAL")
        self._add_column("occupancy_events", "crest_db REAL")
        self._add_column("callsign_events", "crest_db REAL")
        # APRS RF-gated flag: True when the inner callsign did NOT transmit
        # on RF — its packet was carried over the air by a 3rd-party
        # encapsulation (`}`) or originally injected via TCPIP. Stored as
        # 0/1 INTEGER for SQLite compatibility.
        self._add_column("callsign_events", "rf_gated INTEGER")
        # APRS weather payload (JSON): populated for WX stations (symbol '_').
        self._add_column("callsign_events", "weather_json TEXT")
        # APRS symbol identifier: table ('/' primary, '\' alternate, or overlay
        # letter) + code (1 char). Used by the frontend to render station icons.
        self._add_column("callsign_events", "symbol_table TEXT")
        self._add_column("callsign_events", "symbol_code TEXT")
        # Encrypted-at-rest plaintext mirror token (for restart-safe pusher).
        self._add_column("external_mirrors", "auth_token_ciphertext TEXT")
        # Free-form Unicode label for the Admin UI (the slug-style ``name`` stays
        # as the technical identifier sent in headers and used in config files).
        self._add_column("external_mirrors", "display_name TEXT")

    def _add_column(self, table, column_def):
        try:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
            self.conn.commit()
        except sqlite3.OperationalError:
            return

    # Public alias — use this in satellite and other on-demand modules
    def add_column(self, table: str, column_def: str) -> None:
        """Idempotently add a column to an existing table (no-op if already exists)."""
        self._add_column(table, column_def)

    def start_scan(self, scan, started_at):
        with self._lock:
            cursor = self.conn.execute(
                """
                INSERT INTO scans(
                    band, start_hz, end_hz, step_hz, dwell_ms, mode, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scan.get("band"),
                    scan.get("start_hz", 0),
                    scan.get("end_hz", 0),
                    scan.get("step_hz", 0),
                    scan.get("dwell_ms", 0),
                    scan.get("mode", "auto"),
                    started_at
                )
            )
            self.conn.commit()
            return cursor.lastrowid

    def end_scan(self, scan_id, ended_at):
        if scan_id is None:
            return
        with self._lock:
            self.conn.execute(
                "UPDATE scans SET ended_at = ? WHERE id = ?",
                (ended_at, scan_id)
            )
            self.conn.commit()

    def get_scans(self, limit=100):
        with self._lock:
            scans = []
            for row in self.conn.execute(
                """
                SELECT id, band, start_hz, end_hz, step_hz, dwell_ms, mode,
                       started_at, ended_at
                FROM scans
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,)
            ):
                scans.append(dict(row))
            return scans

    def save_settings(self, settings):
        """Thread-safe settings storage."""
        with self._lock:
            payload = json.dumps(settings or {})
            self.conn.execute(
                "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                ("user", payload)
            )
            self.conn.commit()

    def get_settings(self):
        """Thread-safe settings retrieval."""
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM settings WHERE key = ?",
                ("user",)
            ).fetchone()
            if not row:
                return {}
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return {}

    def get_kv(self, key: str) -> str | None:
        """Read a single string value from the settings table by key."""
        with self._lock:
            row = self.conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row else None

    def set_kv(self, key: str, value: str) -> None:
        """Write a single string value to the settings table."""
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                (key, value),
            )
            self.conn.commit()

    # ── Rotation Presets CRUD ──────────────────────────────────────

    def get_rotation_presets(self):
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, name, config, created_at FROM rotation_presets ORDER BY id"
            ).fetchall()
        return [{"id": r[0], "name": r[1], "config": json.loads(r[2]), "created_at": r[3]} for r in rows]

    def save_rotation_preset(self, name: str, config: dict) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO rotation_presets(name, config, created_at) VALUES (?, ?, ?)",
                (name, json.dumps(config), now),
            )
            self.conn.commit()
        return {"id": cur.lastrowid, "name": name, "config": config, "created_at": now}

    def delete_rotation_preset(self, preset_id: int) -> bool:
        with self._lock:
            cur = self.conn.execute("DELETE FROM rotation_presets WHERE id = ?", (preset_id,))
            # CASCADE: remove schedules referencing this preset
            self.conn.execute("DELETE FROM preset_schedules WHERE preset_id = ?", (preset_id,))
            self.conn.commit()
        return cur.rowcount > 0

    # ── Preset Schedules CRUD ──────────────────────────────────────

    def get_preset_schedules(self) -> list:
        with self._lock:
            rows = self.conn.execute(
                "SELECT s.id, s.preset_id, s.start_hhmm, s.end_hhmm, s.enabled, "
                "s.created_at, p.name AS preset_name "
                "FROM preset_schedules s "
                "LEFT JOIN rotation_presets p ON p.id = s.preset_id "
                "ORDER BY s.start_hhmm"
            ).fetchall()
        return [
            {
                "id": r[0], "preset_id": r[1], "start_hhmm": r[2],
                "end_hhmm": r[3], "enabled": bool(r[4]),
                "created_at": r[5], "preset_name": r[6] or "(deleted)",
            }
            for r in rows
        ]

    def save_preset_schedule(self, preset_id: int, start_hhmm: str, end_hhmm: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO preset_schedules(preset_id, start_hhmm, end_hhmm, enabled, created_at) "
                "VALUES (?, ?, ?, 1, ?)",
                (preset_id, start_hhmm, end_hhmm, now),
            )
            self.conn.commit()
        return {
            "id": cur.lastrowid, "preset_id": preset_id,
            "start_hhmm": start_hhmm, "end_hhmm": end_hhmm,
            "enabled": True, "created_at": now,
        }

    def toggle_preset_schedule(self, schedule_id: int, enabled: bool) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "UPDATE preset_schedules SET enabled = ? WHERE id = ?",
                (int(enabled), schedule_id),
            )
            self.conn.commit()
        return cur.rowcount > 0

    def delete_preset_schedule(self, schedule_id: int) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM preset_schedules WHERE id = ?", (schedule_id,)
            )
            self.conn.commit()
        return cur.rowcount > 0

    def get_auth_config(self):
        """Return stored auth credentials and enable flag."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT key, value FROM settings WHERE key IN (?, ?, ?)",
                ("_auth_user", "_auth_pass_hash", "_auth_enabled"),
            ).fetchall()
        result = {"auth_user": "", "auth_pass_hash": "", "auth_enabled": False}
        for row in rows:
            if row[0] == "_auth_user":
                result["auth_user"] = row[1]
            elif row[0] == "_auth_pass_hash":
                result["auth_pass_hash"] = row[1]
            elif row[0] == "_auth_enabled":
                result["auth_enabled"] = str(row[1]).strip() in {"1", "true", "yes", "on"}
        return result

    def save_auth_config(self, user: str, pass_hash: str) -> None:
        """Persist auth credentials and enable state. Pass empty strings to clear."""
        with self._lock:
            if user and pass_hash:
                self.conn.execute(
                    "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                    ("_auth_user", user),
                )
                self.conn.execute(
                    "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                    ("_auth_pass_hash", pass_hash),
                )
                self.conn.execute(
                    "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                    ("_auth_enabled", "1"),
                )
            else:
                self.conn.execute(
                    "DELETE FROM settings WHERE key IN (?, ?)",
                    ("_auth_user", "_auth_pass_hash"),
                )
                self.conn.execute(
                    "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
                    ("_auth_enabled", "0"),
                )
                self.clear_auth_session()
            self.conn.commit()

    def get_auth_session(self):
        """Legacy compat — return first non-expired session or empty dict."""
        with self._lock:
            row = self.conn.execute(
                "SELECT session_hash, user, expires_at FROM auth_sessions ORDER BY expires_at DESC LIMIT 1",
            ).fetchone()
        if not row:
            return {"session_hash": "", "expires_at": "", "user": ""}
        return {"session_hash": row[0], "user": row[1], "expires_at": row[2]}

    def get_auth_session_by_hash(self, session_hash: str) -> dict:
        """Look up a specific session by its hash."""
        with self._lock:
            row = self.conn.execute(
                "SELECT session_hash, user, expires_at FROM auth_sessions WHERE session_hash = ?",
                (session_hash,),
            ).fetchone()
        if not row:
            return {}
        return {"session_hash": row[0], "user": row[1], "expires_at": row[2]}

    def save_auth_session(self, session_hash: str, expires_at: str, user: str) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            # Purge expired sessions
            self.conn.execute(
                "DELETE FROM auth_sessions WHERE expires_at <= ?", (now_iso,)
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO auth_sessions(session_hash, user, expires_at) VALUES (?, ?, ?)",
                (session_hash, user, expires_at),
            )
            self.conn.commit()

    def clear_auth_session(self, session_hash: str = None) -> None:
        with self._lock:
            if session_hash:
                self.conn.execute(
                    "DELETE FROM auth_sessions WHERE session_hash = ?", (session_hash,)
                )
            else:
                self.conn.execute("DELETE FROM auth_sessions")
                # Clean up legacy settings-based session keys
                self.conn.execute(
                    "DELETE FROM settings WHERE key IN (?, ?, ?)",
                    ("_auth_session_hash", "_auth_session_expires_at", "_auth_session_user"),
                )
            self.conn.commit()

    def upsert_band(self, band):
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO bands(name, start_hz, end_hz) VALUES (?, ?, ?)",
                (band.get("name"), band.get("start_hz", 0), band.get("end_hz", 0))
            )
            self.conn.commit()

    def get_bands(self):
        with self._lock:
            rows = self.conn.execute(
                "SELECT name, start_hz, end_hz FROM bands ORDER BY name"
            ).fetchall()
            return [dict(row) for row in rows]

    def add_export(self, metadata):
        with self._lock:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO exports(id, format, path, created_at, row_count, size_bytes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    metadata.get("id"),
                    metadata.get("format"),
                    metadata.get("path"),
                    metadata.get("created_at"),
                    int(metadata.get("row_count", 0) or 0),
                    int(metadata.get("size_bytes", 0) or 0),
                )
            )
            self.conn.commit()

    def get_export(self, export_id):
        with self._lock:
            row = self.conn.execute(
                "SELECT id, format, path, created_at, row_count, size_bytes FROM exports WHERE id = ?",
                (export_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_exports(self, limit=100):
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT id, format, path, created_at, row_count, size_bytes
                FROM exports
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    def delete_export(self, export_id):
        with self._lock:
            self.conn.execute("DELETE FROM exports WHERE id = ?", (export_id,))
            self.conn.commit()

    def insert_occupancy(self, event):
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO occupancy_events(
                    scan_id, timestamp, band, frequency_hz, bandwidth_hz, power_dbm,
                    snr_db, crest_db, threshold_dbm, occupied, mode, confidence, device
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.get("scan_id"),
                    event.get("timestamp"),
                    event.get("band"),
                    event.get("frequency_hz", 0),
                    event.get("bandwidth_hz", 0),
                    event.get("power_dbm"),
                    event.get("snr_db"),
                    event.get("crest_db"),
                    event.get("threshold_dbm"),
                    1 if event.get("occupied") else 0,
                    event.get("mode"),
                    event.get("confidence"),
                    event.get("device")
                )
            )
            self.conn.commit()

    def insert_callsign(self, event):
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO callsign_events(
                    scan_id, timestamp, band, frequency_hz, mode, callsign, snr_db,
                    crest_db, df_hz, confidence, raw, grid, report, time_s, dt_s, is_new, path,
                    payload, lat, lon, msg, source, device, power_dbm, rf_gated, weather_json,
                    symbol_table, symbol_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.get("scan_id"),
                    event.get("timestamp"),
                    event.get("band"),
                    event.get("frequency_hz", 0),
                    event.get("mode"),
                    event.get("callsign"),
                    event.get("snr_db"),
                    event.get("crest_db"),
                    event.get("df_hz"),
                    event.get("confidence"),
                    event.get("raw"),
                    event.get("grid"),
                    event.get("report"),
                    event.get("time_s"),
                    event.get("dt_s"),
                    1 if event.get("is_new") else 0 if event.get("is_new") is not None else None,
                    event.get("path"),
                    event.get("payload"),
                    event.get("lat"),
                    event.get("lon"),
                    event.get("msg"),
                    event.get("source"),
                    event.get("device"),
                    event.get("power_dbm"),
                    1 if event.get("rf_gated") else 0 if event.get("rf_gated") is not None else None,
                    json.dumps(event["weather"]) if event.get("weather") else None,
                    event.get("symbol_table"),
                    event.get("symbol_code"),
                )
            )
            self.conn.commit()

    # ── NCDXF Beacon Observations ─────────────────────────────────────────────

    def insert_beacon_observation(self, obs: dict) -> int:
        """Insert one beacon observation row.  Returns the new row id."""
        from datetime import datetime, timezone as _tz
        recorded_at = datetime.now(_tz.utc).isoformat()
        with self._lock:
            cur = self.conn.execute(
                """
                INSERT INTO beacon_observations(
                    slot_start_utc, slot_index, beacon_callsign, beacon_index,
                    beacon_location, beacon_status, band_name, freq_hz,
                    detected, id_confirmed, id_confidence, drift_ms,
                    dash_levels_detected,
                    snr_db_100w, snr_db_10w, snr_db_1w, snr_db_100mw,
                    recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    obs.get("slot_start_utc"),
                    obs.get("slot_index"),
                    obs.get("beacon_callsign"),
                    obs.get("beacon_index"),
                    obs.get("beacon_location"),
                    obs.get("beacon_status"),
                    obs.get("band_name"),
                    obs.get("freq_hz"),
                    1 if obs.get("detected") else 0,
                    1 if obs.get("id_confirmed") else 0,
                    obs.get("id_confidence"),
                    obs.get("drift_ms"),
                    obs.get("dash_levels_detected", 0),
                    obs.get("snr_db_100w"),
                    obs.get("snr_db_10w"),
                    obs.get("snr_db_1w"),
                    obs.get("snr_db_100mw"),
                    recorded_at,
                ),
            )
            self.conn.commit()
            return cur.lastrowid

    def get_beacon_observations(
        self,
        limit: int = 100,
        offset: int = 0,
        band: str | None = None,
        callsign: str | None = None,
        detected_only: bool = False,
    ) -> list[dict]:
        """Return beacon observations ordered newest-first."""
        clauses: list[str] = []
        params: list = []
        if band:
            clauses.append("band_name = ?")
            params.append(band)
        if callsign:
            clauses.append("UPPER(beacon_callsign) = UPPER(?)")
            params.append(callsign)
        if detected_only:
            clauses.append("detected = 1")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params += [limit, offset]
        with self._lock:
            rows = self.conn.execute(
                f"""
                SELECT id, slot_start_utc, slot_index, beacon_callsign,
                       beacon_index, beacon_location, beacon_status,
                       band_name, freq_hz, detected, id_confirmed,
                       id_confidence, drift_ms, dash_levels_detected,
                       snr_db_100w, snr_db_10w, snr_db_1w, snr_db_100mw,
                       recorded_at
                FROM beacon_observations
                {where}
                ORDER BY slot_start_utc DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def get_beacon_heatmap(self, hours: float = 2.0) -> list[dict]:
        """Aggregated beacon activity over the last ``hours`` hours.

        Returns one row per (beacon_index, band_name) cell with:
          - total slots monitored in window
          - detections (detected=1) in window
          - id_confirmed count in window
                    - best detected pass summary from one coherent observation row
                    - latest detected slot_start_utc (or NULL if none)
        """
        cutoff_iso = (
            datetime.now(timezone.utc) - timedelta(hours=hours)
        ).isoformat()
        with self._lock:
            rows = self.conn.execute(
                """
                                WITH windowed AS (
                                    SELECT *
                                    FROM beacon_observations
                                    WHERE slot_start_utc >= ?
                                ),
                                counts AS (
                                    SELECT
                                        beacon_index,
                                        band_name,
                                        COUNT(*) AS total_slots,
                                        SUM(detected) AS detections,
                                        SUM(id_confirmed) AS id_confirmed,
                                        MAX(CASE WHEN detected=1 THEN slot_start_utc END) AS latest_detected_utc
                                    FROM windowed
                                    GROUP BY beacon_index, band_name
                                ),
                                ranked_detected AS (
                                    SELECT
                                        beacon_index,
                                        band_name,
                                        slot_start_utc AS best_detected_utc,
                                        snr_db_100w AS best_snr_db,
                                        dash_levels_detected AS best_dashes,
                                        id_confirmed AS best_id_confirmed,
                                        ROW_NUMBER() OVER (
                                            PARTITION BY beacon_index, band_name
                                            ORDER BY
                                                dash_levels_detected DESC,
                                                COALESCE(snr_db_100w, -9999.0) DESC,
                                                id_confirmed DESC,
                                                slot_start_utc DESC
                                        ) AS row_num
                                    FROM windowed
                                    WHERE detected = 1
                                )
                                SELECT
                                    counts.beacon_index,
                                    counts.band_name,
                                    counts.total_slots,
                                    counts.detections,
                                    counts.id_confirmed,
                                    ranked_detected.best_snr_db,
                                    ranked_detected.best_dashes,
                                    ranked_detected.best_id_confirmed,
                                    ranked_detected.best_detected_utc,
                                    counts.latest_detected_utc
                                FROM counts
                                LEFT JOIN ranked_detected
                                    ON ranked_detected.beacon_index = counts.beacon_index
                                 AND ranked_detected.band_name = counts.band_name
                                 AND ranked_detected.row_num = 1
                """,
                (cutoff_iso,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_events(self, limit=None, offset=0, band=None, mode=None, callsign=None, start=None, end=None, snr_min=None):
        """Thread-safe event retrieval with proper SQLite synchronization.

        The limit is applied independently to each table (occupancy_events,
        callsign_events) so that one table cannot crowd out the other when
        they are merged.
        """
        with self._lock:
            events = []
            # Each table gets its own limit so neither can starve the other
            per_table_limit = limit if limit is not None else -1

            # occupancy_events has no callsign column — skip entirely when filtering by callsign
            if not callsign:
                params = []
                band_filter = ""
                mode_filter_occ = ""
                time_filter = ""
                if band:
                    band_filter = "AND (UPPER(band) = UPPER(?) OR band IS NULL)"
                    params.append(band)
                if mode:
                    mode_filter_occ = "AND UPPER(mode) LIKE UPPER(?)"
                    params.append(f"%{mode}%")
                if start and end:
                    time_filter = "AND timestamp BETWEEN ? AND ?"
                    params.append(start)
                    params.append(end)
                # LIMIT -1 means no limit in SQLite
                params.extend([limit if limit is not None else -1, offset])

                for row in self.conn.execute(
                    """
                    SELECT 'occupancy' AS type, scan_id, timestamp, band, frequency_hz,
                         bandwidth_hz, mode, power_dbm, snr_db, crest_db, threshold_dbm, occupied, confidence,
                           device
                    FROM occupancy_events
                    WHERE 1=1 {band_filter} {mode_filter_occ} {time_filter}
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?
                    """.format(band_filter=band_filter, mode_filter_occ=mode_filter_occ, time_filter=time_filter),
                    tuple(params)
                ):
                    events.append(dict(row))

            params = []
            band_filter = ""
            mode_filter = ""
            callsign_filter = ""
            snr_filter = ""
            time_filter = ""
            if band:
                band_filter = "AND (UPPER(band) = UPPER(?) OR band IS NULL)"
                params.append(band)
            if mode:
                mode_filter = "AND UPPER(mode) LIKE UPPER(?)"
                params.append(f"%{mode}%")
            if callsign:
                callsign_filter = "AND UPPER(callsign) LIKE UPPER(?)"
                params.append(f"%{callsign}%")
            if snr_min is not None:
                snr_filter = "AND snr_db >= ?"
                params.append(float(snr_min))
            if start and end:
                time_filter = "AND timestamp BETWEEN ? AND ?"
                params.append(start)
                params.append(end)
            # LIMIT -1 means no limit in SQLite
            params.extend([limit if limit is not None else -1, offset])

            for row in self.conn.execute(
                """
                 SELECT 'callsign' AS type, scan_id, timestamp, band, frequency_hz,
                     mode, callsign, snr_db, crest_db, df_hz, confidence, raw, grid, report,
                     time_s, dt_s, is_new, path, payload, lat, lon, msg, source, device, power_dbm, rf_gated, weather_json,
                     symbol_table, symbol_code
                FROM callsign_events
                WHERE 1=1 {band_filter} {mode_filter} {callsign_filter} {snr_filter} {time_filter}
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """.format(
                    band_filter=band_filter,
                    mode_filter=mode_filter,
                    callsign_filter=callsign_filter,
                    snr_filter=snr_filter,
                    time_filter=time_filter
                ),
                tuple(params)
            ):
                events.append(dict(row))

            events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
            return events

    def get_callsign_events(self, limit=None, offset=0, band=None, mode=None, start=None, end=None, snr_min=None):
        """Fetch only callsign events (no occupancy). Used by map endpoint."""
        with self._lock:
            params = []
            filters = []
            if band:
                filters.append("AND (UPPER(band) = UPPER(?) OR band IS NULL)")
                params.append(band)
            if mode:
                filters.append("AND UPPER(mode) LIKE UPPER(?)")
                params.append(f"%{mode}%")
            if snr_min is not None:
                filters.append("AND snr_db >= ?")
                params.append(float(snr_min))
            if start and end:
                filters.append("AND timestamp BETWEEN ? AND ?")
                params.append(start)
                params.append(end)
            params.extend([limit if limit is not None else -1, offset])
            rows = self.conn.execute(
                """
                SELECT 'callsign' AS type, scan_id, timestamp, band, frequency_hz,
                       mode, callsign, snr_db, crest_db, df_hz, confidence, raw, grid, report,
                       time_s, dt_s, is_new, path, payload, lat, lon, msg, source, device, power_dbm, rf_gated, weather_json,
                       symbol_table, symbol_code
                FROM callsign_events
                WHERE 1=1 {filters}
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """.format(filters=" ".join(filters)),
                tuple(params)
            )
            return [dict(r) for r in rows]

    def count_events(self, band=None, mode=None, callsign=None, start=None, end=None):
        """Thread-safe event counting with proper SQLite synchronization."""
        with self._lock:
            # occupancy_events has no callsign column — build separate filters for each table
            occ_count = 0
            
            # Count occupancy events (only if not filtering by callsign)
            if not callsign:
                params_occ = []
                filters_occ = []
                if band:
                    filters_occ.append("band = ?")
                    params_occ.append(band)
                if mode:
                    filters_occ.append("mode = ?")
                    params_occ.append(mode)
                if start and end:
                    filters_occ.append("timestamp BETWEEN ? AND ?")
                    params_occ.extend([start, end])

                where_clause_occ = " AND ".join(filters_occ)
                if where_clause_occ:
                    where_clause_occ = "WHERE " + where_clause_occ

                occ_count = self.conn.execute(
                    f"SELECT COUNT(*) FROM occupancy_events {where_clause_occ}",
                    tuple(params_occ)
                ).fetchone()[0]

            # Count callsign events (can use all filters including callsign)
            params_calls = []
            filters_calls = []
            if band:
                filters_calls.append("band = ?")
                params_calls.append(band)
            if mode:
                filters_calls.append("mode = ?")
                params_calls.append(mode)
            if callsign:
                filters_calls.append("callsign = ?")
                params_calls.append(callsign)
            if start and end:
                filters_calls.append("timestamp BETWEEN ? AND ?")
                params_calls.extend([start, end])

            where_clause_calls = " AND ".join(filters_calls)
            if where_clause_calls:
                where_clause_calls = "WHERE " + where_clause_calls

            calls_count = self.conn.execute(
                f"SELECT COUNT(*) FROM callsign_events {where_clause_calls}",
                tuple(params_calls)
            ).fetchone()[0]

            return int(occ_count) + int(calls_count)

    def get_event_stats(self):
        """Thread-safe event statistics retrieval."""
        with self._lock:
            stats = {"modes": {}, "total": 0}
            
            # Count occupancy events
            occupancy_total = 0
            for row in self.conn.execute(
                "SELECT mode, COUNT(*) AS total FROM occupancy_events GROUP BY mode"
            ):
                mode = row["mode"] or "Unknown"
                count = int(row["total"])
                stats["modes"][mode] = stats["modes"].get(mode, 0) + count
                occupancy_total += count

            # Count callsign events
            callsign_total = 0
            for row in self.conn.execute(
                "SELECT mode, COUNT(*) AS total FROM callsign_events GROUP BY mode"
            ):
                mode = row["mode"] or "Unknown"
                count = int(row["total"])
                stats["modes"][mode] = stats["modes"].get(mode, 0) + count
                callsign_total += count
            
            stats["total"] = occupancy_total + callsign_total
            return stats

    def get_decoder_baseline_stats(self):
        with self._lock:
            baseline = {
                "callsign_events_total": 0,
                "callsign_unique_total": 0,
                "by_source": {},
                "callsign_modes": {},
            }

            total_row = self.conn.execute(
                "SELECT COUNT(*) AS total, COUNT(DISTINCT callsign) AS unique_total FROM callsign_events"
            ).fetchone()
            baseline["callsign_events_total"] = int(total_row["total"] or 0) if total_row else 0
            baseline["callsign_unique_total"] = int(total_row["unique_total"] or 0) if total_row else 0

            for row in self.conn.execute(
                """
                SELECT
                    COALESCE(NULLIF(TRIM(CAST(source AS TEXT)), ''), 'unknown') AS source,
                    COUNT(*) AS total,
                    COUNT(DISTINCT callsign) AS unique_callsigns,
                    MAX(timestamp) AS last_seen_at
                FROM callsign_events
                GROUP BY source
                ORDER BY total DESC
                """
            ):
                source = str(row["source"] or "unknown")
                baseline["by_source"][source] = {
                    "total": int(row["total"] or 0),
                    "unique_callsigns": int(row["unique_callsigns"] or 0),
                    "last_seen_at": row["last_seen_at"],
                }

            for row in self.conn.execute(
                """
                SELECT COALESCE(NULLIF(TRIM(CAST(mode AS TEXT)), ''), 'Unknown') AS mode, COUNT(*) AS total
                FROM callsign_events
                GROUP BY mode
                ORDER BY total DESC
                """
            ):
                mode = str(row["mode"] or "Unknown")
                baseline["callsign_modes"][mode] = int(row["total"] or 0)

            return baseline

    def get_ssb_metrics(self, window_minutes: int = 15):
        try:
            minutes = int(window_minutes)
        except (TypeError, ValueError):
            minutes = 15
        minutes = max(1, min(1440, minutes))

        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(minutes=minutes)).isoformat()

        with self._lock:
            rows = self.conn.execute(
                """
                SELECT timestamp, callsign, confidence, payload
                FROM callsign_events
                WHERE UPPER(mode) = 'SSB' AND timestamp >= ?
                ORDER BY timestamp DESC
                """,
                (cutoff,),
            ).fetchall()

        by_state = {
            "SSB_CONFIRMED": 0,
            "SSB": 0,
            "SSB_UNKNOWN": 0,
        }
        by_parse_method = {}
        scores = []

        first_event_at = rows[-1]["timestamp"] if rows else None
        last_event_at = rows[0]["timestamp"] if rows else None

        for row in rows:
            payload_raw = row["payload"]
            payload = {}
            if isinstance(payload_raw, str) and payload_raw.strip():
                try:
                    payload = json.loads(payload_raw)
                except json.JSONDecodeError:
                    payload = {}

            callsign_value = str(row["callsign"] or "").strip()
            state = payload.get("ssb_state")
            if not state:
                state = "SSB_CONFIRMED" if callsign_value else "SSB"
            state = str(state).strip().upper()
            if state not in by_state:
                state = "SSB_UNKNOWN"
            by_state[state] += 1

            parse_method = str(payload.get("ssb_parse_method") or "unknown").strip().lower()
            by_parse_method[parse_method] = by_parse_method.get(parse_method, 0) + 1

            score_value = payload.get("ssb_score", row["confidence"])
            try:
                score_float = float(score_value)
            except (TypeError, ValueError):
                score_float = None
            if score_float is not None:
                score_float = max(0.0, min(1.0, score_float))
                scores.append(score_float)

        total_events = len(rows)
        confirmed = by_state.get("SSB_CONFIRMED", 0)

        return {
            "window_minutes": minutes,
            "window_start": cutoff,
            "window_end": now.isoformat(),
            "first_event_at": first_event_at,
            "last_event_at": last_event_at,
            "total_events": total_events,
            "by_state": by_state,
            "confirmed_ratio": round((confirmed / total_events), 3) if total_events else 0.0,
            "scores": {
                "count": len(scores),
                "avg": round(sum(scores) / len(scores), 3) if scores else None,
                "min": round(min(scores), 3) if scores else None,
                "max": round(max(scores), 3) if scores else None,
            },
            "parse_methods": by_parse_method,
        }

    def purge_invalid_events(self):
        occupancy_where_clause = """
        (timestamp IS NULL OR TRIM(CAST(timestamp AS TEXT)) = '')
        OR (
            (frequency_hz IS NULL OR CAST(frequency_hz AS REAL) <= 0)
            AND (band IS NULL OR TRIM(CAST(band AS TEXT)) = '' OR LOWER(TRIM(CAST(band AS TEXT))) = 'null')
        )
        OR (
            (scan_id IS NULL)
            AND (mode IS NULL OR TRIM(CAST(mode AS TEXT)) = '' OR LOWER(TRIM(CAST(mode AS TEXT))) = 'unknown')
            AND COALESCE(CAST(occupied AS INTEGER), 0) = 0
            AND (snr_db IS NULL)
            AND (power_dbm IS NULL)
            AND (frequency_hz IS NULL OR CAST(frequency_hz AS REAL) <= 0)
        )
        """
        callsign_where_clause = """
        (timestamp IS NULL OR TRIM(CAST(timestamp AS TEXT)) = '')
        OR (
            callsign IS NULL
            OR TRIM(CAST(callsign AS TEXT)) = ''
            OR LOWER(TRIM(CAST(callsign AS TEXT))) IN ('unknown', 'null', 'n/a', '?')
        )
        OR (
            (frequency_hz IS NULL OR CAST(frequency_hz AS REAL) <= 0)
            AND (band IS NULL OR TRIM(CAST(band AS TEXT)) = '' OR LOWER(TRIM(CAST(band AS TEXT))) = 'null')
        )
        """

        with self._lock:
            occ_before = self.conn.execute(
                f"SELECT COUNT(*) AS total FROM occupancy_events WHERE {occupancy_where_clause}"
            ).fetchone()[0]
            occ_cursor = self.conn.execute(
                f"DELETE FROM occupancy_events WHERE {occupancy_where_clause}"
            )
            occ_deleted = occ_cursor.rowcount

            calls_before = self.conn.execute(
                f"SELECT COUNT(*) AS total FROM callsign_events WHERE {callsign_where_clause}"
            ).fetchone()[0]
            calls_cursor = self.conn.execute(
                f"DELETE FROM callsign_events WHERE {callsign_where_clause}"
            )
            calls_deleted = calls_cursor.rowcount

            self.conn.commit()

            occ_after = self.conn.execute(
                f"SELECT COUNT(*) AS total FROM occupancy_events WHERE {occupancy_where_clause}"
            ).fetchone()[0]
            calls_after = self.conn.execute(
                f"SELECT COUNT(*) AS total FROM callsign_events WHERE {callsign_where_clause}"
            ).fetchone()[0]

        return {
            "before": int(occ_before) + int(calls_before),
            "deleted": int(occ_deleted) + int(calls_deleted),
            "after": int(occ_after) + int(calls_after),
            "details": {
                "occupancy": {
                    "before": int(occ_before),
                    "deleted": int(occ_deleted),
                    "after": int(occ_after),
                },
                "callsign": {
                    "before": int(calls_before),
                    "deleted": int(calls_deleted),
                    "after": int(calls_after),
                },
            },
        }

    def clear_configuration(self):
        with self._lock:
            self.conn.execute("DELETE FROM settings")
            self.conn.execute("DELETE FROM bands")
            self.conn.commit()

    def get_purgeable_events(self, days: int, max_events: int) -> dict:
        """
        Identify events to be purged based on age and/or count limits.

        Returns event records (for export) and their IDs (for deletion).
        Phase 1: events older than `days` days.
        Phase 2: if total remaining still exceeds `max_events`, oldest excess events.

        Args:
            days: Maximum age in days; 0 disables age-based selection.
            max_events: Maximum total events to keep; 0 disables count-based selection.

        Returns:
            dict with keys: events (list), occ_ids (list), call_ids (list), count (int)
        """
        from datetime import datetime, timedelta, timezone

        with self._lock:
            occ_age_ids = []
            call_age_ids = []

            # --- Phase 1: age-based ---
            if days > 0:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
                occ_age_ids = [
                    r[0] for r in self.conn.execute(
                        "SELECT id FROM occupancy_events WHERE timestamp < ? ORDER BY timestamp ASC",
                        (cutoff,)
                    ).fetchall()
                ]
                call_age_ids = [
                    r[0] for r in self.conn.execute(
                        "SELECT id FROM callsign_events WHERE timestamp < ? ORDER BY timestamp ASC",
                        (cutoff,)
                    ).fetchall()
                ]

            # --- Phase 2: count-based ---
            occ_count_ids = []
            call_count_ids = []

            if max_events > 0:
                total_occ = self.conn.execute("SELECT COUNT(*) FROM occupancy_events").fetchone()[0]
                total_call = self.conn.execute("SELECT COUNT(*) FROM callsign_events").fetchone()[0]
                remaining = (total_occ - len(occ_age_ids)) + (total_call - len(call_age_ids))

                if remaining > max_events:
                    excess = remaining - max_events

                    # Take oldest occupancy events first
                    if occ_age_ids:
                        ph = ",".join("?" * len(occ_age_ids))
                        rows = self.conn.execute(
                            f"SELECT id FROM occupancy_events WHERE id NOT IN ({ph})"
                            f" ORDER BY timestamp ASC LIMIT ?",
                            occ_age_ids + [excess]
                        ).fetchall()
                    else:
                        rows = self.conn.execute(
                            "SELECT id FROM occupancy_events ORDER BY timestamp ASC LIMIT ?",
                            (excess,)
                        ).fetchall()
                    occ_count_ids = [r[0] for r in rows]

                    still_excess = excess - len(occ_count_ids)
                    if still_excess > 0:
                        if call_age_ids:
                            ph = ",".join("?" * len(call_age_ids))
                            rows = self.conn.execute(
                                f"SELECT id FROM callsign_events WHERE id NOT IN ({ph})"
                                f" ORDER BY timestamp ASC LIMIT ?",
                                call_age_ids + [still_excess]
                            ).fetchall()
                        else:
                            rows = self.conn.execute(
                                "SELECT id FROM callsign_events ORDER BY timestamp ASC LIMIT ?",
                                (still_excess,)
                            ).fetchall()
                        call_count_ids = [r[0] for r in rows]

            occ_ids = list(set(occ_age_ids) | set(occ_count_ids))
            call_ids = list(set(call_age_ids) | set(call_count_ids))

            if not occ_ids and not call_ids:
                return {"events": [], "occ_ids": [], "call_ids": [], "count": 0}

            # Fetch event records for export
            events = []

            if occ_ids:
                ph = ",".join("?" * len(occ_ids))
                rows = self.conn.execute(
                    f"SELECT timestamp, band, frequency_hz, mode, snr_db, power_dbm,"
                    f" scan_id, confidence FROM occupancy_events WHERE id IN ({ph})",
                    occ_ids
                ).fetchall()
                for r in rows:
                    events.append({
                        "type": "occupancy",
                        "timestamp": r[0], "band": r[1], "frequency_hz": r[2],
                        "mode": r[3], "callsign": None, "snr_db": r[4],
                        "power_dbm": r[5], "scan_id": r[6], "confidence": r[7],
                    })

            if call_ids:
                ph = ",".join("?" * len(call_ids))
                rows = self.conn.execute(
                    f"SELECT timestamp, band, frequency_hz, mode, callsign, snr_db,"
                    f" scan_id, confidence FROM callsign_events WHERE id IN ({ph})",
                    call_ids
                ).fetchall()
                for r in rows:
                    events.append({
                        "type": "callsign",
                        "timestamp": r[0], "band": r[1], "frequency_hz": r[2],
                        "mode": r[3], "callsign": r[4], "snr_db": r[5],
                        "power_dbm": None, "scan_id": r[6], "confidence": r[7],
                    })

            return {
                "events": events,
                "occ_ids": occ_ids,
                "call_ids": call_ids,
                "count": len(events),
            }

    def get_all_events_and_keep_newest(self, keep: int) -> dict:
        """
        Fetch ALL events for export, then identify IDs to delete keeping only
        the `keep` most recent events across both tables.

        Returns:
            dict with keys: events (list), occ_ids (list), call_ids (list), count (int)
        """
        with self._lock:
            # Fetch all events from both tables ordered oldest-first for export
            occ_rows = self.conn.execute(
                "SELECT id, timestamp, band, frequency_hz, mode, snr_db, power_dbm,"
                " scan_id, confidence FROM occupancy_events ORDER BY timestamp ASC"
            ).fetchall()
            call_rows = self.conn.execute(
                "SELECT id, timestamp, band, frequency_hz, mode, callsign, snr_db,"
                " scan_id, confidence FROM callsign_events ORDER BY timestamp ASC"
            ).fetchall()

            events = []
            for r in occ_rows:
                events.append({
                    "type": "occupancy",
                    "timestamp": r[1], "band": r[2], "frequency_hz": r[3],
                    "mode": r[4], "callsign": None, "snr_db": r[5],
                    "power_dbm": r[6], "scan_id": r[7], "confidence": r[8],
                })
            for r in call_rows:
                events.append({
                    "type": "callsign",
                    "timestamp": r[1], "band": r[2], "frequency_hz": r[3],
                    "mode": r[4], "callsign": r[5], "snr_db": r[6],
                    "power_dbm": None, "scan_id": r[7], "confidence": r[8],
                })

            total = len(occ_rows) + len(call_rows)
            if total <= keep:
                # Nothing to delete
                return {"events": events, "occ_ids": [], "call_ids": [], "count": 0}

            # Determine which IDs to DELETE: all except the `keep` most recent.
            # Merge both tables sorted by timestamp descending, keep first `keep`.
            all_sorted = sorted(
                [(r[0], r[1], "occ") for r in occ_rows] +
                [(r[0], r[1], "call") for r in call_rows],
                key=lambda x: x[1],
                reverse=True,
            )
            keep_set_occ = set()
            keep_set_call = set()
            for row_id, _ts, tbl in all_sorted[:keep]:
                if tbl == "occ":
                    keep_set_occ.add(row_id)
                else:
                    keep_set_call.add(row_id)

            occ_ids = [r[0] for r in occ_rows if r[0] not in keep_set_occ]
            call_ids = [r[0] for r in call_rows if r[0] not in keep_set_call]

            return {
                "events": events,
                "occ_ids": occ_ids,
                "call_ids": call_ids,
                "count": len(occ_ids) + len(call_ids),
            }

    def delete_events_by_ids(self, occ_ids: list, call_ids: list) -> int:
        """
        Delete specific events by ID from both tables.

        Args:
            occ_ids: List of occupancy_events IDs to delete.
            call_ids: List of callsign_events IDs to delete.

        Returns:
            Total number of rows deleted.
        """
        with self._lock:
            deleted = 0
            if occ_ids:
                ph = ",".join("?" * len(occ_ids))
                cursor = self.conn.execute(
                    f"DELETE FROM occupancy_events WHERE id IN ({ph})", occ_ids
                )
                deleted += cursor.rowcount
            if call_ids:
                ph = ",".join("?" * len(call_ids))
                cursor = self.conn.execute(
                    f"DELETE FROM callsign_events WHERE id IN ({ph})", call_ids
                )
                deleted += cursor.rowcount
            self.conn.commit()
            return deleted
