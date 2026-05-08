#!/usr/bin/env bash
# refresh_satellite_snapshots.sh
# Refreshes data/satellite/ offline snapshots (TLEs, catalog, pyorbital wheel).
# Run from the project root before each official release.
# © 2026 Octávio Filipe Gonçalves / CT7BFV — AGPL-3.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$PROJECT_ROOT/data/satellite"
WHEELS_DIR="$DATA_DIR/wheels"

echo "=== 4ham Satellite Snapshot Refresh ==="
echo "Project root : $PROJECT_ROOT"
echo "Data dir     : $DATA_DIR"
echo ""

mkdir -p "$DATA_DIR" "$WHEELS_DIR"

# ── 1. Amateur TLEs from Celestrak ────────────────────────────────────────────
echo "[1/3] Fetching amateur TLEs from Celestrak..."
TLE_URL="https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=TLE"
TMP_TLE="$DATA_DIR/tle_amateur.txt.tmp"

if curl -sSf --max-time 30 "$TLE_URL" -o "$TMP_TLE"; then
    LINE_COUNT=$(wc -l < "$TMP_TLE")
    echo "      Downloaded $LINE_COUNT lines."
    if [[ $LINE_COUNT -lt 3 ]]; then
        echo "      ERROR: TLE file too small — aborting to protect existing snapshot."
        rm -f "$TMP_TLE"
        exit 1
    fi
    # Prepend header comment
    {
        echo "# Amateur satellite TLE snapshot"
        echo "# Source: Celestrak ($TLE_URL)"
        echo "# Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
        cat "$TMP_TLE"
    } > "$DATA_DIR/tle_amateur.txt"
    rm -f "$TMP_TLE"
    echo "      Saved to data/satellite/tle_amateur.txt"
else
    echo "      WARNING: Celestrak unreachable — keeping existing TLE snapshot."
fi

# ── 2. SatNOGS catalog (amateur + educational) ────────────────────────────────
echo "[2/3] Fetching SatNOGS DB catalog..."
SATNOGS_URL="https://db.satnogs.org/api/satellites/?format=json&status=alive"
TMP_CAT="$DATA_DIR/catalog.json.tmp"
PYEXEC="${PYTHON:-python3}"

if curl -sSf --max-time 60 "$SATNOGS_URL" -o "$TMP_CAT"; then
    # Filter to amateur/educational only using Python
    $PYEXEC - "$TMP_CAT" "$DATA_DIR/catalog.json" <<'EOF'
import json, sys, datetime

src_path, dst_path = sys.argv[1], sys.argv[2]
with open(src_path) as f:
    raw = json.load(f)

ALLOWED_SERVICES = {"amateur", "educational"}
filtered = [
    s for s in raw
    if (s.get("service", "") or "").lower() in ALLOWED_SERVICES
]

out = {
    "_meta": {
        "source": "satnogs_db",
        "generated_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "filter": "service in [amateur, educational]",
        "count": len(filtered),
    },
    "satellites": filtered,
}
with open(dst_path, "w") as f:
    json.dump(out, f, separators=(",", ":"))
print(f"      Filtered {len(raw)} → {len(filtered)} satellites saved.")
EOF
    rm -f "$TMP_CAT"
else
    echo "      WARNING: SatNOGS unreachable — keeping existing catalog snapshot."
fi

# ── 3. pyorbital wheel (offline install) ─────────────────────────────────────
echo "[3/3] Downloading pyorbital wheel for offline install..."
PYEXEC="${PYTHON:-python3}"

if $PYEXEC -m pip download pyorbital --no-deps -d "$WHEELS_DIR" -q 2>/dev/null; then
    echo "      Saved to data/satellite/wheels/"
    ls "$WHEELS_DIR"
else
    echo "      WARNING: pip download failed — wheels directory unchanged."
fi

# ── Bump schema_version ──────────────────────────────────────────────────────
echo "1" > "$DATA_DIR/schema_version.txt"
echo ""
echo "=== Done. Snapshots updated in data/satellite/ ==="
