<?php
// © 2026 Octávio Filipe Gonçalves — License: AGPL-3.0
//
// Academic analytics shim. The home backend pre-computes 4 rolling
// windows (1h / 24h / 7d / 30d) plus a legacy generic snapshot. We pick
// the window whose duration best matches the requested ``end - start``
// and serve the matching pre-aggregated snapshot.
//
// Falls back to the legacy ``analytics/academic`` key (7d / hour) when
// no per-window snapshot has arrived yet (older home backend) or when
// start/end are missing/invalid.
declare(strict_types=1);
require_once __DIR__ . '/../../lib/snapshot.php';

function fourham_pick_academic_window(): string {
    $start = isset($_GET['start']) ? (string)$_GET['start'] : '';
    $end   = isset($_GET['end'])   ? (string)$_GET['end']   : '';
    if ($start === '' || $end === '') {
        return 'analytics/academic/24h';
    }
    $startTs = strtotime($start);
    $endTs   = strtotime($end);
    if ($startTs === false || $endTs === false || $endTs <= $startTs) {
        return 'analytics/academic/24h';
    }
    $deltaH = ($endTs - $startTs) / 3600.0;
    if ($deltaH <= 1.5) {
        return 'analytics/academic/1h';
    }
    if ($deltaH <= 36.0) {
        return 'analytics/academic/24h';
    }
    if ($deltaH <= 10 * 24.0) {
        return 'analytics/academic/7d';
    }
    return 'analytics/academic/30d';
}

fourham_snapshot_serve_keys([
    fourham_pick_academic_window(),
    'analytics/academic',
]);
