from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .integrations import macos, music

DEFAULT_PROTOCOLS: dict[str, dict] = {
    "lavoro": {
        "description": "Prepara la postazione di lavoro.",
        "steps": [
            {"type": "open_app", "value": "Visual Studio Code"},
            {"type": "music", "value": "play"},
            {"type": "volume", "value": 30},
            {"type": "notify", "title": "Protocollo Lavoro", "message": "Postazione pronta, signore."},
        ],
    },
    "focus": {
        "description": "Modalità concentrazione: volume basso e notifica.",
        "steps": [
            {"type": "volume", "value": 15},
            {"type": "music", "value": "play"},
            {"type": "notify", "title": "Focus", "message": "Modalità concentrazione attiva."},
        ],
    },
    "buonanotte": {
        "description": "Chiude la giornata: musica off, notifica e schermo bloccato.",
        "steps": [
            {"type": "music", "value": "pause"},
            {"type": "volume", "value": 20},
            {"type": "notify", "title": "Buonanotte", "message": "Sistemi in standby. A domani."},
            {"type": "lock"},
        ],
    },
    "emergenza": {
        "description": "Blocca la sessione e lascia una notifica.",
        "steps": [
            {"type": "notify", "title": "Protocollo Emergenza", "message": "Sessione bloccata."},
            {"type": "lock"},
        ],
    },
}


@dataclass(slots=True)
class Protocol:
    name: str
    description: str
    steps: list[dict]


class ProtocolStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self.seed_defaults()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        connection = self._connect()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS protocols (
                    name TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    steps TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

    def seed_defaults(self) -> None:
        for name, data in DEFAULT_PROTOCOLS.items():
            if self.get(name) is None:
                self.upsert(name, data["description"], data["steps"])

    def list(self) -> list[Protocol]:
        connection = self._connect()
        try:
            rows = connection.execute("SELECT * FROM protocols ORDER BY name").fetchall()
        finally:
            connection.close()
        return [
            Protocol(name=row["name"], description=row["description"], steps=json.loads(row["steps"]))
            for row in rows
        ]

    def get(self, name: str) -> Protocol | None:
        connection = self._connect()
        try:
            row = connection.execute("SELECT * FROM protocols WHERE name = ?", (name,)).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return Protocol(name=row["name"], description=row["description"], steps=json.loads(row["steps"]))

    def upsert(self, name: str, description: str, steps: list[dict]) -> Protocol:
        cleaned = name.strip().lower().replace(" ", "_")
        if not cleaned:
            raise ValueError("Nome protocollo vuoto.")
        if not isinstance(steps, list) or not steps:
            raise ValueError("Il protocollo deve avere almeno un passo.")
        now = datetime.now(UTC).isoformat()
        connection = self._connect()
        try:
            connection.execute(
                """
                INSERT INTO protocols (name, description, steps, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    description = excluded.description,
                    steps = excluded.steps,
                    updated_at = excluded.updated_at
                """,
                (cleaned, description.strip() or cleaned, json.dumps(steps, ensure_ascii=False), now, now),
            )
            connection.commit()
        finally:
            connection.close()
        return Protocol(cleaned, description.strip() or cleaned, steps)

    def delete(self, name: str) -> bool:
        connection = self._connect()
        try:
            cursor = connection.execute("DELETE FROM protocols WHERE name = ?", (name.strip().lower(),))
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()

    def format_list(self) -> str:
        protocols = self.list()
        if not protocols:
            return "Nessun protocollo configurato."
        lines = ["🧩 **Protocolli disponibili**"]
        for protocol in protocols:
            lines.append(f"• **{protocol.name}** — {protocol.description}")
        lines.append("\nEsegui con `/protocol <nome>` oppure chiedi a Jarvis.")
        return "\n".join(lines)


class ProtocolRunner:
    def __init__(self, music_app: str = "Music") -> None:
        self.music_app = music_app

    def run(self, protocol: Protocol) -> list[str]:
        results: list[str] = []
        for index, step in enumerate(protocol.steps, start=1):
            try:
                results.append(f"{index}. {self._run_step(step)}")
            except Exception as exc:
                results.append(f"{index}. Errore: {exc}")
        return results

    def _run_step(self, step: dict) -> str:
        step_type = str(step.get("type", "")).lower()
        value = step.get("value")

        if step_type == "open_app":
            return macos.open_app(str(value))
        if step_type == "open_url":
            return macos.open_url(str(value))
        if step_type == "notify":
            return macos.notify(str(step.get("title", "Jarvis")), str(step.get("message", "")))
        if step_type == "volume":
            return macos.set_volume(int(value))
        if step_type == "lock":
            return macos.lock_screen()
        if step_type == "screenshot":
            return macos.screenshot(str(value or "data/output/protocol-screenshot.png"))
        if step_type == "shortcut":
            return macos.run_shortcut(str(value))
        if step_type == "sleep":
            time.sleep(min(float(value or 1), 30))
            return f"Attesa di {value}s."
        if step_type == "music":
            action = str(value or "play_pause")
            if action == "play":
                return music.play(self.music_app)
            if action == "pause":
                return music.pause(self.music_app)
            if action == "next":
                return music.next_track(self.music_app)
            if action == "previous":
                return music.previous_track(self.music_app)
            return music.play_pause(self.music_app)
        if step_type == "home_assistant":
            from .integrations.home_assistant import HomeAssistantClient

            client = HomeAssistantClient.from_env()
            if client is None:
                return "Home Assistant non configurato."
            return client.call_service(
                str(step.get("domain", "homeassistant")),
                str(step.get("service", "toggle")),
                str(value or step.get("entity_id", "")),
            )
        if step_type == "backup":
            from .backup import create_backup

            return create_backup(Path("data"))
        if step_type == "timeline":
            return "Passo descrittivo."
        return f"Tipo di passo sconosciuto: {step_type}"
