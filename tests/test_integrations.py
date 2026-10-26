from pathlib import Path

from jarvis_bot.integrations.calendar import parse_ics, upcoming_events
from jarvis_bot.integrations.email import _decode_header_value
from jarvis_bot.integrations.github import GitHubClient
from jarvis_bot.integrations.notion import NotionClient

ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
SUMMARY:Revisione qualità
DTSTART;TZID=Europe/Rome:20991022T090000
DTEND;TZID=Europe/Rome:20991022T100000
LOCATION:Ufficio
END:VEVENT
BEGIN:VEVENT
SUMMARY:Evento passato
DTSTART:20200101T090000Z
END:VEVENT
END:VCALENDAR
"""


def test_parse_ics_reads_events() -> None:
    events = parse_ics(ICS)

    assert len(events) == 2
    by_summary = {event.summary: event for event in events}
    assert by_summary["Revisione qualità"].location == "Ufficio"
    assert by_summary["Revisione qualità"].start.year == 2099
    assert "Evento passato" in by_summary


def test_upcoming_events_filters_past(tmp_path: Path) -> None:
    calendar = tmp_path / "calendar.ics"
    calendar.write_text(ICS, encoding="utf-8")

    result = upcoming_events(str(calendar))

    assert "Revisione qualità" in result
    assert "Evento passato" not in result


def test_github_repo_resolution() -> None:
    client = GitHubClient("token", "owner/repo")
    assert client._repo(None) == "owner/repo"
    assert client._repo("other/repo") == "other/repo"


def test_notion_title_extraction() -> None:
    client = NotionClient("token")
    item = {
        "object": "page",
        "properties": {"Name": {"type": "title", "title": [{"plain_text": "Nota di prova"}]}},
    }
    assert client._title_of(item) == "Nota di prova"


def test_email_header_decoding() -> None:
    assert _decode_header_value("=?utf-8?q?Ciao_mondo?=") == "Ciao mondo"
