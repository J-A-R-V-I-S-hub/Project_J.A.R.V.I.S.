from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SUPPORTED_SUFFIXES = {
    ".pdf",
    ".docx",
    ".txt",
    ".md",
    ".csv",
    ".xlsx",
    ".xls",
    ".json",
    ".py",
    ".log",
}

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class KnowledgeHit:
    source: str
    text: str
    rank: float


def extract_text(path: Path) -> str:
    """Extract plain text from a supported document."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".docx":
        from docx import Document

        document = Document(str(path))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    if suffix in {".csv", ".xlsx", ".xls"}:
        from .attachments import load_table

        return load_table(path).to_csv(index=False)
    if suffix == ".json":
        try:
            return json.dumps(json.loads(path.read_text(encoding="utf-8", errors="ignore")), ensure_ascii=False, indent=2)
        except ValueError:
            return path.read_text(encoding="utf-8", errors="ignore")
    return path.read_text(encoding="utf-8", errors="ignore")


def chunk_text(text: str, chunk_chars: int = 1200, overlap: int = 200) -> list[str]:
    cleaned = re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n")).strip()
    if not cleaned:
        return []

    chunks: list[str] = []
    start = 0
    length = len(cleaned)
    while start < length:
        end = min(start + chunk_chars, length)
        if end < length:
            window = cleaned[start:end]
            boundary = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("\n"))
            if boundary > chunk_chars // 2:
                end = start + boundary + 1
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return chunks


class KnowledgeBase:
    """Lightweight document knowledge base backed by SQLite FTS5."""

    def __init__(self, db_path: str | Path, chunk_chars: int = 1200, overlap: int = 200) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.chunk_chars = chunk_chars
        self.overlap = overlap
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _init_schema(self) -> None:
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    title TEXT,
                    mtime REAL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL,
                    ordinal INTEGER NOT NULL,
                    text TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
                    USING fts5(text, source UNINDEXED, chunk_id UNINDEXED);
                """
            )
            connection.commit()
        finally:
            connection.close()

    def index_file(self, path: str | Path, source: str | None = None) -> int:
        file_path = Path(path).expanduser().resolve()
        if not file_path.is_file():
            raise FileNotFoundError(f"Documento non trovato: {file_path}")
        if file_path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ValueError(f"Formato non supportato per la knowledge base: {file_path.suffix}")

        text = extract_text(file_path)
        chunks = chunk_text(text, self.chunk_chars, self.overlap)
        if not chunks:
            return 0

        resolved = str(file_path)
        source_name = source or file_path.name
        now = datetime.now(UTC).isoformat()

        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT id FROM knowledge_documents WHERE path = ?", (resolved,)
            ).fetchone()
            if row:
                document_id = int(row[0])
                chunk_ids = [r[0] for r in connection.execute(
                    "SELECT id FROM knowledge_chunks WHERE document_id = ?", (document_id,)
                )]
                for chunk_id in chunk_ids:
                    connection.execute("DELETE FROM knowledge_fts WHERE chunk_id = ?", (chunk_id,))
                connection.execute("DELETE FROM knowledge_chunks WHERE document_id = ?", (document_id,))
                connection.execute("DELETE FROM knowledge_documents WHERE id = ?", (document_id,))

            cursor = connection.execute(
                "INSERT INTO knowledge_documents (path, source, title, mtime, created_at) VALUES (?, ?, ?, ?, ?)",
                (resolved, source_name, file_path.stem, file_path.stat().st_mtime, now),
            )
            document_id = int(cursor.lastrowid)

            for ordinal, chunk in enumerate(chunks):
                chunk_cursor = connection.execute(
                    "INSERT INTO knowledge_chunks (document_id, ordinal, text) VALUES (?, ?, ?)",
                    (document_id, ordinal, chunk),
                )
                connection.execute(
                    "INSERT INTO knowledge_fts (text, source, chunk_id) VALUES (?, ?, ?)",
                    (chunk, source_name, int(chunk_cursor.lastrowid)),
                )
            connection.commit()
            return len(chunks)
        finally:
            connection.close()

    def index_directory(self, directory: str | Path) -> tuple[int, int]:
        root = Path(directory)
        if not root.exists():
            return 0, 0
        files = 0
        total_chunks = 0
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            if any(part.startswith(".") for part in path.parts):
                continue
            try:
                total_chunks += self.index_file(path)
                files += 1
            except Exception:
                LOGGER.warning("Could not index %s", path, exc_info=True)
        return files, total_chunks

    @staticmethod
    def _match_query(query: str) -> str | None:
        tokens = [token for token in re.findall(r"[0-9A-Za-zÀ-ÿ_]+", query.lower()) if len(token) > 1]
        if not tokens:
            return None
        return " OR ".join(f'"{token}"' for token in tokens)

    def search(self, query: str, limit: int = 5) -> list[KnowledgeHit]:
        match = self._match_query(query)
        if match is None:
            return []
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT source, text, rank FROM knowledge_fts "
                "WHERE knowledge_fts MATCH ? ORDER BY rank LIMIT ?",
                (match, limit),
            ).fetchall()
        finally:
            connection.close()
        return [KnowledgeHit(source=str(row[0]), text=str(row[1]), rank=float(row[2])) for row in rows]

    def list_sources(self) -> list[tuple[str, int]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT d.source, COUNT(c.id) FROM knowledge_documents d "
                "LEFT JOIN knowledge_chunks c ON c.document_id = d.id "
                "GROUP BY d.id ORDER BY d.source"
            ).fetchall()
        finally:
            connection.close()
        return [(str(row[0]), int(row[1])) for row in rows]

    def delete_source(self, source: str) -> int:
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT id FROM knowledge_documents WHERE source = ?", (source,)
            ).fetchall()
            deleted = 0
            for (document_id,) in rows:
                chunk_ids = [r[0] for r in connection.execute(
                    "SELECT id FROM knowledge_chunks WHERE document_id = ?", (document_id,)
                )]
                for chunk_id in chunk_ids:
                    connection.execute("DELETE FROM knowledge_fts WHERE chunk_id = ?", (chunk_id,))
                connection.execute("DELETE FROM knowledge_chunks WHERE document_id = ?", (document_id,))
                connection.execute("DELETE FROM knowledge_documents WHERE id = ?", (document_id,))
                deleted += 1
            connection.commit()
            return deleted
        finally:
            connection.close()


def format_hits(hits: list[KnowledgeHit], max_chars: int = 400) -> str:
    if not hits:
        return "Nessun documento pertinente trovato."
    lines = ["📚 **Risultati dalla knowledge base**"]
    for index, hit in enumerate(hits, start=1):
        snippet = " ".join(hit.text.split())
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars].rstrip() + "…"
        lines.append(f"{index}. **{hit.source}** — {snippet}")
    return "\n\n".join(lines)


def format_sources(sources: list[tuple[str, int]]) -> str:
    if not sources:
        return "La knowledge base è vuota. Usa /index oppure invia un PDF/DOCX."
    lines = ["📚 **Documenti indicizzati**"]
    for source, chunks in sources:
        lines.append(f"• {source} — {chunks} chunk")
    return "\n".join(lines)


def search_context(hits: list[KnowledgeHit]) -> str:
    if not hits:
        return ""
    blocks = []
    for index, hit in enumerate(hits, start=1):
        blocks.append(f"[{index}] {hit.source}\n{hit.text}")
    return "\n\n".join(blocks)
