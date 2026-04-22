<?php
// ─────────────────────────────────────────────────────
// 4ham Spectrum Analysis — Mirror ingest endpoint
//
// Accepts POST application/json signed with HMAC-SHA256 from one of the
// configured upstream mirrors. Payload schema is produced by:
//   backend/app/external_mirrors/payload.py :: build_payload()
//
// Idempotent: rows are inserted with INSERT IGNORE keyed by
// (mirror_name, source_id), so duplicate retries do not double-count.
// ─────────────────────────────────────────────────────

declare(strict_types=1);

require_once __DIR__ . '/lib/db.php';
require_once __DIR__ . '/lib/auth.php';

header('Content-Type: application/json; charset=utf-8');
header('X-Content-Type-Options: nosniff');
header('Cache-Control: no-store');

function fourham_respond(int $status, array $body): void {
    http_response_code($status);
    echo json_encode($body, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function fourham_audit_row(?PDO $pdo, array $row): void {
    if (!$pdo) return;
    try {
        $stmt = $pdo->prepare(
            'INSERT INTO mirror_push_audit
              (ts, mirror_name, remote_ip, outcome, http_status, callsign_count, occupancy_count,
               callsign_inserted, occupancy_inserted, previous_watermark, new_watermark,
               upstream_app_version, error_message)
             VALUES
              (NOW(), :mirror, :ip, :outcome, :http, :cc, :oc, :ci, :oi, :pw, :nw, :ver, :err)'
        );
        $stmt->execute([
            ':mirror'  => $row['mirror_name']         ?? null,
            ':ip'      => $_SERVER['REMOTE_ADDR']     ?? null,
            ':outcome' => $row['outcome']             ?? 'unknown',
            ':http'    => $row['http_status']         ?? null,
            ':cc'      => $row['callsign_count']      ?? null,
            ':oc'      => $row['occupancy_count']     ?? null,
            ':ci'      => $row['callsign_inserted']   ?? null,
            ':oi'      => $row['occupancy_inserted']  ?? null,
            ':pw'      => $row['previous_watermark']  ?? null,
            ':nw'      => $row['new_watermark']       ?? null,
            ':ver'     => $row['upstream_app_version']?? null,
            ':err'     => $row['error_message']       ?? null,
        ]);
    } catch (Throwable $e) {
        error_log('[4ham-mirror] audit insert failed: ' . $e->getMessage());
    }
}

try {
    $cfg = fourham_load_config();
} catch (Throwable $e) {
    fourham_respond(500, ['error' => 'config_error', 'detail' => $e->getMessage()]);
}

@set_time_limit((int)($cfg['request_time_limit'] ?? 30));

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    fourham_respond(405, ['error' => 'method_not_allowed']);
}
if (!fourham_check_ip_allowlist($cfg)) {
    fourham_respond(403, ['error' => 'forbidden_ip']);
}

$rawBody = file_get_contents('php://input');
if ($rawBody === false || $rawBody === '') {
    fourham_respond(400, ['error' => 'empty_body']);
}

// Connect AFTER cheap validations so we don't pay a DB round-trip on bad pings.
try {
    $pdo = fourham_pdo($cfg);
} catch (Throwable $e) {
    fourham_respond(500, ['error' => 'db_unavailable', 'detail' => $e->getMessage()]);
}

$verify = fourham_verify_request($cfg, $rawBody);
if (!$verify['ok']) {
    fourham_audit_row($pdo, [
        'mirror_name' => $verify['mirror_name'] ?: null,
        'outcome'     => $verify['reason'],
        'http_status' => 401,
        'error_message' => 'verify_failed',
    ]);
    fourham_respond(401, ['error' => $verify['reason']]);
}

$mirrorName = $verify['mirror_name'];
$nonce      = fourham_header(FOURHAM_NONCE_HEADER);
$ver        = fourham_header(FOURHAM_VERSION_HEADER);

if (!fourham_check_and_record_nonce($pdo, $cfg, $mirrorName, $nonce)) {
    fourham_audit_row($pdo, [
        'mirror_name' => $mirrorName,
        'outcome'     => 'replay',
        'http_status' => 409,
        'upstream_app_version' => $ver ?: null,
    ]);
    fourham_respond(409, ['error' => 'replay']);
}

$payload = json_decode($rawBody, true);
if (!is_array($payload)) {
    fourham_audit_row($pdo, [
        'mirror_name' => $mirrorName,
        'outcome'     => 'malformed',
        'http_status' => 400,
    ]);
    fourham_respond(400, ['error' => 'malformed_json']);
}

$meta       = is_array($payload['meta'] ?? null) ? $payload['meta'] : [];
$events     = is_array($payload['events'] ?? null) ? $payload['events'] : [];
$callsign   = is_array($events['callsign'] ?? null)  ? $events['callsign']  : [];
$occupancy  = is_array($events['occupancy'] ?? null) ? $events['occupancy'] : [];

$insertedCallsign = 0;
$insertedOccupancy = 0;

$callsignCols = [
    'scan_id', 'timestamp', 'band', 'frequency_hz', 'mode', 'callsign',
    'snr_db', 'crest_db', 'df_hz', 'confidence', 'raw', 'grid', 'report',
    'time_s', 'dt_s', 'is_new', 'path', 'payload', 'lat', 'lon', 'msg',
    'source', 'device',
];
$occupancyCols = [
    'scan_id', 'timestamp', 'band', 'frequency_hz', 'bandwidth_hz',
    'power_dbm', 'snr_db', 'crest_db', 'threshold_dbm', 'occupied',
    'mode', 'confidence', 'device',
];

try {
    $pdo->beginTransaction();

    if (!empty($callsign)) {
        $cols = array_merge(['mirror_name', 'source_id', 'received_at'], $callsignCols);
        $placeholders = ':' . implode(', :', $cols);
        $sql = 'INSERT IGNORE INTO mirror_callsign_events (' . implode(',', $cols) . ') VALUES (' . $placeholders . ')';
        $stmt = $pdo->prepare($sql);
        foreach ($callsign as $ev) {
            if (!is_array($ev) || !isset($ev['id'])) continue;
            $params = [
                ':mirror_name' => $mirrorName,
                ':source_id'   => (int)$ev['id'],
                ':received_at' => date('Y-m-d H:i:s'),
            ];
            foreach ($callsignCols as $col) {
                $params[':' . $col] = $ev[$col] ?? null;
            }
            $stmt->execute($params);
            $insertedCallsign += $stmt->rowCount();
        }
    }

    if (!empty($occupancy)) {
        $cols = array_merge(['mirror_name', 'source_id', 'received_at'], $occupancyCols);
        $placeholders = ':' . implode(', :', $cols);
        $sql = 'INSERT IGNORE INTO mirror_occupancy_events (' . implode(',', $cols) . ') VALUES (' . $placeholders . ')';
        $stmt = $pdo->prepare($sql);
        foreach ($occupancy as $ev) {
            if (!is_array($ev) || !isset($ev['id'])) continue;
            $params = [
                ':mirror_name' => $mirrorName,
                ':source_id'   => (int)$ev['id'],
                ':received_at' => date('Y-m-d H:i:s'),
            ];
            foreach ($occupancyCols as $col) {
                $params[':' . $col] = $ev[$col] ?? null;
            }
            $stmt->execute($params);
            $insertedOccupancy += $stmt->rowCount();
        }
    }

    $pdo->commit();
} catch (Throwable $e) {
    if ($pdo->inTransaction()) $pdo->rollBack();
    fourham_audit_row($pdo, [
        'mirror_name'    => $mirrorName,
        'outcome'        => 'db_error',
        'http_status'    => 500,
        'callsign_count' => count($callsign),
        'occupancy_count'=> count($occupancy),
        'error_message'  => substr($e->getMessage(), 0, 500),
        'upstream_app_version' => $ver ?: null,
    ]);
    fourham_respond(500, ['error' => 'db_error']);
}

fourham_audit_row($pdo, [
    'mirror_name'         => $mirrorName,
    'outcome'             => 'ok',
    'http_status'         => 200,
    'callsign_count'      => count($callsign),
    'occupancy_count'     => count($occupancy),
    'callsign_inserted'   => $insertedCallsign,
    'occupancy_inserted'  => $insertedOccupancy,
    'previous_watermark'  => isset($meta['previous_watermark']) ? (int)$meta['previous_watermark'] : null,
    'new_watermark'       => isset($meta['new_watermark'])      ? (int)$meta['new_watermark']      : null,
    'upstream_app_version'=> $meta['app_version'] ?? ($ver ?: null),
]);

fourham_respond(200, [
    'ok' => true,
    'mirror_name' => $mirrorName,
    'received' => [
        'callsign'  => count($callsign),
        'occupancy' => count($occupancy),
    ],
    'inserted' => [
        'callsign'  => $insertedCallsign,
        'occupancy' => $insertedOccupancy,
    ],
    'new_watermark' => $meta['new_watermark'] ?? null,
]);
