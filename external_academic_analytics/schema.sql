-- © 2026 Octávio Filipe Gonçalves
-- Callsign: CT7BFV
-- License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

-- ─────────────────────────────────────────────────────
-- 4ham Spectrum Analysis — External Mirror receiver schema (MySQL 5.7+/8.x)
--
-- Stores append-only mirror copies of callsign_events and occupancy_events
-- pushed by one or more upstream 4ham-spectrum-analysis instances over HTTPS.
--
-- Idempotency: every event row is keyed by (mirror_name, source_id) so the
-- same upstream id never produces duplicates regardless of retries.
-- ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS mirror_callsign_events (
  pk                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  mirror_name       VARCHAR(64)     NOT NULL,
  source_id         BIGINT          NOT NULL,
  received_at       DATETIME        NOT NULL,
  scan_id           BIGINT          NULL,
  timestamp         VARCHAR(32)     NOT NULL,
  band              VARCHAR(16)     NULL,
  frequency_hz      BIGINT          NOT NULL,
  mode              VARCHAR(32)     NOT NULL,
  callsign          VARCHAR(32)     NOT NULL,
  snr_db            DOUBLE          NULL,
  crest_db          DOUBLE          NULL,
  df_hz             INT             NULL,
  confidence        DOUBLE          NULL,
  raw               TEXT            NULL,
  grid              VARCHAR(16)     NULL,
  report            VARCHAR(64)     NULL,
  time_s            INT             NULL,
  dt_s              DOUBLE          NULL,
  is_new            TINYINT(1)      NULL,
  path              VARCHAR(255)    NULL,
  payload           TEXT            NULL,
  lat               DOUBLE          NULL,
  lon               DOUBLE          NULL,
  msg               TEXT            NULL,
  source            VARCHAR(64)     NULL,
  device            VARCHAR(64)     NULL,
  symbol_table      VARCHAR(4)      NULL,
  symbol_code       VARCHAR(4)      NULL,
  weather_json      TEXT            NULL,
  PRIMARY KEY (pk),
  UNIQUE KEY uniq_mirror_source (mirror_name, source_id),
  KEY idx_callsign (callsign),
  KEY idx_timestamp (timestamp),
  KEY idx_received (received_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mirror_occupancy_events (
  pk                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  mirror_name       VARCHAR(64)     NOT NULL,
  source_id         BIGINT          NOT NULL,
  received_at       DATETIME        NOT NULL,
  scan_id           BIGINT          NULL,
  timestamp         VARCHAR(32)     NOT NULL,
  band              VARCHAR(16)     NULL,
  frequency_hz      BIGINT          NOT NULL,
  bandwidth_hz      BIGINT          NOT NULL,
  power_dbm         DOUBLE          NULL,
  snr_db            DOUBLE          NULL,
  crest_db          DOUBLE          NULL,
  threshold_dbm     DOUBLE          NULL,
  occupied          TINYINT(1)      NOT NULL,
  mode              VARCHAR(32)     NULL,
  confidence        DOUBLE          NULL,
  device            VARCHAR(64)     NULL,
  PRIMARY KEY (pk),
  UNIQUE KEY uniq_mirror_source (mirror_name, source_id),
  KEY idx_band (band),
  KEY idx_timestamp (timestamp),
  KEY idx_received (received_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mirror_push_audit (
  pk                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  ts                DATETIME        NOT NULL,
  mirror_name       VARCHAR(64)     NULL,
  remote_ip         VARCHAR(64)     NULL,
  outcome           VARCHAR(32)     NOT NULL,    -- ok | bad_signature | replay | stale | malformed | unknown_mirror
  http_status       SMALLINT        NULL,
  callsign_count    INT             NULL,
  occupancy_count   INT             NULL,
  callsign_inserted INT             NULL,
  occupancy_inserted INT            NULL,
  previous_watermark BIGINT         NULL,
  new_watermark     BIGINT          NULL,
  upstream_app_version VARCHAR(32)  NULL,
  error_message     VARCHAR(512)    NULL,
  PRIMARY KEY (pk),
  KEY idx_ts (ts),
  KEY idx_mirror_ts (mirror_name, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Replay-protection store: keep nonces seen recently per mirror.
-- Caller is responsible for periodic cleanup (cron or per-request GC).
CREATE TABLE IF NOT EXISTS mirror_seen_nonces (
  mirror_name VARCHAR(64) NOT NULL,
  nonce       VARCHAR(128) NOT NULL,
  seen_at     DATETIME    NOT NULL,
  PRIMARY KEY (mirror_name, nonce),
  KEY idx_seen_at (seen_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Endpoint snapshot store: pre-computed JSON bodies pushed by the
-- backend's snapshot bundler (one row per (mirror_name, endpoint),
-- UPSERTed on every push).  PHP shims under api/ read the latest row
-- and return ``payload_json`` verbatim, so the public dashboard sees
-- the exact JSON the live backend would have produced.
CREATE TABLE IF NOT EXISTS mirror_endpoint_snapshots (
  mirror_name  VARCHAR(64)  NOT NULL,
  endpoint     VARCHAR(128) NOT NULL,
  captured_at  DATETIME     NOT NULL,
  received_at  DATETIME     NOT NULL,
  payload_json LONGTEXT     NOT NULL,
  PRIMARY KEY (mirror_name, endpoint),
  KEY idx_captured (captured_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
