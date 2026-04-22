<?php
// Read-only paginated query over mirrored events.
//
// Query string:
//   kind=callsign|occupancy   (default: callsign)
//   limit=1..1000             (default: 100)
//   since=ISO timestamp       (filter by source `timestamp` column)
//   mirror=name               (filter by mirror_name)
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

$kind   = ($_GET['kind'] ?? 'callsign') === 'occupancy' ? 'occupancy' : 'callsign';
$limit  = max(1, min(1000, (int)($_GET['limit'] ?? 100)));
$since  = isset($_GET['since']) ? trim((string)$_GET['since']) : '';
$mirror = isset($_GET['mirror']) ? trim((string)$_GET['mirror']) : '';

$table = $kind === 'occupancy' ? 'mirror_occupancy_events' : 'mirror_callsign_events';

$where = [];
$params = [];
if ($since !== '') {
    $where[] = 'timestamp >= :since';
    $params[':since'] = $since;
}
if ($mirror !== '') {
    $where[] = 'mirror_name = :mirror';
    $params[':mirror'] = $mirror;
}
$sql = "SELECT * FROM {$table}";
if (!empty($where)) $sql .= ' WHERE ' . implode(' AND ', $where);
$sql .= ' ORDER BY received_at DESC, pk DESC LIMIT ' . $limit;

$stmt = $pdo->prepare($sql);
$stmt->execute($params);
$rows = $stmt->fetchAll();

echo json_encode([
    'kind'  => $kind,
    'count' => count($rows),
    'limit' => $limit,
    'rows'  => $rows,
], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
