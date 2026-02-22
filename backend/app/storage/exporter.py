# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

import csv
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def _normalize_format(value):
    fmt = str(value or "csv").strip().lower()
    if fmt not in {"csv", "json"}:
        raise ValueError("Unsupported export format")
    return fmt


def _event_csv_columns():
    return [
        "type",
        "timestamp",
        "band",
        "frequency_hz",
        "mode",
        "callsign",
        "confidence",
        "snr_db",
        "power_dbm",
        "scan_id",
    ]


class ExportManager:
    def __init__(self, export_dir, db, max_files=50, max_age_days=7):
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self.db = db
        self.max_files = int(max_files)
        self.max_age_days = int(max_age_days)

    def create_export(self, events, format_name="csv"):
        fmt = _normalize_format(format_name)
        export_id = uuid4().hex[:16]
        created_at = _utcnow_iso()
        file_name = f"events_{export_id}.{fmt}"
        path = self.export_dir / file_name

        if fmt == "csv":
            self._write_csv(path, events)
        else:
            self._write_json(path, events)

        metadata = {
            "id": export_id,
            "format": fmt,
            "path": str(path),
            "created_at": created_at,
            "row_count": len(events),
            "size_bytes": int(path.stat().st_size),
        }
        self.db.add_export(metadata)
        self.apply_rotation()
        return metadata

    def list_exports(self, limit=100):
        return self.db.list_exports(limit=limit)

    def get_export(self, export_id):
        return self.db.get_export(export_id)

    def apply_rotation(self):
        exports = self.db.list_exports(limit=10000)
        now = datetime.now(timezone.utc)
        threshold = now - timedelta(days=max(0, self.max_age_days))

        removable = []
        for item in exports:
            created_raw = item.get("created_at")
            created_at = None
            if created_raw:
                try:
                    created_at = datetime.fromisoformat(str(created_raw))
                except ValueError:
                    created_at = None
            if created_at and created_at < threshold:
                removable.append(item)

        if self.max_files > 0 and len(exports) > self.max_files:
            overflow = exports[self.max_files:]
            removable.extend(overflow)

        seen_ids = set()
        for item in removable:
            export_id = item.get("id")
            if not export_id or export_id in seen_ids:
                continue
            seen_ids.add(export_id)
            path = item.get("path")
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
            self.db.delete_export(export_id)

    def _write_csv(self, path, events):
        columns = _event_csv_columns()
        with path.open("w", newline="", encoding="utf-8") as fp:
            writer = csv.DictWriter(fp, fieldnames=columns)
            writer.writeheader()
            for event in events:
                writer.writerow({key: event.get(key) for key in columns})

    def _write_json(self, path, events):
        with path.open("w", encoding="utf-8") as fp:
            json.dump(events, fp, ensure_ascii=False, indent=2)
