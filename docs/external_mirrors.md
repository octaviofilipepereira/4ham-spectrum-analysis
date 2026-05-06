<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0
-->

# External Mirrors

The **External Mirrors** module lets a 4ham Spectrum Analysis instance push a
copy of selected dashboard data (callsign + occupancy events **and** a
periodic snapshot of the read-only API endpoints used by the public
dashboard) to one or more remote PHP/MySQL hosts over HTTPS, in **push**
mode. This removes the need for inbound port-forwarding on the production
station and gives operators a fully public, read-only replica of the
Academic Analytics dashboard on shared hosting.

## Architecture

```
┌────────────────────────────┐                ┌────────────────────────────┐
│  4ham backend (FastAPI)    │   HTTPS POST   │  PHP receiver              │
│  external_mirrors/         │ ─────────────▶ │  external_academic_        │
│    pusher loop (15 s tick) │   signed JSON  │    analytics/              │
│    repository (SQLite)     │                │    ingest.php              │
│    HMAC client             │                │    MySQL (PDO_mysql)       │
│    snapshot bundler        │                │    api/*.php shims         │
└────────────────────────────┘                │    index.html dashboard    │
                                              └────────────────────────────┘
```

The pusher loop wakes every 15 s and, for each enabled mirror whose
`last_push_at + push_interval_seconds` has elapsed, builds a payload that
contains:

1. **Event batches** — new rows with `id > last_push_watermark` from the
   `callsign_events` / `occupancy_events` tables (`MAX_BATCH_SIZE=5000`).
