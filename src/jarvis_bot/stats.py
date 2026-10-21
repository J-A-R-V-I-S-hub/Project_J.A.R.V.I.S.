from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class Stats:
    sessions: int = 0
    runs: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    duration: float = 0.0
    models: Counter = field(default_factory=Counter)
    tools: Counter = field(default_factory=Counter)
    last_activity: datetime | None = None


def _decode_runs(raw: object) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return []
    return data if isinstance(data, list) else []


def _tool_name(tool: object) -> str | None:
    if isinstance(tool, str):
        return tool
    if isinstance(tool, dict):
        function = tool.get("function")
        if isinstance(function, dict) and function.get("name"):
            return str(function["name"])
        if tool.get("name"):
            return str(tool["name"])
    return None


def collect_stats(db_path: str | Path) -> Stats:
    stats = Stats()
    path = Path(db_path)
    if not path.exists():
        return stats

    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return stats

    try:
        rows = connection.execute("SELECT runs, updated_at FROM agno_sessions").fetchall()
    except sqlite3.Error:
        connection.close()
        return stats

    for raw_runs, updated_at in rows:
        runs = _decode_runs(raw_runs)
        stats.sessions += 1
        for run in runs:
            if not isinstance(run, dict):
                continue
            stats.runs += 1

            metrics = run.get("metrics") or {}
            stats.input_tokens += int(metrics.get("input_tokens") or 0)
            stats.output_tokens += int(metrics.get("output_tokens") or 0)
            stats.total_tokens += int(metrics.get("total_tokens") or 0)
            stats.duration += float(metrics.get("duration") or 0)

            model = run.get("model")
            if model:
                stats.models[str(model)] += 1

            for tool in run.get("tools") or []:
                name = _tool_name(tool)
                if name:
                    stats.tools[name] += 1

            for message in run.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                for call in message.get("tool_calls") or []:
                    name = _tool_name(call)
                    if name:
                        stats.tools[name] += 1

        timestamp = updated_at
        if isinstance(timestamp, (int, float)):
            moment = datetime.fromtimestamp(timestamp)
        elif isinstance(timestamp, str):
            try:
                moment = datetime.fromisoformat(timestamp)
            except ValueError:
                moment = None
        else:
            moment = None
        if moment and (stats.last_activity is None or moment > stats.last_activity):
            stats.last_activity = moment

    connection.close()
    return stats


def format_stats(stats: Stats) -> str:
    if not stats.runs:
        return "📊 Nessuna attività registrata finora."

    average = stats.duration / stats.runs if stats.runs else 0
    lines = [
        "📊 **Statistiche Jarvis**",
        f"Sessioni: {stats.sessions}",
        f"Run: {stats.runs}",
        f"Token: {stats.total_tokens:,} (input {stats.input_tokens:,} / output {stats.output_tokens:,})",
        f"Tempo modello: {stats.duration:.1f}s (media {average:.1f}s)",
    ]
    if stats.models:
        lines.append("Modelli: " + ", ".join(f"{name} ({count})" for name, count in stats.models.most_common(3)))
    if stats.tools:
        lines.append("Tool: " + ", ".join(f"{name} ({count})" for name, count in stats.tools.most_common(6)))
    if stats.last_activity:
        lines.append("Ultima attività: " + stats.last_activity.strftime("%d/%m/%Y %H:%M"))
    return "\n".join(lines)
