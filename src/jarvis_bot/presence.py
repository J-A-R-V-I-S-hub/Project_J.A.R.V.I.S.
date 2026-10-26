from __future__ import annotations

import platform
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(slots=True)
class PresenceState:
    at_home: bool
    changed: bool
    checked_at: str


def ping_host(ip: str, timeout: int = 2) -> bool:
    command = ["ping", "-c", "1"]
    if platform.system() == "Darwin":
        command += ["-W", "1000"]
    command.append(ip)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


class PresenceTracker:
    """Detect whether the user's phone is reachable on the local network."""

    def __init__(self, ip: str | None, ping: Callable[[str], bool] | None = None) -> None:
        self.ip = ip
        self._ping = ping or ping_host
        self._last: bool | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.ip)

    def check(self) -> PresenceState:
        if not self.ip:
            return PresenceState(False, False, datetime.now(UTC).isoformat())
        current = self._ping(self.ip)
        changed = self._last is not None and current != self._last
        self._last = current
        return PresenceState(current, changed, datetime.now(UTC).isoformat())

    def describe(self) -> str:
        if not self.enabled:
            return "Rilevamento presenza non configurato (imposta JARVIS_PHONE_IP)."
        state = self.check()
        status = "a casa" if state.at_home else "fuori casa"
        suffix = " (cambio di stato)" if state.changed else ""
        return f"📡 Sei {status}{suffix}."
