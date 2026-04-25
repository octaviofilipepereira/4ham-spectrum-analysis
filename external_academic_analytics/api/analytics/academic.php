<?php
// © 2026 Octávio Filipe Gonçalves — License: AGPL-3.0
//
// Academic analytics endpoint — queries mirror_callsign_events directly
// instead of serving a pre-computed snapshot. This is what makes the
// dashboard period selector (1h/24h/7d/30d) actually filter correctly:
// the SQL window matches start/end exactly.
//
// Output shape mirrors backend/app/api/analytics.py::academic_analytics
// for the fields the frontend consumes (data.series, data.callsigns,
// data.raw_events). Heavy server-side propagation_by_band / propagation_trend
// are returned empty — the frontend falls back to its own client-side
// computePropagationAnalytics() in that case.
declare(strict_types=1);
require_once __DIR__ . '/../../lib/query.php';

$appVersion = '';
try {
    $cfg = fourham_load_config();
    $pdo = fourham_pdo($cfg);
} catch (Throwable $e) {
    fourham_send_json(503, [
        'status' => 'error',
        'error'  => 'config_or_db',
        'detail' => $e->getMessage(),
    ]);
    return;
}
// Best-effort: pull app_version from snapshots so the dashboard title
// keeps showing the upstream backend version.
try {
    $row = $pdo->query(
        "SELECT payload_json FROM mirror_endpoint_snapshots
          WHERE endpoint = 'version' ORDER BY captured_at DESC LIMIT 1"
    )->fetch();
    if ($row) {
        $v = json_decode((string)$row['payload_json'], true);
        if (is_array($v)) {
            $appVersion = (string)($v['app_version'] ?? $v['version'] ?? '');
        }
    }
} catch (Throwable $_e) { /* non-fatal */ }

[$startIso, $endIso, $startDt, $endDt] = fourham_resolve_window(
    isset($_GET['start']) ? (string)$_GET['start'] : null,
    isset($_GET['end'])   ? (string)$_GET['end']   : null,
    24 * 60
);
$windowSec = max(60, $endDt->getTimestamp() - $startDt->getTimestamp());
$bucket    = fourham_pick_bucket(
    isset($_GET['bucket']) ? (string)$_GET['bucket'] : null,
    $windowSec
);
$bandFilter = isset($_GET['band']) ? trim((string)$_GET['band']) : '';
$modeFilter = isset($_GET['mode']) ? strtoupper(trim((string)$_GET['mode'])) : '';

$bucketSql = fourham_bucket_sql($bucket);
$modeNorm  = fourham_normalised_mode_sql();

// ── Common WHERE / param binding helpers ─────────────────────────
$whereClauses = ['timestamp BETWEEN :start AND :end'];
$params = [
    ':start' => $startIso,
    ':end'   => $endIso,
];
if ($bandFilter !== '' && strtoupper($bandFilter) !== 'ALL') {
    $whereClauses[] = 'band = :band';
    $params[':band'] = $bandFilter;
}
if ($modeFilter !== '' && $modeFilter !== 'ALL') {
    // Apply on the normalised value so SSB/CW selectors still match
    // SSB_TRAFFIC / CW_TRAFFIC etc.
    $whereClauses[] = "($modeNorm) = :mode";
    $params[':mode'] = $modeFilter;
}
$whereSql = implode(' AND ', $whereClauses);

// ── Series: count + average SNR per (bucket, band, mode) ─────────
$series = [];
try {
    $sql = "SELECT
                $bucketSql AS ts,
                band       AS band,
                $modeNorm  AS mode,
                COUNT(*)   AS cnt,
                AVG(snr_db) AS avg_snr,
                SUM(CASE WHEN snr_db IS NOT NULL THEN 1 ELSE 0 END) AS snr_cnt
            FROM mirror_callsign_events
           WHERE $whereSql
           GROUP BY ts, band, mode
           ORDER BY ts ASC";
    $stmt = $pdo->prepare($sql);
    $stmt->execute($params);
    foreach ($stmt->fetchAll() as $r) {
        $series[] = [
            'ts'        => (string)$r['ts'],
            'band'      => (string)($r['band'] ?? ''),
            'mode'      => (string)$r['mode'],
            'count'     => (int)$r['cnt'],
            'snr'       => $r['avg_snr'] !== null ? round((float)$r['avg_snr'], 2) : 0,
            'snr_count' => (int)($r['snr_cnt'] ?? 0),
        ];
    }
} catch (Throwable $e) {
    fourham_send_json(503, [
        'status' => 'error',
        'error'  => 'series_query',
        'detail' => $e->getMessage(),
    ]);
    return;
}

