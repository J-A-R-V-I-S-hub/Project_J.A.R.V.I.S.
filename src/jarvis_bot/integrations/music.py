from __future__ import annotations

from .macos import _escape, _osascript, on_macos


def _tell(app: str, command: str) -> str:
    return _osascript(f'tell application "{_escape(app)}" to {command}')


def play(app: str = "Music") -> str:
    if not on_macos():
        return "Controllo musica disponibile solo su macOS."
    try:
        _tell(app, "play")
    except Exception as exc:
        return f"Musica non avviata: {exc}"
    return f"Riproduzione avviata ({app})."


def pause(app: str = "Music") -> str:
    if not on_macos():
        return "Controllo musica disponibile solo su macOS."
    try:
        _tell(app, "pause")
    except Exception as exc:
        return f"Musica non messa in pausa: {exc}"
    return "Musica in pausa."


def play_pause(app: str = "Music") -> str:
    if not on_macos():
        return "Controllo musica disponibile solo su macOS."
    try:
        _tell(app, "playpause")
    except Exception as exc:
        return f"Comando non riuscito: {exc}"
    return "Play/pausa eseguito."


def next_track(app: str = "Music") -> str:
    try:
        _tell(app, "next track")
    except Exception as exc:
        return f"Comando non riuscito: {exc}"
    return "Brano successivo."


def previous_track(app: str = "Music") -> str:
    try:
        _tell(app, "previous track")
    except Exception as exc:
        return f"Comando non riuscito: {exc}"
    return "Brano precedente."


def current_track(app: str = "Music") -> str:
    if not on_macos():
        return "Controllo musica disponibile solo su macOS."
    try:
        state = _tell(app, "player state as string")
        title = _tell(app, "name of current track")
        artist = _tell(app, "artist of current track")
    except Exception as exc:
        return f"Nessun brano disponibile: {exc}"
    return f"🎵 {title} — {artist} ({state})"


def set_volume(app: str, level: int) -> str:
    if not on_macos():
        return "Controllo musica disponibile solo su macOS."
    clamped = max(0, min(100, int(level)))
    try:
        _tell(app, f"set sound volume to {clamped}")
    except Exception as exc:
        return f"Volume musica non impostato: {exc}"
    return f"Volume {app} al {clamped}%."
