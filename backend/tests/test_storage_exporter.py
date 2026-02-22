# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)
# Last update: 2026-02-22 16:27:19 UTC

from pathlib import Path

from app.storage.db import Database
from app.storage.exporter import ExportManager


def _sample_events():
    return [
        {
            "type": "callsign",
            "timestamp": "2026-02-21T00:00:00+00:00",
            "band": "20m",
            "frequency_hz": 14074000,
            "mode": "FT8",
            "callsign": "CT1ABC",
            "confidence": 0.9,
            "snr_db": -10.0,
            "power_dbm": -95.0,
            "scan_id": 1,
        }
    ]


def test_export_manager_creates_csv_and_registers_metadata(tmp_path):
    db_path = tmp_path / "events.sqlite"
    db = Database(str(db_path))
    manager = ExportManager(export_dir=tmp_path / "exports", db=db, max_files=10, max_age_days=30)

    item = manager.create_export(_sample_events(), format_name="csv")

    assert item["format"] == "csv"
    assert item["row_count"] == 1
    assert Path(item["path"]).exists()
    from_db = db.get_export(item["id"])
    assert from_db is not None
    assert from_db["id"] == item["id"]


def test_export_manager_rotation_keeps_max_files(tmp_path):
    db_path = tmp_path / "events.sqlite"
    db = Database(str(db_path))
    manager = ExportManager(export_dir=tmp_path / "exports", db=db, max_files=1, max_age_days=30)

    first = manager.create_export(_sample_events(), format_name="json")
    second = manager.create_export(_sample_events(), format_name="json")

    assert db.get_export(first["id"]) is None
    assert db.get_export(second["id"]) is not None
    assert not Path(first["path"]).exists()
    assert Path(second["path"]).exists()
