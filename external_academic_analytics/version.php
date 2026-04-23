<?php
// © 2026 Octávio Filipe Gonçalves
// Callsign: CT7BFV
// License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

// ─────────────────────────────────────────────────────
//  4ham Spectrum Analysis — External Mirror Receiver
//  version.php — build/PHP/PDO info
// ─────────────────────────────────────────────────────
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

echo json_encode([
    'name'    => '4ham-spectrum-analysis-mirror',
    'role'    => 'receiver',
    'version' => '0.14.0',
    'php'     => PHP_VERSION,
    'pdo_drivers' => PDO::getAvailableDrivers(),
]);
