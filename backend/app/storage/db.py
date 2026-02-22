# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

import sqlite3
import json


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
  device TEXT
);

CREATE INDEX IF NOT EXISTS idx_occ_time ON occupancy_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_callsign_time ON callsign_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_callsign_value ON callsign_events(callsign);
"""


class Database:
    def __init__(self, path):
        self.path = path
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
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

    def _add_column(self, table, column_def):
        try:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
            self.conn.commit()
        except sqlite3.OperationalError:
            return

    def start_scan(self, scan, started_at):
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
        self.conn.execute(
            "UPDATE scans SET ended_at = ? WHERE id = ?",
            (ended_at, scan_id)
        )
        self.conn.commit()

    def get_scans(self, limit=100):
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
        payload = json.dumps(settings or {})
        self.conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
            ("user", payload)
        )
        self.conn.commit()

    def get_settings(self):
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

    def upsert_band(self, band):
        self.conn.execute(
            "INSERT OR REPLACE INTO bands(name, start_hz, end_hz) VALUES (?, ?, ?)",
            (band.get("name"), band.get("start_hz", 0), band.get("end_hz", 0))
        )
        self.conn.commit()

    def get_bands(self):
        rows = self.conn.execute(
            "SELECT name, start_hz, end_hz FROM bands ORDER BY name"
        ).fetchall()
        return [dict(row) for row in rows]

    def add_export(self, metadata):
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
        row = self.conn.execute(
            "SELECT id, format, path, created_at, row_count, size_bytes FROM exports WHERE id = ?",
            (export_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_exports(self, limit=100):
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
        self.conn.execute("DELETE FROM exports WHERE id = ?", (export_id,))
        self.conn.commit()

    def insert_occupancy(self, event):
        self.conn.execute(
            """
            INSERT INTO occupancy_events(
                scan_id, timestamp, band, frequency_hz, bandwidth_hz, power_dbm,
                snr_db, threshold_dbm, occupied, mode, confidence, device
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.get("scan_id"),
                event.get("timestamp"),
                event.get("band"),
                event.get("frequency_hz", 0),
                event.get("bandwidth_hz", 0),
                event.get("power_dbm"),
                event.get("snr_db"),
                event.get("threshold_dbm"),
                1 if event.get("occupied") else 0,
                event.get("mode"),
                event.get("confidence"),
                event.get("device")
            )
        )
        self.conn.commit()

    def insert_callsign(self, event):
        self.conn.execute(
            """
            INSERT INTO callsign_events(
                scan_id, timestamp, band, frequency_hz, mode, callsign, snr_db,
                df_hz, confidence, raw, grid, report, time_s, dt_s, is_new, path,
                payload, lat, lon, msg, source, device
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.get("scan_id"),
                event.get("timestamp"),
                event.get("band"),
                event.get("frequency_hz", 0),
                event.get("mode"),
                event.get("callsign"),
                event.get("snr_db"),
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
                event.get("device")
            )
        )
        self.conn.commit()

    def get_events(self, limit=1000, offset=0, band=None, mode=None, callsign=None, start=None, end=None):
        events = []
        params = [limit, offset]
        band_filter = ""
        time_filter = ""
        if band:
            band_filter = "AND band = ?"
            params.insert(0, band)
        if start and end:
            time_filter = "AND timestamp BETWEEN ? AND ?"
            params.insert(0, end)
            params.insert(0, start)

        for row in self.conn.execute(
            """
            SELECT 'occupancy' AS type, scan_id, timestamp, band, frequency_hz,
                   mode, power_dbm, snr_db, threshold_dbm, occupied, confidence,
                   device
            FROM occupancy_events
            WHERE 1=1 {band_filter} {time_filter}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
            """.format(band_filter=band_filter, time_filter=time_filter),
            tuple(params)
        ):
            events.append(dict(row))

        params = [limit, offset]
        band_filter = ""
        mode_filter = ""
        callsign_filter = ""
        time_filter = ""
        if band:
            band_filter = "AND band = ?"
            params.insert(0, band)
        if mode:
            mode_filter = "AND mode = ?"
            params.insert(0, mode)
        if callsign:
            callsign_filter = "AND callsign = ?"
            params.insert(0, callsign)
        if start and end:
            time_filter = "AND timestamp BETWEEN ? AND ?"
            params.insert(0, end)
            params.insert(0, start)

        for row in self.conn.execute(
            """
             SELECT 'callsign' AS type, scan_id, timestamp, band, frequency_hz,
                 mode, callsign, snr_db, df_hz, confidence, raw, grid, report,
                 time_s, dt_s, is_new, path, payload, lat, lon, msg, source, device
            FROM callsign_events
            WHERE 1=1 {band_filter} {mode_filter} {callsign_filter} {time_filter}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
            """.format(
                band_filter=band_filter,
                mode_filter=mode_filter,
                callsign_filter=callsign_filter,
                time_filter=time_filter
            ),
            tuple(params)
        ):
            events.append(dict(row))

        events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        return events[:limit]

    def count_events(self, band=None, mode=None, callsign=None, start=None, end=None):
        params = []
        filters = []
        if band:
            filters.append("band = ?")
            params.append(band)
        if mode:
            filters.append("mode = ?")
            params.append(mode)
        if callsign:
            filters.append("callsign = ?")
            params.append(callsign)
        if start and end:
            filters.append("timestamp BETWEEN ? AND ?")
            params.extend([start, end])

        where_clause = " AND ".join(filters)
        if where_clause:
            where_clause = "WHERE " + where_clause

        occ = self.conn.execute(
            f"SELECT COUNT(*) FROM occupancy_events {where_clause}",
            tuple(params)
        ).fetchone()[0]

        calls = self.conn.execute(
            f"SELECT COUNT(*) FROM callsign_events {where_clause}",
            tuple(params)
        ).fetchone()[0]

        return int(occ) + int(calls)

    def get_event_stats(self):
        stats = {}
        for row in self.conn.execute(
            "SELECT mode, COUNT(*) AS total FROM occupancy_events GROUP BY mode"
        ):
            mode = row["mode"] or "Unknown"
            stats[mode] = stats.get(mode, 0) + int(row["total"])

        for row in self.conn.execute(
            "SELECT mode, COUNT(*) AS total FROM callsign_events GROUP BY mode"
        ):
            mode = row["mode"] or "Unknown"
            stats[mode] = stats.get(mode, 0) + int(row["total"])

        return stats

    def clear_configuration(self):
        self.conn.execute("DELETE FROM settings")
        self.conn.execute("DELETE FROM bands")
        self.conn.commit()
