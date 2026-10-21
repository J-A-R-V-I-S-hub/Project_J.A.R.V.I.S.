from jarvis_bot.agent import JarvisAgentRunner
from jarvis_bot.config import Settings
from jarvis_bot.service import JarvisTelegramService


class DummyRunner:
    def transcribe_audio(self, audio_path):  # pragma: no cover - interface stub
        return "trascrizione"

    def run(self, message, artifact_queue):  # pragma: no cover - interface stub
        return "risposta"


def test_allowed_user_filter() -> None:
    settings = Settings(
        TELEGRAM_BOT_TOKEN="123456:TESTTOKEN",
        OPENROUTER_API_KEY="key",
        TELEGRAM_ALLOWED_USER_ID=123456789,
    )
    service = JarvisTelegramService(settings=settings, agent_runner=DummyRunner())
    assert service.is_allowed_user(123456789) is True
    assert service.is_allowed_user(123) is False


def test_extract_text_prefers_caption_or_text() -> None:
    settings = Settings(
        TELEGRAM_BOT_TOKEN="123456:TESTTOKEN",
        OPENROUTER_API_KEY="key",
    )
    service = JarvisTelegramService(settings=settings, agent_runner=DummyRunner())

    class FakeMessage:
        text = None
        caption = "ciao"

    assert service._extract_user_text(FakeMessage()) == "ciao"


def test_session_id_is_stable_per_chat() -> None:
    assert JarvisAgentRunner.session_id_for(42) == "telegram:42"
    assert JarvisAgentRunner.session_id_for(42) == JarvisAgentRunner.session_id_for(42)
