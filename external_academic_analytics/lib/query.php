<?php
// © 2026 Octávio Filipe Gonçalves — License: AGPL-3.0
//
// Shared helpers for analytics/map endpoints that query the mirror DB
// directly instead of serving pre-computed snapshots.
declare(strict_types=1);

require_once __DIR__ . '/db.php';

function fourham_send_json(int $code, array $body): void {
    header('Content-Type: application/json; charset=utf-8');
    header('X-Content-Type-Options: nosniff');
    header('Cache-Control: no-store');
    http_response_code($code);
    echo json_encode($body, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
}

/**
 * Resolve [start,end] from query params. Falls back to last 24h.
 * Returns ISO8601 UTC strings for the BETWEEN clause (timestamp column
 * stores ISO strings in mirror_callsign_events / mirror_occupancy_events).
 *
 * @return array{0:string,1:string,2:DateTimeImmutable,3:DateTimeImmutable}
 */
function fourham_resolve_window(?string $startParam, ?string $endParam, int $defaultMinutes = 60): array {
    $tz = new DateTimeZone('UTC');
    $endParam = trim((string)($endParam ?? ''));
    $startParam = trim((string)($startParam ?? ''));
    try {
        $end = $endParam !== ''
            ? new DateTimeImmutable($endParam, $tz)
            : new DateTimeImmutable('now', $tz);
    } catch (Throwable $_e) {
        $end = new DateTimeImmutable('now', $tz);
    }
    $end = $end->setTimezone($tz);
    try {
        $start = $startParam !== ''
            ? new DateTimeImmutable($startParam, $tz)
            : $end->modify('-' . $defaultMinutes . ' minutes');
    } catch (Throwable $_e) {
        $start = $end->modify('-' . $defaultMinutes . ' minutes');
    }
    $start = $start->setTimezone($tz);
    if ($start >= $end) {
        $start = $end->modify('-' . $defaultMinutes . ' minutes');
    }
    // The DB stores ISO 8601 with sub-second precision and ``+00:00`` suffix.
    // Use a wide string range to match either style.
    $startIso = $start->format('Y-m-d\TH:i:s.u\Z');
    $endIso   = $end->format('Y-m-d\TH:i:s.u\Z');
    return [$startIso, $endIso, $start, $end];
}

/**
 * Pick a bucket size given a window (in seconds). Mirrors the frontend
 * ``selectBucket()`` heuristic so the dashboard always sees compatible
 * granularity even when ``bucket`` is not explicitly passed.
 */
function fourham_pick_bucket(?string $bucketParam, int $windowSeconds): string {
    $b = strtolower(trim((string)($bucketParam ?? '')));
    if (in_array($b, ['minute', 'hour', 'day'], true)) {
        return $b;
    }
    if ($windowSeconds <= 3 * 3600) {
        return 'minute';
    }
    if ($windowSeconds <= 4 * 86400) {
        return 'hour';
    }
    return 'day';
}

/**
 * Returns the MySQL DATE_FORMAT mask + alignment SQL fragment used to
 * truncate the ISO ``timestamp`` column (varchar) to the requested
 * bucket. We rely on STR_TO_DATE because the column is text.
 */
function fourham_bucket_sql(string $bucket): string {
    switch ($bucket) {
        case 'minute':
            return "DATE_FORMAT(STR_TO_DATE(SUBSTRING(timestamp, 1, 19), '%Y-%m-%dT%H:%i:%s'), '%Y-%m-%dT%H:%i:00+00:00')";
        case 'day':
            return "DATE_FORMAT(STR_TO_DATE(SUBSTRING(timestamp, 1, 19), '%Y-%m-%dT%H:%i:%s'), '%Y-%m-%dT00:00:00+00:00')";
        case 'hour':
        default:
            return "DATE_FORMAT(STR_TO_DATE(SUBSTRING(timestamp, 1, 19), '%Y-%m-%dT%H:%i:%s'), '%Y-%m-%dT%H:00:00+00:00')";
    }
}

/**
 * Normalise mode labels the same way ``backend/app/api/analytics.py``
 * does — SSB_TRAFFIC ⇒ SSB, CW_CANDIDATE/CW_TRAFFIC ⇒ CW. Implemented
 * in SQL as a CASE expression so we can ``GROUP BY`` it directly.
 */
function fourham_normalised_mode_sql(string $col = 'mode'): string {
    return "CASE
        WHEN UPPER($col) = 'SSB_TRAFFIC' THEN 'SSB'
        WHEN UPPER($col) IN ('CW_CANDIDATE','CW_TRAFFIC') THEN 'CW'
        ELSE UPPER($col)
    END";
}

/**
 * Pull the ``station`` block from the most recent ``settings`` snapshot
 * stored in ``mirror_endpoint_snapshots``. Returns sane fallbacks when
 * unavailable.
 *
 * @return array{callsign:string,locator:string,lat:float,lon:float}
 */
function fourham_station_from_snapshot(PDO $pdo): array {
    $fallback = ['callsign' => '', 'locator' => '', 'lat' => 39.5, 'lon' => -8.0];
    try {
        $row = $pdo->query(
            "SELECT payload_json FROM mirror_endpoint_snapshots
              WHERE endpoint = 'settings'
              ORDER BY captured_at DESC LIMIT 1"
        )->fetch();
    } catch (Throwable $_e) {
        return $fallback;
    }
    if (!$row || !isset($row['payload_json'])) return $fallback;
    $data = json_decode((string)$row['payload_json'], true);
    if (!is_array($data)) return $fallback;
    $st = $data['station'] ?? [];
    return [
        'callsign' => (string)($st['callsign'] ?? ''),
        'locator'  => (string)($st['locator']  ?? ''),
        'lat'      => isset($st['lat']) ? (float)$st['lat'] : $fallback['lat'],
        'lon'      => isset($st['lon']) ? (float)$st['lon'] : $fallback['lon'],
    ];
}

/**
 * Great-circle distance between two lat/lon points, kilometres.
 */
function fourham_haversine_km(float $lat1, float $lon1, float $lat2, float $lon2): float {
    $r = 6371.0;
    $toRad = M_PI / 180.0;
    $dLat = ($lat2 - $lat1) * $toRad;
    $dLon = ($lon2 - $lon1) * $toRad;
    $a = sin($dLat / 2) ** 2
       + cos($lat1 * $toRad) * cos($lat2 * $toRad) * sin($dLon / 2) ** 2;
    return 2 * $r * asin(min(1.0, sqrt($a)));
}

/**
 * Resolve a callsign to its DXCC entity using longest-prefix-match.
 *
 * Mirrors backend/app/dependencies/helpers.py::callsign_to_dxcc so that
 * the cs5arc external mirror enriches callsigns at query time using the
 * same DXCC index file (lib/dxcc_coords.json) instead of relying on
 * lat/lon stored on the row (which the home backend does not persist).
 *
 * @return array|null  Entity dict (country, lat, lon, continent, cq_zone, …)
 *                     or null if no prefix matches.
 */
function fourham_callsign_to_dxcc(string $callsign): ?array {
    static $index = null;
    if ($index === null) {
        $path = __DIR__ . '/dxcc_coords.json';
        $index = [];
        if (is_readable($path)) {
            $raw = file_get_contents($path);
            $data = $raw !== false ? json_decode($raw, true) : null;
            if (is_array($data) && isset($data['index']) && is_array($data['index'])) {
                $index = $data['index'];
            }
        }
    }
    if ($index === [] || $callsign === '') {
        return null;
    }
    $cs = strtoupper(trim($callsign));
    // Strip portable suffixes (/P /M /MM /QRP /QRPP /A /B)
    $cs = preg_replace('#/(P|M|MM|QRP|QRPP|A|B)$#', '', $cs);
    $len = min(strlen($cs), 5);
    for ($l = $len; $l > 0; $l--) {
        $candidate = substr($cs, 0, $l);
        if (isset($index[$candidate])) {
            return $index[$candidate];
        }
    }
    return null;
}
