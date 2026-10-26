from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path


def on_macos() -> bool:
    return platform.system() == "Darwin"


def _run(command: list[str], timeout: int = 15) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _osascript(script: str) -> str:
    code, out, err = _run(["osascript", "-e", script])
    if code != 0:
        raise RuntimeError(err or "AppleScript non riuscito.")
    return out


def open_app(name: str) -> str:
    """Apre o porta in primo piano un'app macOS."""
    if not on_macos():
        return "Controllo macOS disponibile solo su macOS."
    try:
        _osascript(f'tell application "{_escape(name)}" to activate')
    except Exception as exc:
        return f"Non sono riuscito ad aprire {name}: {exc}"
    return f"Applicazione aperta: {name}."


def open_url(url: str) -> str:
    if not on_macos():
        return "Controllo macOS disponibile solo su macOS."
    code, _, err = _run(["open", url])
    return f"Aperto: {url}" if code == 0 else f"Non riesco ad aprire l'URL: {err}"


def set_volume(level: int) -> str:
    if not on_macos():
        return "Controllo macOS disponibile solo su macOS."
    clamped = max(0, min(100, int(level)))
    try:
        _osascript(f"set volume output volume {clamped}")
    except Exception as exc:
        return f"Volume non impostato: {exc}"
    return f"Volume impostato al {clamped}%."


def get_volume() -> str:
    if not on_macos():
        return "Controllo macOS disponibile solo su macOS."
    try:
        return f"Volume attuale: {_osascript('output volume of (get volume settings)')}%."
    except Exception as exc:
        return f"Volume non disponibile: {exc}"


def toggle_mute() -> str:
    if not on_macos():
        return "Controllo macOS disponibile solo su macOS."
    try:
        muted = _osascript("output muted of (get volume settings)") == "true"
        _osascript(f"set volume output muted {'false' if muted else 'true'}")
    except Exception as exc:
        return f"Mute non disponibile: {exc}"
    return "Audio riattivato." if muted else "Audio silenziato."


def lock_screen() -> str:
    if not on_macos():
        return "Controllo macOS disponibile solo su macOS."
    code, _, _ = _run(["pmset", "displaysleepnow"])
    return "Schermo bloccato." if code == 0 else "Non sono riuscito a bloccare lo schermo."


def screenshot(path: str | Path) -> str:
    if not on_macos():
        return "Controllo macOS disponibile solo su macOS."
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    code, _, err = _run(["screencapture", "-x", str(target)])
    return f"Screenshot salvato: {target}" if code == 0 else f"Screenshot non riuscito: {err}"


def notify(title: str, message: str) -> str:
    if not on_macos():
        return "Notifiche macOS disponibili solo su macOS."
    script = (
        f'display notification "{_escape(message)}" with title "{_escape(title)}"'
    )
    try:
        _osascript(script)
    except Exception as exc:
        return f"Notifica non inviata: {exc}"
    return "Notifica inviata."


def clipboard_get() -> str:
    if not on_macos():
        return "Appunti disponibili solo su macOS."
    code, out, err = _run(["pbpaste"])
    return out if code == 0 else f"Appunti non disponibili: {err}"


def clipboard_set(text: str) -> str:
    if not on_macos():
        return "Appunti disponibili solo su macOS."
    try:
        subprocess.run(["pbcopy"], input=text, text=True, check=True, timeout=10)
    except Exception as exc:
        return f"Appunti non aggiornati: {exc}"
    return "Appunti aggiornati."


def run_shortcut(name: str) -> str:
    if not on_macos():
        return "Shortcuts disponibile solo su macOS."
    code, out, err = _run(["shortcuts", "run", name], timeout=60)
    return f"Shortcut '{name}' eseguito." if code == 0 else f"Shortcut non riuscito: {err or out}"


def _battery_status() -> str:
    code, out, _ = _run(["pmset", "-g", "batt"])
    if code != 0:
        return "batteria n/d"
    parts = out.split("\t")
    for part in parts:
        if "%" in part:
            return part.strip()
    return "batteria n/d"


def _memory_status() -> str:
    try:
        import psutil

        memory = psutil.virtual_memory()
        return f"{memory.percent:.0f}% usata ({memory.used / 1024**3:.1f}/{memory.total / 1024**3:.1f} GB)"
    except Exception:
        code, out, _ = _run(["sysctl", "-n", "hw.memsize"])
        total = int(out) / 1024**3 if code == 0 and out.isdigit() else 0
        return f"{total:.0f} GB totali" if total else "RAM n/d"


def system_health() -> str:
    """Report rapido di salute del Mac: carico, RAM, disco, batteria e uptime."""
    if not on_macos():
        return "Report macOS disponibile solo su macOS."
    load = os.getloadavg()
    disk = shutil.disk_usage("/")
    code, uptime, _ = _run(["uptime"])
    code_ps, processes, _ = _run(["ps", "-Ao", "%cpu,comm", "-r"])
    top = []
    if code_ps == 0:
        top = processes.splitlines()[1:6]

    lines = [
        f"🖥️ **Salute del Mac** — {platform.machine()} · macOS {platform.mac_ver()[0]}",
        f"Load: {load[0]:.2f} / {load[1]:.2f} / {load[2]:.2f}",
        f"RAM: {_memory_status()}",
        (
            f"Disco: {disk.used / 1024**3:.1f}/{disk.total / 1024**3:.1f} GB usati "
            f"({disk.used / disk.total * 100:.0f}%)"
        ),
        f"Batteria: {_battery_status()}",
    ]
    if code == 0 and uptime:
        lines.append(f"Uptime: {uptime}")
    if top:
        lines.append("Top processi per CPU:")
        lines.extend(f"• {row}" for row in top)
    return "\n".join(lines)
