<?php
// © 2026 Octávio Filipe Gonçalves
// Callsign: CT7BFV
// License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
//
// Helper for snapshot-backed shim endpoints. Returns the latest payload
// stored in mirror_endpoint_snapshots for the given endpoint key.
//
// On any failure (DB down, missing row, malformed JSON) responds with
// a JSON error and a 503/404 — the dashboard renders an empty state.

declare(strict_types=1);

require_once __DIR__ . '/db.php';

function fourham_snapshot_serve(string $endpointKey): void {
    header('Content-Type: application/json; charset=utf-8');
    header('X-Content-Type-Options: nosniff');
    header('Cache-Control: no-store');

    try {
        $cfg = fourham_load_config();
        $pdo = fourham_pdo($cfg);
    } catch (Throwable $e) {
        http_response_code(503);
        echo json_encode([
            'status' => 'error',
            'error' => 'config_or_db',
            'detail' => $e->getMessage(),
        ]);
        return;
    }

    // If a single mirror is the canonical source, allow override via config.
    $mirror = isset($_GET['mirror']) ? trim((string)$_GET['mirror']) : '';
    $sql = 'SELECT payload_json, captured_at, mirror_name
              FROM mirror_endpoint_snapshots
             WHERE endpoint = :e';
    $params = [':e' => $endpointKey];
    if ($mirror !== '') {
        $sql .= ' AND mirror_name = :m';
        $params[':m'] = $mirror;
    }
    $sql .= ' ORDER BY captured_at DESC, mirror_name ASC LIMIT 1';

    try {
        $stmt = $pdo->prepare($sql);
        $stmt->execute($params);
        $row = $stmt->fetch();
    } catch (Throwable $e) {
        http_response_code(503);
        echo json_encode([
            'status' => 'error',
            'error' => 'db_query',
            'detail' => $e->getMessage(),
        ]);
        return;
    }

    if (!$row || !isset($row['payload_json'])) {
        http_response_code(404);
        echo json_encode([
            'status' => 'error',
            'error' => 'snapshot_unavailable',
            'endpoint' => $endpointKey,
        ]);
        return;
    }

    // Forward upstream snapshot age as a debug header.
    if (!empty($row['captured_at'])) {
        header('X-4HAM-Snapshot-Captured-At: ' . $row['captured_at']);
    }
    if (!empty($row['mirror_name'])) {
        header('X-4HAM-Snapshot-Mirror: ' . $row['mirror_name']);
    }

    // Payload is already valid JSON produced by the backend — emit it raw.
    echo $row['payload_json'];
}
