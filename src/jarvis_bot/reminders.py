from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

RECURRENCES = {"none", "daily", "weekly"}


@dataclass(slots=True)
class Reminder:
    id: int
    chat_id: int
    text: str
    due_at: str
    recurrence: str
    status: str

    def due_local(self, tz: ZoneInfo) -> datetime:
        return datetime.fromisoformat(self.due_at).astimezone(tz)


def parse_when(value: str, now: datetime | None = None, tz: ZoneInfo | None = None) -> datetime:
    """Parse ISO datetimes plus a few Italian-friendly shortcuts.

    Supports: "2026-10-22 09:00", "22/10/2026 09:00", "domani alle 8",
    "oggi 18:30", "tra 10 minuti", "tra 2 ore", "+30m", "18:30".
    """
    tz = tz or ZoneInfo("Europe/Rome")
    now = now or datetime.now(tz)
    raw = value.strip()
    if not raw:
        raise ValueError("Data/ora mancante.")

    lowered = raw.lower()

    match = re.fullmatch(r"\+\s*(\d+)\s*([mhd])", lowered)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        delta = {"m": timedelta(minutes=amount), "h": timedelta(hours=amount), "d": timedelta(days=amount)}[unit]
        return now + delta

    match = re.fullmatch(r"tra\s+(\d+)\s+(minut[oi]|or[ae]|giorn[oi])", lowered)
    if match:
        amount = int(match.group(1))
        word = match.group(2)
        if word.startswith("minut"):
            return now + timedelta(minutes=amount)
        if word.startswith("or"):
            return now + timedelta(hours=amount)
        return now + timedelta(days=amount)

    day_offset: int | None = None
    remainder = lowered
    for keyword, offset in (("dopodomani", 2), ("domani", 1), ("oggi", 0)):
        if lowered.startswith(keyword):
            day_offset = offset
            remainder = lowered[len(keyword) :].strip()
            break

    if day_offset is not None:
        hour, minute = 9, 0
        time_match = re.search(r"(\d{1,2})(?::(\d{2}))?", remainder)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Orario non valido.")
        day = (now + timedelta(days=day_offset)).date()
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)

    match = re.fullmatch(r"(?:alle?\s*)?(\d{1,2}):(\d{2})", lowered)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Orario non valido.")
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    for parser in (datetime.fromisoformat, lambda text: datetime.strptime(text, "%d/%m/%Y %H:%M")):
        try:
            parsed = parser(raw)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed

    raise ValueError(
        "Formato data non riconosciuto. Usa ISO come '2026-10-22 09:00' oppure "
        "'domani alle 8', 'tra 2 ore', '+30m'."
    )


class ReminderStore:
    """Small SQLite-backed reminder store, safe to use from multiple threads."""

    def __init__(self, db_path: str | Path, timezone_name: str = "Europe/Rome") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.tz = ZoneInfo(timezone_name)
        self._init_schema()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    recurrence TEXT NOT NULL DEFAULT 'none',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, due_at)"
            )

    @staticmethod
    def _row_to_reminder(row: sqlite3.Row) -> Reminder:
        return Reminder(
            id=row["id"],
            chat_id=row["chat_id"],
            text=row["text"],
            due_at=row["due_at"],
            recurrence=row["recurrence"],
            status=row["status"],
        )

    def add(self, chat_id: int, text: str, due_at: str, recurrence: str = "none") -> Reminder:
        if recurrence not in RECURRENCES:
            raise ValueError(f"Recorrenza non valida: {recurrence}. Usa {sorted(RECURRENCES)}.")
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("Il testo del promemoria è vuoto.")
        when = parse_when(due_at, tz=self.tz).astimezone(timezone.utc)
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO reminders (chat_id, text, due_at, recurrence, status, created_at) "
                "VALUES (?, ?, ?, ?, 'pending', ?)",
                (chat_id, cleaned, when.isoformat(), recurrence, now_iso),
            )
            reminder_id = int(cursor.lastrowid)
        return Reminder(reminder_id, chat_id, cleaned, when.isoformat(), recurrence, "pending")

    def list(self, chat_id: int, include_done: bool = False) -> list[Reminder]:
        query = "SELECT * FROM reminders WHERE chat_id = ?"
        params: list[object] = [chat_id]
        if not include_done:
            query += " AND status = 'pending'"
        query += " ORDER BY due_at ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_reminder(row) for row in rows]

    def cancel(self, chat_id: int, reminder_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE reminders SET status = 'cancelled' "
                "WHERE id = ? AND chat_id = ? AND status = 'pending'",
                (reminder_id, chat_id),
            )
            return cursor.rowcount > 0

    def due(self, now: datetime | None = None) -> list[Reminder]:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reminders WHERE status = 'pending' AND due_at <= ? ORDER BY due_at ASC",
                (current,),
            ).fetchall()
        return [self._row_to_reminder(row) for row in rows]

    def mark_sent(self, reminder: Reminder, now: datetime | None = None) -> None:
        current = now or datetime.now(timezone.utc)
        if reminder.recurrence in {"daily", "weekly"}:
            step = timedelta(days=1 if reminder.recurrence == "daily" else 7)
            next_due = datetime.fromisoformat(reminder.due_at)
            while next_due <= current:
                next_due += step
            with self._connect() as connection:
                connection.execute(
                    "UPDATE reminders SET due_at = ? WHERE id = ?",
                    (next_due.astimezone(timezone.utc).isoformat(), reminder.id),
                )
            return

        with self._connect() as connection:
            connection.execute("UPDATE reminders SET status = 'sent' WHERE id = ?", (reminder.id,))

    def format_list(self, reminders: list[Reminder]) -> str:
        if not reminders:
            return "Nessun promemoria attivo."
        lines = ["⏰ **Promemoria attivi**"]
        for reminder in reminders:
            when = reminder.due_local(self.tz).strftime("%d/%m/%Y %H:%M")
            suffix = "" if reminder.recurrence == "none" else f" ({reminder.recurrence})"
            lines.append(f"• `{reminder.id}` — {when} — {reminder.text}{suffix}")
        return "\n".join(lines)
