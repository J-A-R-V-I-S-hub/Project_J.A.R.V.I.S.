import pytest

from jarvis_bot.config import Settings


def test_validate_required_secrets_rejects_missing() -> None:
    settings = Settings(TELEGRAM_BOT_TOKEN="", OPENROUTER_API_KEY="__set_in_env__")
    with pytest.raises(RuntimeError):
        settings.validate_required_secrets()


def test_validate_required_secrets_accepts_real_values() -> None:
    settings = Settings(TELEGRAM_BOT_TOKEN="123:abc", OPENROUTER_API_KEY="sk-test")
    settings.validate_required_secrets()
