from pathlib import Path

from jarvis_bot.config import Settings
from jarvis_bot.dashboard import build_status
from jarvis_bot.reminders import ReminderStore


def _settings(tmp_path: Path) -> Settings:
    settings = Settings(
        TELEGRAM_BOT_TOKEN="123:abc",
        OPENROUTER_API_KEY="sk-test",
        TELEGRAM_ALLOWED_USER_ID=1,
        AGNO_DB_PATH=str(tmp_path / "agno.db"),
        JARVIS_APP_DB_PATH=str(tmp_path / "app.db"),
        JARVIS_WORKSPACE_DIR=str(tmp_path / "workspace"),
        JARVIS_INCOMING_DIR=str(tmp_path / "incoming"),
        JARVIS_OUTPUT_DIR=str(tmp_path / "output"),
        JARVIS_REPORTS_DIR=str(tmp_path / "reports"),
        JARVIS_PYTHON_SANDBOX_DIR=str(tmp_path / "py"),
        JARVIS_SHELL_SANDBOX_DIR=str(tmp_path / "sh"),
        JARVIS_QUALITY_WATCH_DIR=str(tmp_path / "quality"),
        JARVIS_KNOWLEDGE_DB_PATH=str(tmp_path / "knowledge.db"),
        JARVIS_KNOWLEDGE_DIR=str(tmp_path / "knowledge"),
        JARVIS_MEETING_DIR=str(tmp_path / "meetings"),
    )
    settings.ensure_directories()
    return settings


def test_build_status_contains_system_and_data(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    (settings.output_path / "chart.png").write_bytes(b"png")
    ReminderStore(settings.app_db_path_obj).add(1, "Bere acqua", "+1h")

    status = build_status(settings)

    assert status["system"]["disk"]["total"] > 0
    assert status["stats"]["runs"] == 0
    assert status["reminders"][0]["text"] == "Bere acqua"
    assert status["artifacts"][0]["name"] == "chart.png"
    assert "lavoro" in status["protocols"]
