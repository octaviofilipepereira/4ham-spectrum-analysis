<!--
© 2026 Octávio Filipe Gonçalves
Callsign: CT7BFV
License: GNU AGPL-3.0
-->

# External Mirrors

The **External Mirrors** module lets a 4ham Spectrum Analysis instance push a
copy of selected dashboard data (currently `callsign_events` and
`occupancy_events`) to one or more remote PHP/MySQL hosts over HTTPS, in
**push** mode. This removes the need for inbound port-forwarding on the
production station and gives operators a public, read-only mirror of their
events on shared hosting.

## Architecture

```
┌────────────────────────────┐                ┌────────────────────────────┐
│  4ham backend (FastAPI)    │   HTTPS POST   │  PHP receiver              │
│  external_mirrors/         │ ─────────────▶ │  external_academic_        │
│    pusher loop (15 s tick) │   signed JSON  │    analytics_mirror/       │
│    repository (SQLite)     │                │    ingest.php              │
│    HMAC client             │                │    MySQL (PDO_mysql)       │
└────────────────────────────┘                └────────────────────────────┘
```

The pusher loop wakes every 15 s and, for each enabled mirror whose
`last_push_at + push_interval_seconds` has elapsed, builds a batch
(`payload.build_payload`) of new events with `id > last_push_watermark`,
signs it, POSTs it to the configured `endpoint_url`, and updates
`last_push_at`, `last_push_status`, `last_push_watermark` and
`consecutive_failures`. After 5 consecutive failures a mirror is
automatically disabled (`auto_disabled_at` is set); re-enabling it via
the UI clears the failure counter.

## Configuration storage

Mirrors are stored in two SQLite tables (created automatically by
`storage.db._SCHEMA_SQL`):

* `external_mirrors` — one row per mirror. The token is **bcrypt-hashed**
  at rest (rounds=12) and the plaintext is shown to the operator **only
  once** at creation and at rotation. The plaintext is also held in an
  in-process `TokenCache` so the pusher can sign requests; it does not
  survive a backend restart, so after a restart the operator must rotate
  the token to resume pushes (or the mirror is skipped, with a one-time
  audit entry `skipped_no_token`).
* `external_mirror_audit` — chronological audit log per mirror
  (`mirror_id`, `ts`, `event`, `actor`, `details JSON`). Events include
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
