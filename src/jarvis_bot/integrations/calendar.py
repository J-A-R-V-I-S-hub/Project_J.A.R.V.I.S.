from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx


@dataclass(slots=True)
class CalendarEvent:
    summary: str
    start: datetime
    end: datetime | None
    location: str


def _unfold(text: str) -> str:
    return re.sub(r"\r?\n[ \t]", "", text)


def _parse_datetime(value: str, tzid: str | None, default_tz: ZoneInfo) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        parsed = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    elif "T" in raw:
        parsed = datetime.strptime(raw, "%Y%m%dT%H%M%S")
        zone = ZoneInfo(tzid) if tzid else default_tz
        parsed = parsed.replace(tzinfo=zone)
    else:
        parsed = datetime.strptime(raw, "%Y%m%d").replace(tzinfo=default_tz)
    return parsed.astimezone(default_tz)


def parse_ics(text: str, timezone_name: str = "Europe/Rome") -> list[CalendarEvent]:
    default_tz = ZoneInfo(timezone_name)
    events: list[CalendarEvent] = []
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", _unfold(text), re.DOTALL):
        properties: dict[str, tuple[str, str | None]] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            parts = key.split(";")
            name = parts[0].upper()
            tzid = None
            for part in parts[1:]:
                if part.upper().startswith("TZID="):
                    tzid = part.split("=", 1)[1]
            properties[name] = (value, tzid)

        if "DTSTART" not in properties:
            continue
        start_value, start_tzid = properties["DTSTART"]
        try:
            start = _parse_datetime(start_value, start_tzid, default_tz)
        except ValueError:
            continue

        end = None
        if "DTEND" in properties:
            end_value, end_tzid = properties["DTEND"]
            try:
                end = _parse_datetime(end_value, end_tzid, default_tz)
            except ValueError:
                end = None

        summary = properties.get("SUMMARY", ("(senza titolo)", None))[0].strip()
        location = properties.get("LOCATION", ("", None))[0].strip()
        events.append(CalendarEvent(summary=summary, start=start, end=end, location=location))
    return sorted(events, key=lambda event: event.start)


def load_events(source: str, timezone_name: str = "Europe/Rome") -> list[CalendarEvent]:
    if source.startswith(("http://", "https://")):
        response = httpx.get(source, timeout=25, follow_redirects=True)
        response.raise_for_status()
        text = response.text
    else:
        text = Path(source).expanduser().read_text(encoding="utf-8", errors="ignore")
    return parse_ics(text, timezone_name)


def upcoming_events(source: str, timezone_name: str = "Europe/Rome", limit: int = 10) -> str:
    """Legge un calendario ICS (URL o file locale) e mostra i prossimi eventi.

    Nota: le ricorrenze RRULE non vengono espanse in questa versione.
    """
    try:
        events = load_events(source, timezone_name)
    except Exception as exc:
        return f"Calendario non raggiungibile: {exc}"

    tz = ZoneInfo(timezone_name)
    now = datetime.now(tz)
    upcoming = [event for event in events if event.start >= now]
    if not upcoming:
        return "Nessun evento imminente nel calendario."

    lines = ["📅 **Prossimi eventi**"]
    for event in upcoming[:limit]:
        line = f"• {event.start.strftime('%d/%m %H:%M')} — {event.summary}"
        if event.location:
            line += f" ({event.location})"
        lines.append(line)
    return "\n".join(lines)
