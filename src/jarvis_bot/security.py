from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

METACHARACTERS = set(";&|`$><\n")

ALLOWED_PATTERNS = [
    r"^pwd$",
    r"^ls(\s|$)",
    r"^cat(\s|$)",
    r"^head(\s|$)",
    r"^tail(\s|$)",
    r"^grep(\s|$)",
    r"^rg(\s|$)",
    r"^find(\s|$)",
    r"^df(\s|$)",
    r"^du(\s|$)",
    r"^ps(\s|$)",
    r"^uname(\s|$)",
    r"^date$",
    r"^echo(\s|$)",
    r"^git\s+(status|log|diff|show|branch|remote|add|commit)(\s|$)",
    r"^python3?\s+-m\s+(pytest|pip)(\s|$)",
    r"^pip\s+(list|show)(\s|$)",
]


def is_command_allowed(command: str) -> tuple[bool, str]:
    stripped = command.strip()
    if not stripped:
        return False, "Comando vuoto."
    if any(character in stripped for character in METACHARACTERS):
        return False, "Il comando contiene metacaratteri di shell non consentiti."
    if not any(re.match(pattern, stripped) for pattern in ALLOWED_PATTERNS):
        return False, "Comando non presente nella allowlist."
    return True, ""


def run_safe_command(command: str, cwd: str | Path | None = None, timeout: int = 20) -> str:
    allowed, reason = is_command_allowed(command)
    if not allowed:
        return f"⛔ Comando bloccato: {reason}"
    try:
        arguments = shlex.split(command)
    except ValueError as exc:
        return f"⛔ Comando non valido: {exc}"
    try:
        completed = subprocess.run(
            arguments,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Comando non eseguito: {exc}"
    output = (completed.stdout or completed.stderr).strip()
    if not output:
        output = "Comando eseguito (nessun output)."
    return output[:4000]
