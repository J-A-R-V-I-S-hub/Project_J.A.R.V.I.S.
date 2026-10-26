from pathlib import Path

from jarvis_bot.meetings import MeetingStore
from jarvis_bot.voice_loop import strip_wake_word


def test_strip_wake_word() -> None:
    assert strip_wake_word("Hey Jarvis, che ore sono?", "hey jarvis") == "che ore sono?"
    assert strip_wake_word("che ore sono?", "hey jarvis") == ""
    assert strip_wake_word("che ore sono?", "hey jarvis", require=False) == "che ore sono?"


def test_meeting_store_roundtrip(tmp_path: Path) -> None:
    store = MeetingStore(tmp_path / "app.db")
    meeting = store.add(
        "Riunione qualità",
        "Trascrizione completa della riunione.",
        "Sintesi della riunione.",
        "- controllare i difetti del prodotto A4636",
        duration=125,
    )

    assert meeting.id > 0
    assert store.get(meeting.id) is not None
    assert store.list()[0].title == "Riunione qualità"
    assert "Riunione qualità" in store.format_list(store.list())
    assert "A4636" in store.format_meeting(meeting)
