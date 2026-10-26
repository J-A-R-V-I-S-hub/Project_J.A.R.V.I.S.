from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = Field(default="__set_in_env__", alias="TELEGRAM_BOT_TOKEN")
    telegram_allowed_user_id: int = Field(default=0, alias="TELEGRAM_ALLOWED_USER_ID")

    openrouter_api_key: str = Field(default="__set_in_env__", alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(default="openai/gpt-4.1-mini", alias="OPENROUTER_MODEL")
    openrouter_vision_model: str = Field(default="openai/gpt-4.1-mini", alias="OPENROUTER_VISION_MODEL")
    openrouter_audio_model: str = Field(default="openai/gpt-4o-mini-transcribe", alias="OPENROUTER_AUDIO_MODEL")
    openrouter_memory_model: str = Field(default="openai/gpt-4.1-nano", alias="OPENROUTER_MEMORY_MODEL")

    agno_db_path: str = Field(default="data/jarvis.db", alias="AGNO_DB_PATH")
    workspace_dir: str = Field(default="data/workspace", alias="JARVIS_WORKSPACE_DIR")
    incoming_dir: str = Field(default="data/incoming", alias="JARVIS_INCOMING_DIR")
    output_dir: str = Field(default="data/output", alias="JARVIS_OUTPUT_DIR")
    reports_dir: str = Field(default="data/reports", alias="JARVIS_REPORTS_DIR")
    python_sandbox_dir: str = Field(default="data/sandbox/python", alias="JARVIS_PYTHON_SANDBOX_DIR")
    shell_sandbox_dir: str = Field(default="data/sandbox/shell", alias="JARVIS_SHELL_SANDBOX_DIR")

    browserbase_api_key: str | None = Field(default=None, alias="BROWSERBASE_API_KEY")
    browserbase_project_id: str | None = Field(default=None, alias="BROWSERBASE_PROJECT_ID")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Agent behaviour
    timezone: str = Field(default="Europe/Rome", alias="JARVIS_TIMEZONE")
    agent_history_runs: int = Field(default=8, alias="JARVIS_HISTORY_RUNS")
    agent_tool_call_limit: int = Field(default=10, alias="JARVIS_TOOL_CALL_LIMIT")
    agent_retries: int = Field(default=1, alias="JARVIS_AGENT_RETRIES")
    max_concurrent_runs: int = Field(default=1, alias="JARVIS_MAX_CONCURRENT_RUNS")
    persona: str = Field(default="butler", alias="JARVIS_PERSONA")
    address_as: str = Field(default="Signore", alias="JARVIS_ADDRESS_AS")
    macos_control_enabled: bool = Field(default=True, alias="JARVIS_MACOS_CONTROL_ENABLED")
    music_app: str = Field(default="Music", alias="JARVIS_MUSIC_APP")
    protocols_enabled: bool = Field(default=True, alias="JARVIS_PROTOCOLS_ENABLED")
    voice_wake_word: str = Field(default="hey jarvis", alias="JARVIS_VOICE_WAKE_WORD")
    voice_stt_backend: str = Field(default="auto", alias="JARVIS_VOICE_STT_BACKEND")
    voice_stt_model: str = Field(default="base", alias="JARVIS_VOICE_STT_MODEL")
    voice_silence_seconds: float = Field(default=1.2, alias="JARVIS_VOICE_SILENCE_SECONDS")
    voice_max_seconds: float = Field(default=15.0, alias="JARVIS_VOICE_MAX_SECONDS")
    voice_device: int | None = Field(default=None, alias="JARVIS_VOICE_DEVICE")
    meeting_dir: str = Field(default="data/meetings", alias="JARVIS_MEETING_DIR")
    dashboard_host: str = Field(default="127.0.0.1", alias="JARVIS_DASHBOARD_HOST")
    dashboard_port: int = Field(default=8765, alias="JARVIS_DASHBOARD_PORT")

    # App state (reminders, artifacts, quality history)
    app_db_path: str = Field(default="data/jarvis_app.db", alias="JARVIS_APP_DB_PATH")
    reminder_poll_seconds: int = Field(default=15, alias="JARVIS_REMINDER_POLL_SECONDS")
    daily_brief_enabled: bool = Field(default=True, alias="JARVIS_DAILY_BRIEF_ENABLED")
    daily_brief_time: str = Field(default="08:00", alias="JARVIS_DAILY_BRIEF_TIME")
    location_name: str = Field(default="Casteggio", alias="JARVIS_LOCATION")
    latitude: float | None = Field(default=None, alias="JARVIS_LATITUDE")
    longitude: float | None = Field(default=None, alias="JARVIS_LONGITUDE")
    file_retention_days: int = Field(default=30, alias="JARVIS_FILE_RETENTION_DAYS")
    quality_watch_dir: str = Field(default="data/weldtrace", alias="JARVIS_QUALITY_WATCH_DIR")
    quality_watch_enabled: bool = Field(default=True, alias="JARVIS_QUALITY_WATCH_ENABLED")

    # Media (optional, require OPENAI_API_KEY)
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    tts_model: str = Field(default="gpt-4o-mini-tts", alias="JARVIS_TTS_MODEL")
    tts_voice: str = Field(default="alloy", alias="JARVIS_TTS_VOICE")
    image_model: str = Field(default="gpt-image-1", alias="JARVIS_IMAGE_MODEL")
    voice_reply_max_chars: int = Field(default=1500, alias="JARVIS_VOICE_MAX_CHARS")

    # Knowledge base (SQLite FTS5, no external vector DB required)
    knowledge_db_path: str = Field(default="data/knowledge.db", alias="JARVIS_KNOWLEDGE_DB_PATH")
    knowledge_dir: str = Field(default="data/knowledge", alias="JARVIS_KNOWLEDGE_DIR")
    knowledge_enabled: bool = Field(default=True, alias="JARVIS_KNOWLEDGE_ENABLED")
    knowledge_chunk_chars: int = Field(default=1200, alias="JARVIS_KNOWLEDGE_CHUNK_CHARS")
    knowledge_max_results: int = Field(default=5, alias="JARVIS_KNOWLEDGE_MAX_RESULTS")

    # Optional integrations (enabled only when credentials are present)
    github_token: str | None = Field(default=None, alias="GITHUB_TOKEN")
    github_default_repo: str | None = Field(default=None, alias="GITHUB_DEFAULT_REPO")
    notion_token: str | None = Field(default=None, alias="NOTION_TOKEN")
    notion_database_id: str | None = Field(default=None, alias="NOTION_DATABASE_ID")
    calendar_ics_url: str | None = Field(default=None, alias="CALENDAR_ICS_URL")
    email_imap_host: str | None = Field(default=None, alias="EMAIL_IMAP_HOST")
    email_imap_port: int = Field(default=993, alias="EMAIL_IMAP_PORT")
    email_smtp_host: str | None = Field(default=None, alias="EMAIL_SMTP_HOST")
    email_smtp_port: int = Field(default=587, alias="EMAIL_SMTP_PORT")
    email_username: str | None = Field(default=None, alias="EMAIL_USERNAME")
    email_password: str | None = Field(default=None, alias="EMAIL_PASSWORD")
    email_from: str | None = Field(default=None, alias="EMAIL_FROM")

    @property
    def db_path(self) -> Path:
        return Path(self.agno_db_path)

    @property
    def app_db_path_obj(self) -> Path:
        return Path(self.app_db_path)

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace_dir)

    @property
    def incoming_path(self) -> Path:
        return Path(self.incoming_dir)

    @property
    def output_path(self) -> Path:
        return Path(self.output_dir)

    @property
    def reports_path(self) -> Path:
        return Path(self.reports_dir)

    @property
    def python_sandbox_path(self) -> Path:
        return Path(self.python_sandbox_dir)

    @property
    def shell_sandbox_path(self) -> Path:
        return Path(self.shell_sandbox_dir)

    @property
    def quality_watch_path(self) -> Path:
        return Path(self.quality_watch_dir)

    @property
    def knowledge_db_path_obj(self) -> Path:
        return Path(self.knowledge_db_path)

    @property
    def knowledge_path(self) -> Path:
        return Path(self.knowledge_dir)

    @property
    def meeting_path(self) -> Path:
        return Path(self.meeting_dir)

    def ensure_directories(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.app_db_path_obj.parent.mkdir(parents=True, exist_ok=True)
        for path in (
            self.workspace_path,
            self.incoming_path,
            self.output_path,
            self.reports_path,
            self.python_sandbox_path,
            self.shell_sandbox_path,
            self.quality_watch_path,
            self.knowledge_path,
            self.knowledge_db_path_obj.parent,
            self.meeting_path,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def validate_required_secrets(self) -> None:
        missing = [
            name
            for name, value in (
                ("TELEGRAM_BOT_TOKEN", self.telegram_bot_token),
                ("OPENROUTER_API_KEY", self.openrouter_api_key),
            )
            if not value or value == "__set_in_env__" or value.startswith("__")
        ]
        if missing:
            raise RuntimeError(
                "Valori mancanti in .env: " + ", ".join(missing)
            )
