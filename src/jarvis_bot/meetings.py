from __future__ import annotations

import sqlite3
import threading
import time
import wave
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings
from .reporting import slugify_filename


@dataclass(slots=True)
class Meeting:
    id: int
    title: str
    transcript: str
    summary: str
    action_items: str
    duration: float
    created_at: str


class MeetingStore:
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
                CREATE TABLE IF NOT EXISTS meetings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    transcript TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    action_items TEXT NOT NULL,
                    duration REAL NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

    def add(
        self,
        title: str,
        transcript: str,
        summary: str,
        action_items: str = "",
        duration: float = 0.0,
    ) -> Meeting:
        now = datetime.now(UTC).isoformat()
        connection = self._connect()
        try:
            cursor = connection.execute(
                "INSERT INTO meetings (title, transcript, summary, action_items, duration, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (title, transcript, summary, action_items, duration, now),
            )
            connection.commit()
            meeting_id = int(cursor.lastrowid)
        finally:
            connection.close()
        return Meeting(meeting_id, title, transcript, summary, action_items, duration, now)

    def list(self, limit: int = 10) -> list[Meeting]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM meetings ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        finally:
            connection.close()
        return [self._row(row) for row in rows]

    def get(self, meeting_id: int) -> Meeting | None:
        connection = self._connect()
        try:
            row = connection.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        finally:
            connection.close()
        return self._row(row) if row else None

    @staticmethod
    def _row(row: sqlite3.Row) -> Meeting:
        return Meeting(
            id=row["id"],
            title=row["title"],
            transcript=row["transcript"],
            summary=row["summary"],
            action_items=row["action_items"],
            duration=row["duration"],
            created_at=row["created_at"],
        )

    def format_list(self, meetings: list[Meeting]) -> str:
        if not meetings:
            return "Nessuna riunione registrata."
        lines = ["📝 **Riunioni**"]
        for meeting in meetings:
            minutes = meeting.duration / 60 if meeting.duration else 0
            lines.append(
                f"• `{meeting.id}` — {meeting.title} — {minutes:.0f} min — {meeting.created_at[:10]}"
            )
        return "\n".join(lines)

    def format_meeting(self, meeting: Meeting) -> str:
        lines = [f"📝 **{meeting.title}** (id `{meeting.id}`)", "", meeting.summary]
        if meeting.action_items:
            lines.extend(["", "**Action item**", meeting.action_items])
        return "\n".join(lines)


class MeetingRecorder:
    """Record microphone audio to a WAV file while the bot is running."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.meeting_path.mkdir(parents=True, exist_ok=True)
        self._stream = None
        self._wave = None
        self._started_at: float | None = None
        self._path: Path | None = None
        self._lock = threading.Lock()

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    def start(self, title: str) -> Path:
        if self.is_recording:
            raise RuntimeError("Registrazione già in corso.")
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError(
                "Registrazione non disponibile: installa le dipendenze con pip install -e '.[voice]'."
            ) from exc

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_title = slugify_filename(title, "meeting")
        self._path = self.settings.meeting_path / f"{stamp}-{safe_title}.wav"
        self._wave = wave.open(str(self._path), "wb")  # noqa: SIM115 - kept open across recording
        self._wave.setnchannels(1)
        self._wave.setsampwidth(2)
        self._wave.setframerate(16000)

        def callback(indata, frames, time_info, status) -> None:
            if self._wave is None:
                return
            pcm = np.clip(indata[:, 0], -1.0, 1.0)
            self._wave.writeframes((pcm * 32767).astype(np.int16).tobytes())

        self._stream = sd.InputStream(
            samplerate=16000,
            channels=1,
            dtype="float32",
            callback=callback,
            device=self.settings.voice_device,
        )
        self._stream.start()
        self._started_at = time.time()
        return self._path

    def stop(self) -> tuple[Path, float]:
        if not self.is_recording or self._path is None or self._wave is None:
            raise RuntimeError("Nessuna registrazione in corso.")
        duration = time.time() - (self._started_at or time.time())
        with self._lock:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
            self._wave.close()
            path = self._path
            self._stream = None
            self._wave = None
            self._path = None
            self._started_at = None
        return path, duration


def summarize_meeting(transcript: str, settings: Settings) -> tuple[str, str]:
    """Return (summary, action_items) in Italian using the configured LLM."""
    from agno.agent import Agent
    from agno.models.openrouter import OpenRouterResponses

    agent = Agent(
        name="Jarvis Meeting",
        model=OpenRouterResponses(id=settings.openrouter_model),
        markdown=True,
        instructions=[
            "Sei Jarvis. Riassumi la riunione in italiano in modo chiaro e conciso.",
            "Struttura la risposta in: SINTESI, DECISIONI, AZIONI.",
            "Nella sezione AZIONI elenca ogni attività con owner e scadenza se presenti, una per riga.",
            "Non inventare informazioni non presenti nella trascrizione.",
        ],
    )
    response = agent.run(input="Trascrizione della riunione:\n\n" + transcript)
    content = str(response.content).strip()

    action_items = ""
    if "AZIONI" in content.upper():
        marker = content.upper().rfind("AZIONI")
        action_items = content[marker + len("AZIONI") :].lstrip(" :\n").strip()
        summary = content[:marker].rstrip(" :\n-").strip()
    else:
        summary = content
    return summary or content, action_items
