from jarvis_bot.config import Settings
from jarvis_bot.doctor import format_checks, run_checks


def test_doctor_checks_core_modules() -> None:
    settings = Settings(TELEGRAM_BOT_TOKEN="123:abc", OPENROUTER_API_KEY="sk-test")
    checks = run_checks(settings)
    names = {check.name: check for check in checks}

    assert names["Python"].ok is True
    assert names["Modulo agno"].ok is True
    assert names["Modulo aiogram"].ok is True
    assert "Jarvis doctor" in format_checks(checks)
