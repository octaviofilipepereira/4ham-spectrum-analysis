<?php
// © 2026 Octávio Filipe Gonçalves — License: AGPL-3.0
//
// Live map contacts endpoint — queries mirror_callsign_events directly
// so the dashboard's window selector (?window_minutes=) returns the
// callsigns actually decoded in that period instead of a stale 60-min
// snapshot pre-computed on the home backend.
//
// Mirrors the JSON shape of backend/app/api/map.py::map_contacts so the
// frontend (frontend/map.js) is unchanged.
declare(strict_types=1);
require_once __DIR__ . '/../../lib/query.php';

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

$windowMinutes = isset($_GET['window_minutes'])
    ? max(1, min(7 * 24 * 60, (int)$_GET['window_minutes']))
    : 60;
$limit = isset($_GET['limit'])
    ? max(1, min(5000, (int)$_GET['limit']))
    : 2000;

[$startIso, $endIso, $startDt, $endDt] = fourham_resolve_window(
    null,
    null,
    $windowMinutes
);

$station = fourham_station_from_snapshot($pdo);

// One row per (callsign, band) keeping the strongest SNR. Done in SQL
// because the dashboard typically asks for windows with thousands of
// rows and we don't want to ship them all to PHP.
$modeNorm = fourham_normalised_mode_sql();
$sql = "
    SELECT t.callsign, t.band, t.mode, t.snr_db, t.lat, t.lon, t.ts
      FROM (
        SELECT
            UPPER(callsign)                       AS callsign,
            band                                  AS band,
            $modeNorm                             AS mode,
            snr_db                                AS snr_db,
            lat                                   AS lat,
            lon                                   AS lon,
            timestamp                             AS ts,
            ROW_NUMBER() OVER (
                PARTITION BY UPPER(callsign), band
                ORDER BY (snr_db IS NULL) ASC, snr_db DESC, timestamp DESC
            ) AS rn
          FROM mirror_callsign_events
         WHERE timestamp BETWEEN :start AND :end
           AND callsign <> ''
           AND lat IS NOT NULL AND lon IS NOT NULL
           AND UPPER(mode) <> 'APRS'
      ) t
     WHERE t.rn = 1
     ORDER BY t.ts DESC
     LIMIT :lim
";

try {
    $stmt = $pdo->prepare($sql);
    $stmt->bindValue(':start', $startIso, PDO::PARAM_STR);
    $stmt->bindValue(':end',   $endIso,   PDO::PARAM_STR);
    $stmt->bindValue(':lim',   $limit,    PDO::PARAM_INT);
    $stmt->execute();
    $rows = $stmt->fetchAll();
} catch (Throwable $e) {
    fourham_send_json(503, [
        'status' => 'error',
        'error'  => 'db_query',
        'detail' => $e->getMessage(),
    ]);
    return;
}

$contacts = [];
foreach ($rows as $r) {
    $lat = (float)$r['lat'];
    $lon = (float)$r['lon'];
    $contacts[] = [
        'callsign'    => (string)$r['callsign'],
        'lat'         => $lat,
        'lon'         => $lon,
        'country'     => '',     // DXCC enrichment lives on the home backend
        'continent'   => '',
        'cq_zone'     => null,
        'band'        => (string)($r['band'] ?? ''),
        'mode'        => (string)($r['mode'] ?? ''),
        'snr_db'      => $r['snr_db'] !== null ? (float)$r['snr_db'] : null,
        'distance_km' => round(
            fourham_haversine_km($station['lat'], $station['lon'], $lat, $lon),
            1
        ),
        'timestamp'   => (string)$r['ts'],
    ];
}

fourham_send_json(200, [
    'status'         => 'ok',
    'window_minutes' => $windowMinutes,
    'station'        => $station,
    'contact_count'  => count($contacts),
    'contacts'       => $contacts,
]);
