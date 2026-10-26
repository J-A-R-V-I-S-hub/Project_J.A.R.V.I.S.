from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(slots=True)
class AuditEntry:
    id: int
    action: str
    details: str
    actor: str
    created_at: str


class AuditStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        connection = self._connect()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    actor TEXT NOT NULL DEFAULT 'jarvis',
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

    def record(self, action: str, details: str = "", actor: str = "jarvis") -> AuditEntry:
        created = datetime.now(UTC).isoformat()
        connection = self._connect()
        try:
            cursor = connection.execute(
                "INSERT INTO audit_log (action, details, actor, created_at) VALUES (?, ?, ?, ?)",
                (action, details, actor, created),
            )
            connection.commit()
            entry_id = int(cursor.lastrowid)
        finally:
            connection.close()
        return AuditEntry(entry_id, action, details, actor, created)

    def recent(self, limit: int = 20) -> list[AuditEntry]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        finally:
            connection.close()
        return [
            AuditEntry(row["id"], row["action"], row["details"], row["actor"], row["created_at"])
            for row in rows
        ]

    def format_recent(self, limit: int = 20) -> str:
        entries = self.recent(limit)
        if not entries:
            return "Audit log vuoto."
        lines = ["🧾 **Audit log**"]
        for entry in entries:
            moment = entry.created_at.replace("T", " ")[:19]
            details = f" — {entry.details}" if entry.details else ""
            lines.append(f"• `{entry.id}` {moment} · {entry.action}{details}")
        return "\n".join(lines)
