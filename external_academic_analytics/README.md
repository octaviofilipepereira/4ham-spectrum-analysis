<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
-->

# 4ham Spectrum Analysis — External Mirror Receiver

PHP/MySQL receiver counterpart to the in-app **External Mirrors** push
module (`backend/app/external_mirrors/`). Designed to run on shared
hosting where only `PDO_mysql` is available (e.g. cs5arc.pt, PHP 7.4+).

## Endpoints

### Ingest + admin

| Path          | Method | Auth                                  | Purpose                                     |
| ------------- | ------ | ------------------------------------- | ------------------------------------------- |
| `ingest.php`  | POST   | HMAC-SHA256 (`X-4HAM-Signature` etc.) | Receive a signed batch of events + snapshot bundle |
| `status.php`  | GET    | none (public read-only summary)       | Per-mirror stats + last 50 push outcomes    |
| `events.php`  | GET    | none (public read-only)               | Paginated query over mirrored event tables  |
| `version.php` | GET    | none                                  | Receiver build/PHP/PDO info                 |

### Public dashboard (snapshot replicas of the home backend)

The receiver also exposes the read-only API surface used by the home
station's Academic Analytics dashboard, served from the
`mirror_endpoint_snapshots` table that `ingest.php` UPSERTs on every
push. The shims live under `api/` and respond with JSON that is
byte-equivalent to what the home backend would serve, with at most
one push interval (default 5 min) of staleness.

| Path                            | Source                                                  |
| ------------------------------- | ------------------------------------------------------- |
| `api/version`                   | snapshot                                                |
| `api/scan/status`               | snapshot                                                |
| `api/settings`                  | snapshot (public projection — no auth/aprs/asr/device)  |
| `api/map/ionospheric`           | snapshot                                                |
| `api/map/contacts`              | snapshot                                                |
| `api/analytics/academic`        | snapshot (raw_events capped @ 1500)                     |
| `api/events`                    | live SQL over `mirror_*_events`                         |
| `index.html`                    | dashboard (copy of `frontend/4ham_academic_analytics.html`) |
| `i18n/academic_analytics.json`  | static                                                  |
| `lib/*.{js,json}`               | static (D3, TopoJSON, XLSX, countries-110m)             |
| `vendor/leaflet/*`              | static (Leaflet 1.x)                                    |

Each shim is a 5-line PHP file that calls
`fourham_snapshot_serve(<endpoint_key>)` from `lib/snapshot.php`.
Optional `?mirror=<name>` query parameter selects a specific mirror when
multiple home stations push to the same receiver.

`status.php`, `events.php` and the `api/*` shims are all read-only; if
you want them private, front them with HTTP Basic auth at the web-server
level.

## Deployment

The receiver bundle is the entire contents of this folder. Deploy it to
a shared-hosting webroot via `rsync` or your FTP client of choice.

1. **Database** — create a MySQL database and user, then load the schema:

   ```bash
   mysql -u admin -p fourham_mirror < schema.sql
   ```

   Re-running the schema is idempotent (`CREATE TABLE IF NOT EXISTS`),
   so it is safe to re-apply after upgrades that add new tables (e.g.
   `mirror_endpoint_snapshots`).

2. **Upload** the contents of this folder to the public web root, e.g.
   `https://cs5arc.pt/external_academic_analytics/`. Recommended:

   ```bash
   rsync -avz \
     --exclude=config.local.php \
     --exclude=logs/ \
     --exclude=.gitignore \
     --exclude=config.local.php.example \
     external_academic_analytics/ \
     youruser@yourhost:public_html/external_academic_analytics/
   ```

   The `--exclude=config.local.php` is critical: it preserves the
   credentials file you wrote in step 3. Make sure `lib/` and
   `config.local.php` are NOT directly fetchable (the bundled
   `.htaccess` files take care of that on Apache).

3. **Configure** — copy the template and edit:

   ```bash
   cp config.local.php.example config.local.php
   chmod 600 config.local.php
   ```

   Set:
   * `db.*` — MySQL credentials.
   * `mirrors[<mirror_name>] = '<plaintext token>'` — the **plaintext
     token** that the upstream Admin Config UI showed you ONCE when you
     created/rotated the mirror. The mirror name MUST match exactly the
     `name` field configured upstream (it is sent as `X-4HAM-Mirror-Name`).
   * `max_clock_skew_seconds` — default 300; must cover the worst-case
     clock drift between sender and receiver.
   * `allowed_source_ips` — optional source allowlist. Accepts exact IPv4/IPv6, CIDR blocks, or hostnames/FQDNs (resolved per-request, supports DDNS).

4. **Test** the upstream side: from the Admin Config modal of the
   sender, open the mirror row and click **Test**. You should see HTTP
   200 with `received={callsign:0,occupancy:0,...}`.

## Security model

* Every request is verified with HMAC-SHA256 over
  `timestamp + "\n" + nonce + "\n" + raw_body` using the per-mirror
  shared secret. The exact request bytes are used (no JSON
  re-encoding) so PHP must read `php://input` once and never modify it.
* Requests outside the allowed clock-skew window are rejected with 401
  and recorded with `outcome=stale`.
* Each `(mirror_name, nonce)` is recorded in `mirror_seen_nonces`;
  duplicates return HTTP 409 (`outcome=replay`). Old nonces are GC'd
  on every request via `seen_at < NOW() - INTERVAL nonce_ttl SECOND`.
* Optional source allowlist via `allowed_source_ips` (IPs, CIDRs, or hostnames).
* Inserts use `INSERT IGNORE` keyed by `(mirror_name, source_id)` so
  retries are idempotent.

## Operational notes

* Audit rows are written to `mirror_push_audit` for every attempt,
  successful or not. Use `status.php` for a quick health check.
* Clean up old audit/event data with your own cron — retention is
  intentionally NOT enforced server-side here.
* The receiver is **append-only** for events; it never updates or
  deletes mirrored rows.
* `mirror_endpoint_snapshots` is **upsert-on-key** (`(mirror_name, endpoint)`):
  every push overwrites the previous snapshot for that endpoint, so the
  table never grows beyond `N_mirrors × N_endpoints` rows.
* Apache's `mod_headers` is **not** required by the bundled `.htaccess`
  files; if missing, the `Header set X-Content-Type-Options` directive
  is silently skipped (it is wrapped in `<IfModule mod_headers.c>`).
* PHP's `post_max_size` must accommodate the snapshot bundle. With the
  built-in 1500-row cap on `analytics/academic.raw_events`, payloads
  stay well under the conservative 8 MB shared-hosting default; if you
  raise the snapshot raw_events cap upstream, raise `post_max_size`
  accordingly.
