# © 2026 Octávio Filipe Gonçalves
# Callsign: CT7BFV
# License: GNU AGPL-3.0 (https://www.gnu.org/licenses/agpl-3.0.html)

import sqlite3

from app.storage import db as storage_db_module
from app.storage.db import Database


class _DeleteLimitProxy:
    def __init__(self, conn, max_variables):
        self._conn = conn
        self._max_variables = max_variables

    def execute(self, sql, parameters=()):
        if sql.startswith("DELETE FROM occupancy_events WHERE id IN") or sql.startswith(
            "DELETE FROM callsign_events WHERE id IN"
        ):
            if sql.count("?") > self._max_variables:
                raise sqlite3.OperationalError("too many SQL variables")
        return self._conn.execute(sql, parameters)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _seed_occupancy_events(db, total):
    rows = [
        (
            None,
            f"2026-05-01T00:00:{index % 60:02d}+00:00",
            "20m",
            14074000,
            2500,
            -95.0,
            -12.0,
            None,
            None,
            1,
            "FT8",
            0.9,
            "rtlsdr",
        )
        for index in range(total)
    ]
    db.conn.executemany(
        """
        INSERT INTO occupancy_events(
            scan_id, timestamp, band, frequency_hz, bandwidth_hz, power_dbm,
            snr_db, crest_db, threshold_dbm, occupied, mode, confidence, device
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    db.conn.commit()


def test_delete_events_by_ids_batches_sqlite_variable_limit(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "events.sqlite"))
    _seed_occupancy_events(db, total=7)

    occ_ids = [row[0] for row in db.conn.execute("SELECT id FROM occupancy_events ORDER BY id").fetchall()]
    monkeypatch.setattr(storage_db_module, "_SQLITE_DELETE_BATCH_SIZE", 3)
    db.conn = _DeleteLimitProxy(db.conn, max_variables=3)

    deleted = db.delete_events_by_ids(occ_ids, [])

    assert deleted == 7
    remaining = db.conn.execute("SELECT COUNT(*) FROM occupancy_events").fetchone()[0]
    assert remaining == 0
