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

/**
 * Try a list of endpoint keys in order and serve the first one that has
 * a stored snapshot. Used by the academic shim which prefers a
 * window-specific snapshot (e.g. ``analytics/academic/1h``) but falls
 * back to the legacy generic key when older home backends only push
 * the single 7d snapshot.
 */
function fourham_snapshot_serve_keys(array $endpointKeys): void {
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

    $mirror = isset($_GET['mirror']) ? trim((string)$_GET['mirror']) : '';
    $row = null;
    $usedKey = '';
    foreach ($endpointKeys as $endpointKey) {
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
            $candidate = $stmt->fetch();
        } catch (Throwable $e) {
            http_response_code(503);
            echo json_encode([
                'status' => 'error',
                'error' => 'db_query',
                'detail' => $e->getMessage(),
            ]);
            return;
        }
        if ($candidate && isset($candidate['payload_json'])) {
            $row = $candidate;
            $usedKey = $endpointKey;
            break;
        }
    }

    if (!$row) {
        http_response_code(404);
        echo json_encode([
            'status' => 'error',
            'error' => 'snapshot_unavailable',
            'endpoint' => $endpointKeys[0] ?? '',
        ]);
        return;
    }

    if (!empty($row['captured_at'])) {
        header('X-4HAM-Snapshot-Captured-At: ' . $row['captured_at']);
    }
    if (!empty($row['mirror_name'])) {
        header('X-4HAM-Snapshot-Mirror: ' . $row['mirror_name']);
    }
    if ($usedKey !== '') {
        header('X-4HAM-Snapshot-Endpoint: ' . $usedKey);
    }

    echo $row['payload_json'];
}

function fourham_snapshot_serve(string $endpointKey): void {
    fourham_snapshot_serve_keys([$endpointKey]);
}
