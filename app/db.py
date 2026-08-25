"""SQLite connection + schema. No ORM ceremony."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "top100.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS match_cache (
    list_id TEXT NOT NULL,
    normalized_guess TEXT NOT NULL,
    entry_id TEXT,
    outcome TEXT NOT NULL,
    resolved_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (list_id, normalized_guess)
);
"""


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    if db_path is None:
        db_path = DB_PATH  # resolved at call time, not import time, so tests can monkeypatch it
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(_SCHEMA)
    conn.commit()
    return conn
