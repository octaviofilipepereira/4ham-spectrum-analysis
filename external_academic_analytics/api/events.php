<?php
// © 2026 Octávio Filipe Gonçalves
// Callsign: CT7BFV
// License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
//
// ─────────────────────────────────────────────────────
//  api/events.php — public read-only events feed
//
//  Mirrors the live backend GET /api/events response shape so the
//  academic dashboard renders unchanged.  Reads from the mirror tables
//  (mirror_callsign_events + mirror_occupancy_events) populated by
//  ingest.php on every push from the home backend.
//
//  Query params (all optional):
//    limit      int (default 1000, hard cap 10000)
//    offset     int (default 0)
//    band       string (case-insensitive)
//    mode       string (case-insensitive)
//    callsign   string (case-insensitive substring)
//    snr_min    float
//    start      ISO timestamp (>=)
//    end        ISO timestamp (<=)
//    mirror     name (filter by upstream mirror)
//    format     "csv" (optional)
//
//  Output: JSON array of event dicts whose shape matches
//          backend/app/dependencies/helpers.py :: sanitize_events_for_api()
// ─────────────────────────────────────────────────────

declare(strict_types=1);

require_once __DIR__ . '/../lib/db.php';

header('X-Content-Type-Options: nosniff');
header('Cache-Control: no-store');

try {
    $cfg = fourham_load_config();
    $pdo = fourham_pdo($cfg);
} catch (Throwable $e) {
    header('Content-Type: application/json; charset=utf-8');
    http_response_code(503);
    echo json_encode(['error' => 'config_or_db', 'detail' => $e->getMessage()]);
    exit;
}

// ── Parameters ───────────────────────────────────────
$limit    = max(1, min(10000, (int)($_GET['limit'] ?? 1000)));
$offset   = max(0, (int)($_GET['offset'] ?? 0));
$band     = isset($_GET['band']) ? trim((string)$_GET['band']) : '';
$mode     = isset($_GET['mode']) ? trim((string)$_GET['mode']) : '';
$callsign = isset($_GET['callsign']) ? trim((string)$_GET['callsign']) : '';
$snrMin   = isset($_GET['snr_min']) && $_GET['snr_min'] !== '' ? (float)$_GET['snr_min'] : null;
$start    = isset($_GET['start']) ? trim((string)$_GET['start']) : '';
$end      = isset($_GET['end'])   ? trim((string)$_GET['end'])   : '';
$mirror   = isset($_GET['mirror']) ? trim((string)$_GET['mirror']) : '';
$format   = isset($_GET['format']) ? strtolower(trim((string)$_GET['format'])) : '';

// ── Helper: build WHERE clauses common to both tables ────────
$bind = [];
$conds = [];
if ($band !== '') {
    $conds[] = 'UPPER(band) = :band';
    $bind[':band'] = strtoupper($band);
}
if ($mode !== '') {
    $conds[] = 'UPPER(mode) = :mode';
    $bind[':mode'] = strtoupper($mode);
}
if ($snrMin !== null) {
    $conds[] = 'snr_db >= :snr_min';
    $bind[':snr_min'] = $snrMin;
}
if ($start !== '') {
    $conds[] = 'timestamp >= :start';
    $bind[':start'] = $start;
}
if ($end !== '') {
    $conds[] = 'timestamp <= :end';
    $bind[':end'] = $end;
}
if ($mirror !== '') {
    $conds[] = 'mirror_name = :mirror';
    $bind[':mirror'] = $mirror;
}

// callsign filter is callsign-table only
$callBind = $bind;
$callConds = $conds;
if ($callsign !== '') {
    $callConds[] = 'UPPER(callsign) LIKE :cs';
    $callBind[':cs'] = '%' . strtoupper($callsign) . '%';
}

$callWhere = !empty($callConds) ? ' WHERE ' . implode(' AND ', $callConds) : '';
$occWhere  = !empty($conds)     ? ' WHERE ' . implode(' AND ', $conds)     : '';

// ── Fetch ───────────────────────────────────────────
// Strategy: fetch up to (limit + offset) rows from each table ordered by
// timestamp DESC, merge in PHP, sort, then slice.  This mirrors the
// behaviour of state.db.get_events() which returns interleaved rows.
$cap = $limit + $offset + 100;

$selectCallsign = "SELECT 'callsign' AS type, scan_id, timestamp, band, frequency_hz, mode,
                          callsign, snr_db, crest_db, df_hz, confidence, payload, grid,
                          report, time_s, dt_s, is_new, path, lat, lon, msg, source, device
                     FROM mirror_callsign_events" . $callWhere
                . " ORDER BY timestamp DESC LIMIT " . (int)$cap;

$selectOccupancy = "SELECT 'occupancy' AS type, scan_id, timestamp, band, frequency_hz, mode,
                           NULL AS callsign, snr_db, crest_db, NULL AS df_hz, confidence,
                           NULL AS payload, NULL AS grid, NULL AS report, NULL AS time_s,
                           NULL AS dt_s, NULL AS is_new, NULL AS path, NULL AS lat, NULL AS lon,
                           NULL AS msg, NULL AS source, device,
                           bandwidth_hz, power_dbm, threshold_dbm, occupied
                      FROM mirror_occupancy_events" . $occWhere
                 . " ORDER BY timestamp DESC LIMIT " . (int)$cap;

