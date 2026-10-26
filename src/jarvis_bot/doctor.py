from __future__ import annotations

import importlib.util
import platform
import sys
from dataclasses import dataclass

from .config import Settings
from .sandbox import docker_available

REQUIRED_MODULES = {
    "agno": "core",
    "aiogram": "core",
    "pandas": "core",
    "matplotlib": "grafici",
    "reportlab": "PDF",
    "pypdf": "PDF",
    "pydantic": "core",
    "httpx": "integrazioni",
}

OPTIONAL_MODULES = {
    "openai": "TTS/immagini",
    "openpyxl": "Excel",
    "docx": "Word",
    "sounddevice": "voce/meeting",
    "faster_whisper": "STT locale",
    "openwakeword": "wake word",
    "psutil": "HUD",
    "browserbase": "browser",
}


@dataclass(slots=True)
class Check:
    name: str
    ok: bool
    detail: str = ""
    required: bool = True


def _has_module(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def run_checks(settings: Settings) -> list[Check]:
    checks: list[Check] = [
        Check("Python", sys.version_info >= (3, 11), platform.python_version()),
        Check("Sistema", True, f"{platform.system()} {platform.release()}"),
    ]

    for module, purpose in REQUIRED_MODULES.items():
        checks.append(Check(f"Modulo {module}", _has_module(module), purpose))
    for module, purpose in OPTIONAL_MODULES.items():
        checks.append(Check(f"Opzionale {module}", _has_module(module), purpose, required=False))

    checks.extend(
        [
            Check("TELEGRAM_BOT_TOKEN", bool(settings.telegram_bot_token and not settings.telegram_bot_token.startswith("__"))),
            Check("OPENROUTER_API_KEY", bool(settings.openrouter_api_key and not settings.openrouter_api_key.startswith("__"))),
            Check("Cartella dati", settings.db_path.parent.exists(), str(settings.db_path.parent)),
            Check("Cartella incoming", settings.incoming_path.exists(), str(settings.incoming_path)),
            Check("Cartella output", settings.output_path.exists(), str(settings.output_path)),
            Check("Cartella reports", settings.reports_path.exists(), str(settings.reports_path)),
            Check("Knowledge base", settings.knowledge_db_path_obj.exists(), str(settings.knowledge_db_path_obj), required=False),
            Check("App DB", settings.app_db_path_obj.exists(), str(settings.app_db_path_obj), required=False),
            Check("OPENAI_API_KEY", bool(settings.openai_api_key), "TTS/immagini (opzionale)", required=False),
            Check("Home Assistant", bool(settings.home_assistant_url and settings.home_assistant_token), "", required=False),
            Check("GitHub", bool(settings.github_token), "", required=False),
            Check("Email", bool(settings.email_imap_host and settings.email_username), "", required=False),
            Check("Calendario ICS", bool(settings.calendar_ics_url), "", required=False),
            Check("Presenza", bool(settings.phone_ip), "JARVIS_PHONE_IP", required=False),
            Check(
                "Docker",
                docker_available(),
                "sandbox Python",
                required=settings.sandbox_backend.lower() == "docker",
            ),
        ]
    )
    return checks


def format_checks(checks: list[Check]) -> str:
    lines = ["🩺 **Jarvis doctor**", ""]
    for check in checks:
        if check.ok:
            icon = "✅"
        elif check.required:
            icon = "❌"
        else:
            icon = "⚠️"
        suffix = f" — {check.detail}" if check.detail else ""
        lines.append(f"{icon} {check.name}{suffix}")
    failures = [check.name for check in checks if check.required and not check.ok]
    lines.append("")
    if failures:
        lines.append("Problemi bloccanti: " + ", ".join(failures))
    else:
        lines.append("Nessun problema bloccante.")
    return "\n".join(lines)


def main() -> None:
    settings = Settings()
    print(format_checks(run_checks(settings)))


if __name__ == "__main__":
    main()
