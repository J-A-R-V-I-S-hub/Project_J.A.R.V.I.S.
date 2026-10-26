from datetime import UTC, datetime
from pathlib import Path

from jarvis_bot.config import Settings
from jarvis_bot.presence import PresenceState
from jarvis_bot.proactive import ProactiveEngine, ProactiveStore


class FakePresence:
    enabled = True

    def __init__(self) -> None:
        self.calls = 0

    def check(self) -> PresenceState:
        self.calls += 1
        return PresenceState(True, self.calls == 1, datetime.now(UTC).isoformat())


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        TELEGRAM_BOT_TOKEN="123:abc",
        OPENROUTER_API_KEY="sk-test",
        JARVIS_APP_DB_PATH=str(tmp_path / "app.db"),
        JARVIS_PROACTIVE_ENABLED=True,
        JARVIS_PROACTIVE_COOLDOWN_SECONDS=3600,
    )


def test_proactive_store_cooldown(tmp_path: Path) -> None:
    store = ProactiveStore(tmp_path / "app.db")

    assert store.should_send("email", "3", 3600) is True
    store.mark("email", "3")
    assert store.should_send("email", "3", 3600) is False
    assert store.should_send("email", "3", 0) is True


def test_proactive_engine_presence(tmp_path: Path, monkeypatch) -> None:
    engine = ProactiveEngine(_settings(tmp_path), FakePresence())
    monkeypatch.setattr(engine, "_weather_events", lambda: [])

    first = engine.check()
    assert any("Bentornato" in message for message in first)

    second = engine.check()
    assert second == []
