# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-23 21:30 UTC

import sqlite3
import json
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
        self._add_column("callsign_events", "power_dbm REAL")
        self._add_column("occupancy_events", "crest_db REAL")
        self._add_column("callsign_events", "crest_db REAL")

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
        self.conn.execute(
            """
            INSERT INTO callsign_events(
                scan_id, timestamp, band, frequency_hz, mode, callsign, snr_db,
                crest_db, df_hz, confidence, raw, grid, report, time_s, dt_s, is_new, path,
                payload, lat, lon, msg, source, device, power_dbm
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                event.get("power_dbm")
            )
        )
        self.conn.commit()

    def get_events(self, limit=None, offset=0, band=None, mode=None, callsign=None, start=None, end=None, snr_min=None):
        events = []

        # occupancy_events has no callsign column — skip entirely when filtering by callsign
        if not callsign:
            params = []
            band_filter = ""
            mode_filter_occ = ""
            time_filter = ""
            if band:
                band_filter = "AND UPPER(band) = UPPER(?)"
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
            band_filter = "AND UPPER(band) = UPPER(?)"
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
                 time_s, dt_s, is_new, path, payload, lat, lon, msg, source, device, power_dbm
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
        return events if limit is None else events[:limit]

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
            "SSB_TRAFFIC": 0,
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
                state = "SSB_CONFIRMED" if callsign_value else "SSB_TRAFFIC"
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

    def delete_events_by_ids(self, occ_ids: list, call_ids: list) -> int:
        """
        Delete specific events by ID from both tables.

        Args:
            occ_ids: List of occupancy_events IDs to delete.
            call_ids: List of callsign_events IDs to delete.

        Returns:
            Total number of rows deleted.
        """
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
