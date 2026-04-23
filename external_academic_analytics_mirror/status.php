<?php
// © 2026 Octávio Filipe Gonçalves
// Callsign: CT7BFV
// License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

// ─────────────────────────────────────────────────────
//  4ham Spectrum Analysis — External Mirror Receiver
//  status.php — read-only health/summary endpoint
//  Returns per-mirror stats + last 50 push outcomes (public).
// ─────────────────────────────────────────────────────
declare(strict_types=1);

require_once __DIR__ . '/lib/db.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

try {
    $cfg = fourham_load_config();
    $pdo = fourham_pdo($cfg);
} catch (Throwable $e) {
    http_response_code(500);
    echo json_encode(['error' => 'config_or_db', 'detail' => $e->getMessage()]);
    exit;
}

$mirrors = [];
$rs = $pdo->query(
    'SELECT mirror_name,
            MAX(ts) AS last_attempt,
            SUM(outcome = "ok") AS ok_count,
            SUM(outcome <> "ok") AS error_count,
            MAX(new_watermark) AS max_watermark
       FROM mirror_push_audit
      GROUP BY mirror_name
      ORDER BY mirror_name'
);
foreach ($rs as $row) $mirrors[] = $row;

$counts = [
    'callsign_total'  => (int)$pdo->query('SELECT COUNT(*) FROM mirror_callsign_events')->fetchColumn(),
    'occupancy_total' => (int)$pdo->query('SELECT COUNT(*) FROM mirror_occupancy_events')->fetchColumn(),
];

$recent = [];
$rs = $pdo->query(
    'SELECT ts, mirror_name, outcome, http_status,
            callsign_count, occupancy_count,
            callsign_inserted, occupancy_inserted,
            previous_watermark, new_watermark,
            upstream_app_version, error_message
       FROM mirror_push_audit
      ORDER BY ts DESC
      LIMIT 50'
);
foreach ($rs as $row) $recent[] = $row;

echo json_encode([
    'mirrors' => $mirrors,
    'counts'  => $counts,
    'recent_pushes' => $recent,
], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
