from pathlib import Path

from jarvis_bot.app_state import AppStateStore
from jarvis_bot.media import generate_image


def test_app_state_roundtrip(tmp_path: Path) -> None:
    store = AppStateStore(tmp_path / "app.db")

    assert store.get_bool(1, "voice_replies", default=False) is False
    store.set(1, "voice_replies", "true")
    assert store.get_bool(1, "voice_replies") is True
    store.set(1, "voice_replies", "false")
    assert store.get_bool(1, "voice_replies") is False


def test_generate_image_requires_key(tmp_path: Path) -> None:
    try:
        generate_image("gatto", tmp_path / "image.png", api_key=None)
    except RuntimeError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("generate_image should require an API key")
