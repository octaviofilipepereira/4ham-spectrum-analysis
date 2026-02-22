# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 16:27:19 UTC

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
  source TEXT,
  device TEXT
);

CREATE INDEX IF NOT EXISTS idx_occ_time ON occupancy_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_callsign_time ON callsign_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_callsign_value ON callsign_events(callsign);
