-- SQLite schema for events and scans

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
