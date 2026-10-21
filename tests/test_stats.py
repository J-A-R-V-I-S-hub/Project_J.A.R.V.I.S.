import json
import sqlite3
from pathlib import Path

from jarvis_bot.stats import collect_stats, format_stats


def test_collect_stats_reads_double_encoded_runs(tmp_path: Path) -> None:
    db_path = tmp_path / "jarvis.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE agno_sessions (runs TEXT, updated_at TEXT)")
    runs = [
        {
            "model": "openai/gpt-4.1-mini",
            "metrics":{"input_tokens": 100, "output_tokens": 20, "total_tokens": 120, "duration": 3.5},
            "tools": ["web_search", "create_chart"],
            "messages": [],
        }
    ]
    connection.execute(
        "INSERT INTO agno_sessions VALUES (?, ?)",
        (json.dumps(json.dumps(runs)), "2026-10-21T10:00:00"),
    )
    connection.commit()
    connection.close()

    stats = collect_stats(db_path)

    assert stats.sessions == 1
    assert stats.runs == 1
    assert stats.total_tokens == 120
    assert stats.tools["web_search"] == 1
    assert "Token: 120" in format_stats(stats)


def test_collect_stats_handles_missing_db(tmp_path: Path) -> None:
    stats = collect_stats(tmp_path / "missing.db")
    assert stats.runs == 0
    assert "Nessuna attività" in format_stats(stats)
