<?php
// ─────────────────────────────────────────────────────
// 4ham mirror receiver — HMAC-SHA256 signature verification
//
// MUST stay byte-for-byte compatible with the sender:
//   backend/app/external_mirrors/http_client.py :: sign_payload()
//
// Signing string:
//     timestamp + "\n" + nonce + "\n" + raw_body
// where raw_body is the EXACT bytes received as the HTTP request body
// (do NOT re-encode the parsed JSON — whitespace differences would
//  invalidate the signature).
// ─────────────────────────────────────────────────────

declare(strict_types=1);

const FOURHAM_SIGNATURE_HEADER = 'X-4HAM-Signature';
const FOURHAM_TIMESTAMP_HEADER = 'X-4HAM-Timestamp';
const FOURHAM_NONCE_HEADER     = 'X-4HAM-Nonce';
const FOURHAM_VERSION_HEADER   = 'X-4HAM-Mirror-Version';
const FOURHAM_NAME_HEADER      = 'X-4HAM-Mirror-Name';

function fourham_header(string $name): string {
    // Apache/CGI normalises headers to HTTP_X_4HAM_…
    $key = 'HTTP_' . strtoupper(str_replace('-', '_', $name));
    return isset($_SERVER[$key]) ? trim((string)$_SERVER[$key]) : '';
}

function fourham_compute_signature(string $secret, string $rawBody, string $timestamp, string $nonce): string {
    $msg = $timestamp . "\n" . $nonce . "\n" . $rawBody;
    return hash_hmac('sha256', $msg, $secret);
}

/**
 * Verify the request signature.
 *
 * @return array{ok:bool, reason:string, mirror_name:string}
 */
function fourham_verify_request(array $cfg, string $rawBody): array {
    $mirrorName = fourham_header(FOURHAM_NAME_HEADER);
    $timestamp  = fourham_header(FOURHAM_TIMESTAMP_HEADER);
    $nonce      = fourham_header(FOURHAM_NONCE_HEADER);
    $signature  = fourham_header(FOURHAM_SIGNATURE_HEADER);

    if ($mirrorName === '' || $timestamp === '' || $nonce === '' || $signature === '') {
        return ['ok' => false, 'reason' => 'missing_headers', 'mirror_name' => $mirrorName];
    }

    $mirrors = $cfg['mirrors'] ?? [];
    $secret  = $mirrors[$mirrorName] ?? null;
    if (!is_string($secret) || $secret === '') {
        return ['ok' => false, 'reason' => 'unknown_mirror', 'mirror_name' => $mirrorName];
    }

    // Clock skew check (timestamp expected as ISO-8601 Zulu, e.g. 2026-04-11T12:34:56Z)
    $skew = (int)($cfg['max_clock_skew_seconds'] ?? 300);
    $ts   = strtotime($timestamp);
    if ($ts === false) {
        return ['ok' => false, 'reason' => 'malformed_timestamp', 'mirror_name' => $mirrorName];
    }
    if (abs(time() - $ts) > $skew) {
        return ['ok' => false, 'reason' => 'stale', 'mirror_name' => $mirrorName];
    }

    $expected = fourham_compute_signature($secret, $rawBody, $timestamp, $nonce);
    if (!hash_equals($expected, $signature)) {
        return ['ok' => false, 'reason' => 'bad_signature', 'mirror_name' => $mirrorName];
    }

    return ['ok' => true, 'reason' => 'ok', 'mirror_name' => $mirrorName];
}

function fourham_check_ip_allowlist(array $cfg): bool {
    $allow = $cfg['allowed_source_ips'] ?? [];
    if (!is_array($allow) || empty($allow)) return true;
    $ip = $_SERVER['REMOTE_ADDR'] ?? '';
    foreach ($allow as $entry) {
        if ($ip === $entry) return true;
    }
    return false;
}

/**
 * Replay protection. Returns true if nonce was unseen and is now recorded.
 * Returns false on duplicate (replay).
 */
function fourham_check_and_record_nonce(PDO $pdo, array $cfg, string $mirrorName, string $nonce): bool {
    $ttl = (int)($cfg['nonce_ttl_seconds'] ?? 900);
    // Opportunistic GC of expired nonces (cheap on indexed seen_at).
    try {
        $gc = $pdo->prepare('DELETE FROM mirror_seen_nonces WHERE seen_at < (NOW() - INTERVAL :ttl SECOND)');
        $gc->execute([':ttl' => $ttl]);
    } catch (Throwable $e) {
        // ignore GC failures
    }
    try {
        $stmt = $pdo->prepare('INSERT INTO mirror_seen_nonces (mirror_name, nonce, seen_at) VALUES (:m, :n, NOW())');
        $stmt->execute([':m' => $mirrorName, ':n' => $nonce]);
        return true;
    } catch (PDOException $e) {
        // 23000 = integrity constraint (duplicate nonce)
        if ($e->getCode() === '23000') return false;
        throw $e;
    }
}
