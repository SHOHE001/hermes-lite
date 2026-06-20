from __future__ import annotations

import sqlite3
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    scope_key TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);
"""


class SessionStore:
    def __init__(self, db_path: Path):
        self._db = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)

    def get(self, scope_key: str) -> str | None:
        row = self._db.execute(
            "SELECT session_id FROM sessions WHERE scope_key = ?", (scope_key,)
        ).fetchone()
        return row[0] if row else None

    def set(self, scope_key: str, session_id: str) -> None:
        self._db.execute(
            "INSERT INTO sessions(scope_key, session_id, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(scope_key) DO UPDATE SET session_id=excluded.session_id, "
            "updated_at=excluded.updated_at",
            (scope_key, session_id, int(time.time())),
        )

    def delete(self, scope_key: str) -> None:
        self._db.execute("DELETE FROM sessions WHERE scope_key = ?", (scope_key,))
