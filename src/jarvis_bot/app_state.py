from __future__ import annotations

import sqlite3
from pathlib import Path


class AppStateStore:
    """Tiny per-chat key/value store stored in the local app database."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_state (
                    chat_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    PRIMARY KEY (chat_id, key)
                )
                """
            )

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def get(self, chat_id: int, key: str, default: str | None = None) -> str | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT value FROM chat_state WHERE chat_id = ? AND key = ?",
                (chat_id, key),
            ).fetchone()
            return row["value"] if row else default
        finally:
            connection.close()

    def get_bool(self, chat_id: int, key: str, default: bool = False) -> bool:
        value = self.get(chat_id, key)
        if value is None:
            return default
        return value.lower() in {"1", "true", "yes", "on", "si", "sì"}

    def set(self, chat_id: int, key: str, value: str) -> None:
        connection = self._connect()
        try:
            connection.execute(
                "INSERT OR REPLACE INTO chat_state (chat_id, key, value) VALUES (?, ?, ?)",
                (chat_id, key, value),
            )
            connection.commit()
        finally:
            connection.close()