try {
    $stmt = $pdo->prepare($selectCallsign);
    $stmt->execute($callBind);
    $callsignRows = $stmt->fetchAll();

    $occupancyRows = [];
    if ($callsign === '') {
        // Don't pull occupancy when filtering by callsign (occupancy has none).
        $stmt = $pdo->prepare($selectOccupancy);
        $stmt->execute($bind);
        $occupancyRows = $stmt->fetchAll();
    }
} catch (Throwable $e) {
    header('Content-Type: application/json; charset=utf-8');
    http_response_code(500);
    echo json_encode(['error' => 'db_query', 'detail' => $e->getMessage()]);
    exit;
}

// ── Inline band inference (mirrors helpers.infer_band_from_frequency) ──
function fourham_infer_band(?int $hz): ?string {
    if ($hz === null || $hz <= 0) return null;
    static $bands = [
        ['160m',  1_800_000,    2_000_000],
        ['80m',   3_500_000,    4_000_000],
        ['60m',   5_250_000,    5_450_000],
        ['40m',   7_000_000,    7_300_000],
        ['30m',   10_100_000,   10_150_000],
        ['20m',   14_000_000,   14_350_000],
        ['17m',   18_068_000,   18_168_000],
        ['15m',   21_000_000,   21_450_000],
        ['12m',   24_890_000,   24_990_000],
        ['10m',   28_000_000,   29_700_000],
        ['6m',    50_000_000,   54_000_000],
        ['2m',    144_000_000,  148_000_000],
        ['70cm',  430_000_000,  450_000_000],
    ];
    foreach ($bands as $b) {
        if ($hz >= $b[1] && $hz <= $b[2]) return $b[0];
    }
    return null;
}

// ── Merge + sanitize (mirrors sanitize_events_for_api) ─────────────────
$merged = [];

foreach ($callsignRows as $row) {
    // crest_db backfill from JSON payload (legacy callsign rows).
    if (($row['crest_db'] === null || $row['crest_db'] === '') && !empty($row['payload'])) {
        $obj = json_decode((string)$row['payload'], true);
        if (is_array($obj) && isset($obj['crest_db']) && $obj['crest_db'] !== null) {
            $row['crest_db'] = $obj['crest_db'];
        }
    }
    if (empty($row['band'])) {
        $row['band'] = fourham_infer_band(isset($row['frequency_hz']) ? (int)$row['frequency_hz'] : null);
    }
    $merged[] = $row;
}

foreach ($occupancyRows as $row) {
    // Filter invalid occupancy events.
    $freq = isset($row['frequency_hz']) ? (float)$row['frequency_hz'] : 0.0;
    $b    = strtolower(trim((string)($row['band'] ?? '')));
    $m    = strtolower(trim((string)($row['mode'] ?? '')));
    $occ  = !empty($row['occupied']);
    $sid  = $row['scan_id'] ?? null;
    $invalid_noise = (!$occ) && $freq <= 0 && ($b === '' || $b === 'null') && $m === 'unknown';
    $invalid_unbound = ($sid === null) && $freq <= 0 && ($b === '' || $b === 'null');
    if ($invalid_noise || $invalid_unbound) continue;
    if (empty($row['band'])) {
        $row['band'] = fourham_infer_band(isset($row['frequency_hz']) ? (int)$row['frequency_hz'] : null);
    }
    $merged[] = $row;
}

// Sort merged by timestamp DESC and slice.
usort($merged, function ($a, $b) {
    return strcmp((string)($b['timestamp'] ?? ''), (string)($a['timestamp'] ?? ''));
});
$merged = array_slice($merged, $offset, $limit);

// ── Cast numeric fields (PDO returns strings on MySQL by default) ─────
foreach ($merged as &$row) {
    foreach (['frequency_hz', 'scan_id', 'df_hz', 'time_s', 'bandwidth_hz'] as $k) {
        if (isset($row[$k]) && $row[$k] !== null && $row[$k] !== '') {
            $row[$k] = (int)$row[$k];
        }
    }
    foreach (['snr_db', 'crest_db', 'confidence', 'dt_s', 'lat', 'lon',
             'power_dbm', 'threshold_dbm'] as $k) {
        if (isset($row[$k]) && $row[$k] !== null && $row[$k] !== '') {
            $row[$k] = (float)$row[$k];
        }
    }
    if (isset($row['occupied'])) {
        $row['occupied'] = (bool)$row['occupied'];
    }
    if (isset($row['is_new']) && $row['is_new'] !== null && $row['is_new'] !== '') {
        $row['is_new'] = (bool)$row['is_new'];
    }
}
unset($row);

// ── CSV branch ────────────────────────────────────────
if ($format === 'csv') {
    header('Content-Type: text/csv; charset=utf-8');
    $lines = ['Type,Timestamp,Band,FrequencyHz,Mode,Callsign,Confidence,SNR,PowerDbm,ScanId'];
    foreach ($merged as $r) {
        $lines[] = implode(',', [
            (string)($r['type'] ?? ''),
            (string)($r['timestamp'] ?? ''),
            (string)($r['band'] ?? ''),
            (string)($r['frequency_hz'] ?? ''),
            (string)($r['mode'] ?? ''),
            (string)($r['callsign'] ?? ''),
            (string)($r['confidence'] ?? ''),
            (string)($r['snr_db'] ?? ''),
            (string)($r['power_dbm'] ?? ''),
            (string)($r['scan_id'] ?? ''),
        ]);
    }
    echo implode("\n", $lines);
    exit;
}

header('Content-Type: application/json; charset=utf-8');
echo json_encode($merged, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