2. **A `snapshots` bundle** — pre-computed JSON bodies for the read-only
   endpoints the public dashboard fetches (see [Snapshot bundle](#snapshot-bundle)
   below).

The payload is signed and POSTed to `endpoint_url`; on success
`last_push_at`, `last_push_status`, `last_push_watermark` and
`consecutive_failures` are updated. After 5 consecutive failures a mirror
is auto-disabled (`auto_disabled_at` is set); re-enabling it via the UI
clears the failure counter.

### Snapshot bundle

To keep the receiver completely independent of the home backend (i.e. no
inbound connectivity, no DNS, no opening ports), the **snapshot bundler**
(`backend/app/external_mirrors/snapshots.py`) calls the live FastAPI
route functions in-process and embeds their full JSON return values under
`payload["snapshots"]`. Each entry has the shape:

```json
"snapshots": {
  "version":            { "captured_at": "2026-04-23T20:44:28Z", "payload": { ... } },
  "scan/status":        { "captured_at": "...", "payload": { ... } },
  "settings":           { "captured_at": "...", "payload": { ... } },
  "map/ionospheric":    { "captured_at": "...", "payload": { ... } },
  "map/contacts":       { "captured_at": "...", "payload": { ... } },
  "analytics/academic": { "captured_at": "...", "payload": { ... } }
}
```

The receiver UPSERTs each entry into `mirror_endpoint_snapshots`
(primary key `(mirror_name, endpoint)`); the matching `api/<endpoint>.php`
shim simply `SELECT payload_json` and `echo`es the bytes verbatim — so
the public dashboard sees a JSON response that is byte-equivalent to the
live home backend, with at most one push interval (default 5 min) of
staleness.

The `settings` snapshot uses a **public projection** that strips secrets
and operator-private fields (`auth`, `aprs`, `lora_aprs`, `asr`,
`device_config`, `audio_config`); the `analytics/academic` snapshot caps
embedded `raw_events` at the most recent **1500 rows** (the dashboard
only renders a sliding window of recent decodes anyway). Builders that
fail are silently omitted from the bundle and an `_errors` map is
appended; partial failure never breaks the push of the event batch.

The exception is `api/events` on the receiver — there is no snapshot for
events; the PHP endpoint reads live from the mirrored
`mirror_callsign_events` / `mirror_occupancy_events` tables and returns
results immediately, so the dashboard's events table stays as fresh as
the events themselves (every push interval) without paying for snapshot
serialisation.

## Configuration storage

Mirrors are stored in two SQLite tables on the home backend (created
automatically by `storage.db._SCHEMA_SQL`) and three MySQL tables on the
receiver (created by `external_academic_analytics/schema.sql`).

**Home backend (SQLite):**

* `external_mirrors` — one row per mirror. The token is **bcrypt-hashed**
  at rest (rounds=12) and the plaintext is shown to the operator **only
  once** at creation and at rotation. The plaintext is also held in an
  in-process `TokenCache` so the pusher can sign requests; it does not
  survive a backend restart, so after a restart the operator must rotate
  the token to resume pushes (or the mirror is skipped, with a one-time
  audit entry `skipped_no_token`).
* `external_mirror_audit` — chronological audit log per mirror
  (`mirror_id`, `ts`,

**Receiver (MySQL):**

* `mirror_callsign_events` / `mirror_occupancy_events` — append-only
  copies of the source events (`INSERT IGNORE` on `(mirror_name, source_id)`).
* `mirror_endpoint_snapshots` — latest snapshot per
  `(mirror_name, endpoint)`; UPSERTed on every push.
* `mirror_push_audit` — one row per push attempt (HTTP code, batch
  counts, error_message).
* `mirror_seen_nonces` — replay-protection cache, GC'd on every
  request via `nonce_ttl`. `event`, `actor`, `details JSON`). Events include
  `created`, `updated`, `enabled`, `disabled`, `rotated`, `deleted`,
  `push_ok`, `push_failed`, `auto_disabled`, `test_push`,
  `skipped_no_token`.

## Admin REST API

All endpoints require Basic auth (same `BASIC_AUTH_USER`/`BASIC_AUTH_PASS`
used elsewhere). All paths are under `/api/admin/mirrors`:

| Method | Path                       | Purpose                                                |
| ------ | -------------------------- | ------------------------------------------------------ |
| GET    | `/`                        | List mirrors (`?include_disabled=true` to include off) |
| POST   | `/`                        | Create mirror — returns `{mirror, plaintext_token}`    |
| GET    | `/{id}`                    | Fetch one                                              |
| PATCH  | `/{id}`                    | Update editable fields (audit diff)                    |
| DELETE | `/{id}`                    | Remove + drop cached token                             |
| POST   | `/{id}/enable`             | Enable + clear failure counter                         |
| POST   | `/{id}/disable`            | Disable                                                |
| POST   | `/{id}/rotate-token`       | Regenerate token — returns new plaintext ONCE          |
| GET    | `/{id}/audit?limit=`       | Audit list (1..1000, default 100)                      |
| POST   | `/{id}/test`               | One-shot probe push (no watermark / failure update)    |

## Security model

* **Transport**: HTTPS with certificate verification on by default.
* **Signing**: HMAC-SHA256 over `timestamp + "\n" + nonce + "\n" + body`
  with the per-mirror plaintext token as the key. The body is the exact
  bytes encoded by `canonical_json` (sorted keys, no whitespace) so the
  receiver MUST hash `php://input` directly without re-encoding.
* **Headers** sent on every push:
  * `X-4HAM-Signature` — hex HMAC-SHA256.
  * `X-4HAM-Timestamp` — ISO-8601 Zulu (e.g. `2026-04-22T10:15:00Z`).
  * `X-4HAM-Nonce` — random per-request token.
  * `X-4HAM-Mirror-Name` — names the upstream mirror (used by receiver to
    look up the secret).
  * `X-4HAM-Mirror-Version` — sender app version.
* **Replay protection**: receiver records each `(mirror_name, nonce)` and
  rejects duplicates with HTTP 409 (`outcome=replay`).
* **Clock skew**: receiver rejects timestamps outside ±300 s
  (`outcome=stale`).
* **No retry on 4xx**: the sender retries only on 5xx / network /
  timeout, with exponential back-off (3 attempts max).
* **Auto-disable**: after 5 consecutive failures the mirror is disabled
  to prevent indefinite hammering of a broken receiver.

## Admin UI walkthrough

Open **Admin Config** in the dashboard. The **External Mirrors** section at
the bottom lists every mirror.

1. **Add mirror** — opens the form. Fill in:
   * *Name* — short, immutable identifier (sent in `X-4HAM-Mirror-Name`).
   * *Endpoint URL* — full URL to the receiver's `ingest.php`.
   * *Push interval (s)* — minimum 10 s.
   * *Data scopes* — at least one of `callsign_events`, `occupancy_events`.
   * *Retention (days)* — informational only at the moment (not enforced).
   * *Enabled* — start enabled or paused.

   On save you get a **one-time plaintext token**. Copy it now; it is
   never shown again. Paste it into the receiver's
   `config.local.php`'s `mirrors[<name>]` entry.

2. **Edit** — change endpoint, interval, scopes, retention or enabled
   state. The name cannot be changed after creation.

3. **Enable / Disable** — toggle the pusher for this mirror. Enabling
   also clears the consecutive-failure counter.

4. **Rotate token** — generates a new token (also shown ONCE). The old
   token stops working immediately. Update the receiver before the next
   push interval elapses.

5. **Test** — performs an immediate signed POST with an empty event
   batch. Returns the receiver's HTTP status, attempt count and any
   error. Does NOT update `last_push_at` or the failure counter.

6. **Audit** — opens the last 200 audit events for the mirror.

7. **Delete** — removes the mirror and drops its cached token.

## Receiver deployment

See `external_academic_analytics/README.md` for the full
deployment guide. Summary:

```bash
mysql -u admin -p fourham_mirror < schema.sql
cp config.local.php.example config.local.php
chmod 600 config.local.php
# edit config.local.php — set db credentials and mirrors[<name>] = '<plaintext token>'
```

Then click **Test** in the upstream Admin Config UI. A successful round
trip looks like:

```
Test push to "primary" OK (HTTP 200, attempts=1)
```

## Public dashboard mirror

Once snapshots start arriving (after the first successful push) the
receiver also serves a **fully public, read-only replica of the Academic
Analytics dashboard** at the receiver's web root, e.g.
`https://cs5arc.pt/external_academic_analytics/`. The dashboard is the
exact `frontend/4ham_academic_analytics.html` file shipped under the
receiver as `index.html`, plus its vendored JS/CSS assets and the i18n
JSON.

The dashboard fetches the same paths it would fetch on the home backend:

| Path                       | Source on receiver                                   |
| -------------------------- | ---------------------------------------------------- |
| `api/version`              | snapshot (`mirror_endpoint_snapshots`)               |
| `api/scan/status`          | snapshot                                             |
| `api/settings`             | snapshot (public projection)                         |
| `api/map/ionospheric`      | snapshot                                             |
| `api/map/contacts`         | snapshot                                             |
| `api/analytics/academic`   | snapshot (raw_events capped @ 1500)                  |
| `api/events`               | live SQL over `mirror_*_events`                      |
| `i18n/academic_analytics.json` | static file                                       |
| `lib/*.{js,json}`          | static (D3, TopoJSON, XLSX, countries-110m)          |
| `vendor/leaflet/*`         | static (Leaflet 1.x)                                 |

The Apache `api/.htaccess` rewrites extension-less requests
(`/api/scan/status`) onto the matching `.php` shim. The shim files are
~5 lines each — `require lib/snapshot.php` + `fourham_snapshot_serve(KEY)`.

**What the public mirror does NOT have:**
- No WebSocket / live IQ / live spectrum (push model only).
- No admin endpoints, no auth, no mutating endpoints.
- No raw decoded audio, no SDR control, no APRS-IS credentials.
- Snapshots have a maximum staleness of `push_interval_seconds` (default 300 s = 5 min).
