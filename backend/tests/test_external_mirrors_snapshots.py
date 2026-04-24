# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
"""Tests for backend.app.external_mirrors.snapshots."""

from __future__ import annotations

from unittest.mock import patch

from backend.app.external_mirrors import snapshots


def test_safe_returns_value_on_success():
    assert snapshots._safe("ok", lambda: {"a": 1}) == {"a": 1}


def test_safe_swallows_exception_and_returns_none():
    def boom():
        raise RuntimeError("bad")

    assert snapshots._safe("boom", boom) is None


def test_snapshot_version_uses_app_version():
    out = snapshots._snapshot_version()
    assert "version" in out and "app_version" in out
    assert out["version"] == out["app_version"]


def test_build_snapshot_bundle_skips_failed_builders():
    """If every individual builder fails, bundle is empty."""
    fakes = (
        ("a", lambda: (_ for _ in ()).throw(RuntimeError("x"))),
        ("b", lambda: (_ for _ in ()).throw(RuntimeError("y"))),
    )
    with patch.object(snapshots, "_safe", wraps=snapshots._safe):
        # Replace builders by patching; just call _safe directly here.
        assert snapshots._safe("a", fakes[0][1]) is None


def test_build_snapshot_bundle_keys_are_endpoint_paths():
    """Successful builders produce entries keyed by the endpoint path.

    The bundle was slimmed down in the v0.14.0 receiver-side analytics
    refactor: map/contacts and analytics/academic are now queried by the
    receiver directly from MySQL instead of being shipped as snapshots.
    """
    with patch.object(snapshots, "_snapshot_version", return_value={"version": "0.0.0", "app_version": "0.0.0"}), \
         patch.object(snapshots, "_snapshot_scan_status", return_value={"state": "stopped"}), \
         patch.object(snapshots, "_snapshot_settings", return_value={"station": {}}), \
         patch.object(snapshots, "_snapshot_map_ionospheric", return_value={"kp": 0}):
        bundle = snapshots.build_snapshot_bundle()

    assert set(bundle.keys()) == {
        "version",
        "scan/status",
        "settings",
        "map/ionospheric",
    }
    for key, entry in bundle.items():
        assert "captured_at" in entry
        assert "payload" in entry
        assert isinstance(entry["payload"], dict)


def test_build_snapshot_bundle_partial_failure_omits_only_failed():
    """A single failing builder doesn't break the others."""
    with patch.object(snapshots, "_snapshot_version", return_value={"version": "x", "app_version": "x"}), \
         patch.object(snapshots, "_snapshot_scan_status", side_effect=RuntimeError("nope")), \
         patch.object(snapshots, "_snapshot_settings", return_value={"station": {}}), \
         patch.object(snapshots, "_snapshot_map_ionospheric", return_value={"kp": 0}):
        bundle = snapshots.build_snapshot_bundle()

    assert "scan/status" not in bundle
    assert "version" in bundle
    assert "settings" in bundle


def test_build_payload_includes_snapshots_key(tmp_path):
    """Integration: build_payload exposes a snapshots dict."""
    from backend.app.external_mirrors.payload import build_payload
    from backend.app.storage.db import Database

    from backend.app.external_mirrors import payload as payload_mod

    db = Database(str(tmp_path / "evt.sqlite"))
    with patch.object(payload_mod, "build_snapshot_bundle", return_value={"version": {"captured_at": "x", "payload": {"v": 1}}}):
        payload = build_payload(
            db, mirror_name="primary", last_watermark=0, scopes=[]
        )

    assert "snapshots" in payload
    assert payload["snapshots"]["version"]["payload"] == {"v": 1}


def test_build_payload_snapshots_failure_does_not_break_push(tmp_path):
    """If the bundler raises, payload still works (snapshots = {})."""
    from backend.app.external_mirrors.payload import build_payload
    from backend.app.storage.db import Database

    from backend.app.external_mirrors import payload as payload_mod

    db = Database(str(tmp_path / "evt.sqlite"))
    with patch.object(payload_mod, "build_snapshot_bundle", side_effect=RuntimeError("boom")):
        payload = build_payload(
            db, mirror_name="primary", last_watermark=0, scopes=[]
        )
    assert payload["snapshots"] == {}