// ── Callsigns: per (bucket, band, mode, callsign) decode count ───
$callsigns = [];
try {
    $sql = "SELECT
                $bucketSql AS ts,
                band       AS band,
                $modeNorm  AS mode,
                UPPER(callsign) AS callsign,
                COUNT(*)   AS hits
            FROM mirror_callsign_events
           WHERE $whereSql AND callsign <> ''
           GROUP BY ts, band, mode, callsign
           ORDER BY hits DESC, ts DESC
           LIMIT 5000";
    $stmt = $pdo->prepare($sql);
    $stmt->execute($params);
    foreach ($stmt->fetchAll() as $r) {
        $callsigns[] = [
            'ts'       => (string)$r['ts'],
            'band'     => (string)($r['band'] ?? ''),
            'mode'     => (string)$r['mode'],
            'callsign' => (string)$r['callsign'],
            'hits'     => (int)$r['hits'],
        ];
    }
} catch (Throwable $e) {
    fourham_send_json(503, [
        'status' => 'error',
        'error'  => 'callsigns_query',
        'detail' => $e->getMessage(),
    ]);
    return;
}

// ── Raw events: most recent N within the window ─────────────────
$rawEvents = [];
try {
    $sql = "SELECT timestamp, band, $modeNorm AS mode, snr_db,
                   frequency_hz, callsign, grid, lat, lon
              FROM mirror_callsign_events
             WHERE $whereSql
             ORDER BY timestamp DESC
             LIMIT 1000";
    $stmt = $pdo->prepare($sql);
    $stmt->execute($params);
    foreach ($stmt->fetchAll() as $r) {
        $rawEvents[] = [
            'timestamp'    => (string)$r['timestamp'],
            'type'         => 'callsign',
            'band'         => (string)($r['band'] ?? ''),
            'mode'         => (string)$r['mode'],
            'snr_db'       => $r['snr_db'] !== null ? round((float)$r['snr_db'], 1) : null,
            'frequency_hz' => $r['frequency_hz'] !== null ? (int)$r['frequency_hz'] : null,
            'callsign'     => (string)($r['callsign'] ?? '') ?: null,
            'grid'         => (string)($r['grid'] ?? '') ?: null,
            'lat'          => $r['lat'] !== null ? (float)$r['lat'] : null,
            'lon'          => $r['lon'] !== null ? (float)$r['lon'] : null,
        ];
    }
} catch (Throwable $_e) {
    // raw_events is non-critical — keep empty on failure
}

// ── KPIs (aggregate over the same window) ───────────────────────
$kpis = [
    'total_events'      => 0,
    'unique_callsigns'  => 0,
    'snr_avg'           => null,
    'snr_digital_avg'   => null,
    'snr_analog_avg'    => null,
    'period_minutes'    => max(1, (int)round($windowSec / 60.0)),
    'propagation_score' => null,
    'stability_pct'     => null,
];
try {
    $stmt = $pdo->prepare(
        "SELECT
            COUNT(*)                                  AS total,
            COUNT(DISTINCT NULLIF(UPPER(callsign), '')) AS uniq,
            AVG(snr_db)                               AS snr_avg,
            AVG(CASE WHEN UPPER(mode) IN ('FT8','FT4','WSPR','JT65','JT9','FST4','FST4W','Q65') THEN snr_db END) AS snr_dig,
            AVG(CASE WHEN UPPER(mode) NOT IN ('FT8','FT4','WSPR','JT65','JT9','FST4','FST4W','Q65') THEN snr_db END) AS snr_ana
           FROM mirror_callsign_events
          WHERE $whereSql"
    );
    $stmt->execute($params);
    if ($r = $stmt->fetch()) {
        $kpis['total_events']     = (int)$r['total'];
        $kpis['unique_callsigns'] = (int)$r['uniq'];
        if ($r['snr_avg'] !== null) $kpis['snr_avg']         = round((float)$r['snr_avg'], 2);
        if ($r['snr_dig'] !== null) $kpis['snr_digital_avg'] = round((float)$r['snr_dig'], 2);
        if ($r['snr_ana'] !== null) $kpis['snr_analog_avg']  = round((float)$r['snr_ana'], 2);
    }
} catch (Throwable $_e) { /* non-fatal */ }

fourham_send_json(200, [
    'status'      => 'ok',
    'app_version' => $appVersion,
    'snapshot_utc' => gmdate('Y-m-d\TH:i:s\Z'),
    'kpis' => $kpis,
    'data' => [
        'series'              => $series,
        'callsigns'           => $callsigns,
        'raw_events'          => $rawEvents,
        'propagation_by_band' => [],
        'propagation_trend'   => [],
    ],
]);
