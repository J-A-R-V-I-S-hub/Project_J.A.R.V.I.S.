from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from jarvis_bot.reminders import ReminderStore, parse_when

TZ = ZoneInfo("Europe/Rome")


def test_parse_when_relative() -> None:
    now = datetime(2026, 10, 21, 10, 0, tzinfo=TZ)

    assert parse_when("+30m", now, TZ) == now + timedelta(minutes=30)
    assert parse_when("tra 2 ore", now, TZ) == now + timedelta(hours=2)

    tomorrow = parse_when("domani alle 8", now, TZ)
    assert tomorrow.day == 22
    assert tomorrow.hour == 8
    assert tomorrow.minute == 0


def test_parse_when_rejects_unknown_format() -> None:
    now = datetime(2026, 10, 21, 10, 0, tzinfo=TZ)
    with pytest.raises(ValueError):
        parse_when("quando mi pare", now, TZ)


def test_reminder_roundtrip(tmp_path: Path) -> None:
    store = ReminderStore(tmp_path / "app.db")
    reminder = store.add(1, "Bere acqua", "+1m")

    assert reminder.id > 0
    assert [item.text for item in store.list(1)] == ["Bere acqua"]

    future = datetime.now(UTC) + timedelta(minutes=5)
    due = store.due(future)
    assert len(due) == 1

    store.mark_sent(due[0], future)
    assert store.list(1) == []


def test_recurring_reminder_reschedules(tmp_path: Path) -> None:
    store = ReminderStore(tmp_path / "app.db")
    store.add(1, "Daily standup", "+1m", "daily")

    future = datetime.now(UTC) + timedelta(minutes=5)
    due = store.due(future)
    assert len(due) == 1

    store.mark_sent(due[0], future)
    remaining = store.list(1)
    assert len(remaining) == 1
    assert datetime.fromisoformat(remaining[0].due_at) > future


def test_cancel_reminder(tmp_path: Path) -> None:
    store = ReminderStore(tmp_path / "app.db")
    reminder = store.add(1, "Da annullare", "+1h")

    assert store.cancel(1, reminder.id) is True
    assert store.list(1) == []
    assert store.cancel(1, reminder.id) is False
