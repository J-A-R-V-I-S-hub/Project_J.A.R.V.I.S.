from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Approval:
    id: int
    chat_id: int
    action: str
    payload: dict
    description: str
    status: str
    created_at: str


class ApprovalStore:
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
                CREATE TABLE IF NOT EXISTS approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

    def request(self, chat_id: int, action: str, payload: dict, description: str) -> Approval:
        created = datetime.now(UTC).isoformat()
        connection = self._connect()
        try:
            cursor = connection.execute(
                "INSERT INTO approvals (chat_id, action, payload, description, status, created_at) "
                "VALUES (?, ?, ?, ?, 'pending', ?)",
                (chat_id, action, json.dumps(payload, ensure_ascii=False), description, created),
            )
            connection.commit()
            approval_id = int(cursor.lastrowid)
        finally:
            connection.close()
        return Approval(approval_id, chat_id, action, payload, description, "pending", created)

    def get(self, approval_id: int) -> Approval | None:
        connection = self._connect()
        try:
            row = connection.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        finally:
            connection.close()
        return self._row(row) if row else None

    def approve(self, approval_id: int) -> Approval | None:
        connection = self._connect()
        try:
            cursor = connection.execute(
                "UPDATE approvals SET status = 'approved' WHERE id = ? AND status = 'pending'",
                (approval_id,),
            )
            connection.commit()
            if cursor.rowcount == 0:
                return None
        finally:
            connection.close()
        return self.get(approval_id)

    def cancel(self, approval_id: int) -> bool:
        connection = self._connect()
        try:
            cursor = connection.execute(
                "UPDATE approvals SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
                (approval_id,),
            )
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()

    def pending(self, chat_id: int | None = None) -> list[Approval]:
        connection = self._connect()
        try:
            if chat_id is None:
                rows = connection.execute(
                    "SELECT * FROM approvals WHERE status = 'pending' ORDER BY id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM approvals WHERE status = 'pending' AND chat_id = ? ORDER BY id",
                    (chat_id,),
                ).fetchall()
        finally:
            connection.close()
        return [self._row(row) for row in rows]

    @staticmethod
    def _row(row: sqlite3.Row) -> Approval:
        return Approval(
            id=row["id"],
            chat_id=row["chat_id"],
            action=row["action"],
            payload=json.loads(row["payload"]),
            description=row["description"],
            status=row["status"],
            created_at=row["created_at"],
        )

    def format_pending(self, chat_id: int) -> str:
        pending = self.pending(chat_id)
        if not pending:
            return "Nessuna azione in attesa di approvazione."
        lines = ["🔐 **Azioni in attesa**"]
        for approval in pending:
            lines.append(f"• `{approval.id}` {approval.description}")
            lines.append(f"  /confirm {approval.id} · /cancel {approval.id}")
        return "\n".join(lines)


def execute_approval(approval: Approval, settings, runner: Any = None) -> str:
    action = approval.action
    payload = approval.payload

    if action == "email.send":
        from .integrations.email import EmailClient

        client = EmailClient(
            settings.email_imap_host,
            settings.email_imap_port,
            settings.email_smtp_host,
            settings.email_smtp_port,
            settings.email_username,
            settings.email_password,
            settings.email_from,
        )
        return client.send(payload["to"], payload["subject"], payload["body"])

    if action == "protocol.run" and runner is not None:
        protocol = runner.protocols.get(payload["name"])
        if protocol is None:
            return f"Protocollo '{payload['name']}' non trovato."
        return "\n".join(runner.protocol_runner.run(protocol))

    if action == "macos.run_shortcut":
        from .integrations.macos import run_shortcut

        return run_shortcut(payload["name"])

    if action == "home_assistant.call_service":
        from .integrations.home_assistant import HomeAssistantClient

        client = HomeAssistantClient.from_settings(settings)
        if client is None:
            return "Home Assistant non configurato."
        return client.call_service(
            payload["domain"],
            payload["service"],
            payload.get("entity_id", ""),
            payload.get("data"),
        )

    if action == "shell.run":
        from .security import run_safe_command

        return run_safe_command(payload["command"], payload.get("cwd"))

    return f"Azione sconosciuta: {action}"
