from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(slots=True)
class ProfileFact:
    category: str
    key: str
    value: str
    updated_at: str


@dataclass(slots=True)
class Goal:
    id: int
    title: str
    status: str
    due_at: str
    created_at: str


@dataclass(slots=True)
class Project:
    id: int
    name: str
    status: str
    description: str
    created_at: str


class ProfileStore:
    """Structured long-term profile: facts, goals and projects."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS profile_facts (
                    category TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (category, key)
                );
                CREATE TABLE IF NOT EXISTS goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    due_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'active',
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                """
            )
            connection.commit()
        finally:
            connection.close()

    def remember(self, category: str, key: str, value: str) -> ProfileFact:
        now = datetime.now(UTC).isoformat()
        category = category.strip().lower() or "generale"
        key = key.strip().lower() or "nota"
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO profile_facts (category, key, value, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(category, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (category, key, value.strip(), now),
            )
            connection.commit()
        finally:
            connection.close()
        return ProfileFact(category, key, value.strip(), now)

    def forget(self, category: str, key: str) -> bool:
        connection = self._connect()
        try:
            cursor = connection.execute(
                "DELETE FROM profile_facts WHERE category = ? AND key = ?",
                (category.strip().lower(), key.strip().lower()),
            )
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()

    def facts(self, category: str | None = None) -> list[ProfileFact]:
        connection = self._connect()
        try:
            if category:
                rows = connection.execute(
                    "SELECT * FROM profile_facts WHERE category = ? ORDER BY key",
                    (category.strip().lower(),),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM profile_facts ORDER BY category, key"
                ).fetchall()
        finally:
            connection.close()
        return [
            ProfileFact(row["category"], row["key"], row["value"], row["updated_at"])
            for row in rows
        ]

    def add_goal(self, title: str, due_at: str = "") -> Goal:
        now = datetime.now(UTC).isoformat()
        connection = self._connect()
        try:
            cursor = connection.execute(
                "INSERT INTO goals (title, status, due_at, created_at) VALUES (?, 'open', ?, ?)",
                (title.strip(), due_at.strip(), now),
            )
            connection.commit()
            goal_id = int(cursor.lastrowid)
        finally:
            connection.close()
        return Goal(goal_id, title.strip(), "open", due_at.strip(), now)

    def goals(self, include_done: bool = False) -> list[Goal]:
        connection = self._connect()
        try:
            query = "SELECT * FROM goals"
            if not include_done:
                query += " WHERE status = 'open'"
            query += " ORDER BY id"
            rows = connection.execute(query).fetchall()
        finally:
            connection.close()
        return [Goal(row["id"], row["title"], row["status"], row["due_at"], row["created_at"]) for row in rows]

    def complete_goal(self, goal_id: int) -> bool:
        connection = self._connect()
        try:
            cursor = connection.execute(
                "UPDATE goals SET status = 'done' WHERE id = ? AND status = 'open'", (goal_id,)
            )
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()

    def add_project(self, name: str, description: str = "") -> Project:
        now = datetime.now(UTC).isoformat()
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO projects (name, status, description, created_at) VALUES (?, 'active', ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET description = excluded.description",
                (name.strip(), description.strip(), now),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM projects WHERE name = ?", (name.strip(),)).fetchone()
        finally:
            connection.close()
        assert row is not None
        return Project(row["id"], row["name"], row["status"], row["description"], row["created_at"])

    def projects(self) -> list[Project]:
        connection = self._connect()
        try:
            rows = connection.execute("SELECT * FROM projects ORDER BY name").fetchall()
        finally:
            connection.close()
        return [
            Project(row["id"], row["name"], row["status"], row["description"], row["created_at"])
            for row in rows
        ]

    def summary(self, limit: int = 20) -> str:
        facts = self.facts()[:limit]
        goals = self.goals()
        projects = self.projects()
        lines: list[str] = []
        if facts:
            lines.append("Fatti sul profilo:")
            for fact in facts:
                lines.append(f"• [{fact.category}] {fact.key}: {fact.value}")
        if goals:
            lines.append("Obiettivi aperti:")
            for goal in goals[:10]:
                suffix = f" (scadenza {goal.due_at})" if goal.due_at else ""
                lines.append(f"• #{goal.id} {goal.title}{suffix}")
        if projects:
            lines.append("Progetti:")
            for project in projects[:10]:
                lines.append(f"• {project.name}: {project.description or 'nessuna descrizione'}")
        return "\n".join(lines) if lines else "Profilo ancora vuoto."

    def format_facts(self, category: str | None = None) -> str:
        facts = self.facts(category)
        if not facts:
            return "Nessun fatto salvato."
        lines = ["🧠 **Profilo**"]
        current = None
        for fact in facts:
            if fact.category != current:
                current = fact.category
                lines.append(f"\n**{current}**")
            lines.append(f"• {fact.key}: {fact.value}")
        return "\n".join(lines)
