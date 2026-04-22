<?php
// ─────────────────────────────────────────────────────
// 4ham mirror receiver — config + PDO bootstrap
// ─────────────────────────────────────────────────────

declare(strict_types=1);

function fourham_load_config(): array {
    $local = __DIR__ . '/../config.local.php';
    $tmpl  = __DIR__ . '/../config.local.php.example';
    if (file_exists($local)) {
        $cfg = require $local;
    } elseif (file_exists($tmpl)) {
        // Allow boot but the receiver will refuse pushes since mirrors[] is empty.
        $cfg = require $tmpl;
    } else {
        throw new RuntimeException('Missing config.local.php');
    }
    if (!is_array($cfg)) {
        throw new RuntimeException('Invalid configuration (not an array)');
    }
    return $cfg;
}

function fourham_pdo(array $cfg): PDO {
    $dbCfg = $cfg['db'] ?? [];
    $dsn = sprintf(
        'mysql:host=%s;port=%d;dbname=%s;charset=%s',
        $dbCfg['host']   ?? '127.0.0.1',
        (int)($dbCfg['port'] ?? 3306),
        $dbCfg['dbname'] ?? '',
        $dbCfg['charset'] ?? 'utf8mb4'
    );
    $pdo = new PDO(
        $dsn,
        $dbCfg['user'] ?? '',
        $dbCfg['pass'] ?? '',
        [
            PDO::ATTR_ERRMODE            => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES   => false,
        ]
    );
    return $pdo;
}
