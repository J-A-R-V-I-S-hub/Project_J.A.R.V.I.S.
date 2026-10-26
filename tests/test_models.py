from jarvis_bot.config import Settings
from jarvis_bot.models import choose_model


def _settings() -> Settings:
    return Settings(
        TELEGRAM_BOT_TOKEN="123:abc",
        OPENROUTER_API_KEY="sk-test",
        JARVIS_MODEL_ROUTING_ENABLED=True,
        JARVIS_CHEAP_MODEL="cheap/model",
        JARVIS_SMART_MODEL="smart/model",
    )


def test_simple_message_uses_cheap_model() -> None:
    assert choose_model("ciao, come stai?", _settings()) == "cheap/model"


def test_complex_message_uses_smart_model() -> None:
    assert choose_model("analizza questo CSV e crea un report", _settings()) == "smart/model"
    assert choose_model("x", _settings(), has_attachments=True) == "smart/model"


def test_vision_uses_vision_model() -> None:
    settings = _settings()
    assert choose_model("cos'è questo?", settings, has_images=True) == settings.openrouter_vision_model
