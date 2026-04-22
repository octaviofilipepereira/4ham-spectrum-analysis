<?php
// Receiver build/version info.
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
