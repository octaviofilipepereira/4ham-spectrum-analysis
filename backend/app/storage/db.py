import sqlite3


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
                df_hz, confidence, raw, source, device
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                event.get("source"),
                event.get("device")
            )
        )
        self.conn.commit()

    def get_events(self, limit=1000):
        events = []
        for row in self.conn.execute(
            """
            SELECT 'occupancy' AS type, scan_id, timestamp, band, frequency_hz,
                   mode, power_dbm, snr_db, threshold_dbm, occupied, confidence,
                   device
            FROM occupancy_events
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,)
        ):
            events.append(dict(row))

        for row in self.conn.execute(
            """
             SELECT 'callsign' AS type, scan_id, timestamp, band, frequency_hz,
                 mode, callsign, snr_db, df_hz, confidence, raw, source, device
            FROM callsign_events
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,)
        ):
            events.append(dict(row))

        events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        return events[:limit]
