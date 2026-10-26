from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import Settings
from .integrations.calendar import load_events
from .integrations.email import EmailClient
from .integrations.github import GitHubClient
from .integrations.weather import weather_alert
from .presence import PresenceTracker


@dataclass(slots=True)
class ProactiveEvent:
    rule: str
    key: str
    message: str


class ProactiveStore:
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
                CREATE TABLE IF NOT EXISTS proactive_events (
                    rule TEXT NOT NULL,
                    key TEXT NOT NULL,
                    last_sent TEXT NOT NULL,
                    PRIMARY KEY (rule, key)
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

    def should_send(self, rule: str, key: str, cooldown_seconds: int) -> bool:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT last_sent FROM proactive_events WHERE rule = ? AND key = ?",
                (rule, key),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return True
        last_sent = datetime.fromisoformat(row["last_sent"])
        return datetime.now(UTC) - last_sent >= timedelta(seconds=cooldown_seconds)

    def mark(self, rule: str, key: str) -> None:
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO proactive_events (rule, key, last_sent) VALUES (?, ?, ?) "
                "ON CONFLICT(rule, key) DO UPDATE SET last_sent = excluded.last_sent",
                (rule, key, datetime.now(UTC).isoformat()),
            )
            connection.commit()
        finally:
            connection.close()


class ProactiveEngine:
    """Runs lightweight checks and returns user-facing proactive messages."""

    def __init__(self, settings: Settings, presence: PresenceTracker | None = None) -> None:
        self.settings = settings
        self.presence = presence
        self.store = ProactiveStore(settings.app_db_path_obj)
        self.email = (
            EmailClient(
                settings.email_imap_host,
                settings.email_imap_port,
                settings.email_smtp_host,
                settings.email_smtp_port,
                settings.email_username,
                settings.email_password,
                settings.email_from,
            )
            if settings.email_imap_host
            and settings.email_smtp_host
            and settings.email_username
            and settings.email_password
            else None
        )
        self.github = (
            GitHubClient(settings.github_token, settings.github_default_repo)
            if settings.github_token
            else None
        )

    def check(self) -> list[str]:
        events: list[ProactiveEvent] = []
        for checker in (
            self._presence_events,
            self._email_events,
            self._github_events,
            self._calendar_events,
            self._weather_events,
        ):
            try:
                events.extend(checker())
            except Exception:
                continue

        messages: list[str] = []
        for event in events:
            if self.store.should_send(event.rule, event.key, self.settings.proactive_cooldown_seconds):
                self.store.mark(event.rule, event.key)
                messages.append(event.message)
        return messages

    def _presence_events(self) -> list[ProactiveEvent]:
        if self.presence is None or not self.presence.enabled:
            return []
        state = self.presence.check()
        if not state.changed:
            return []
        if state.at_home:
            return [ProactiveEvent("presence", "home", "🏠 Bentornato, signore. Sistemi pronti.")]
        return [ProactiveEvent("presence", "away", "👋 A presto, signore. Passo in modalità stand-by.")]

    def _email_events(self) -> list[ProactiveEvent]:
        if self.email is None:
            return []
        count = self.email.count_unread()
        if count < self.settings.proactive_email_threshold:
            return []
        return [
            ProactiveEvent(
                "email",
                f"unread-{count}",
                f"📬 Hai {count} email non lette. Chiedimi un riepilogo quando vuoi.",
            )
        ]

    def _github_events(self) -> list[ProactiveEvent]:
        if self.github is None:
            return []
        count = self.github.count_notifications()
        if count <= 0:
            return []
        return [
            ProactiveEvent(
                "github",
                "notifications",
                f"🐙 Hai {count} notifiche GitHub non lette.",
            )
        ]

    def _calendar_events(self) -> list[ProactiveEvent]:
        if not self.settings.calendar_ics_url:
            return []
        events = load_events(self.settings.calendar_ics_url, self.settings.timezone)
        now = datetime.now(tz=events[0].start.tzinfo) if events else None
        if now is None:
            return []
        upcoming = [
            event
            for event in events
            if now <= event.start <= now + timedelta(minutes=self.settings.proactive_calendar_lookahead_minutes)
        ]
        return [
            ProactiveEvent(
                "calendar",
                f"{event.start.isoformat()}-{event.summary}",
                f"📅 Tra poco: {event.summary} alle {event.start.strftime('%H:%M')}.",
            )
            for event in upcoming
        ]

    def _weather_events(self) -> list[ProactiveEvent]:
        message = weather_alert(
            self.settings.location_name,
            latitude=self.settings.latitude,
            longitude=self.settings.longitude,
            timezone=self.settings.timezone,
        )
        if not message:
            return []
        today = datetime.now(UTC).date().isoformat()
        return [ProactiveEvent("weather", today, message)]
