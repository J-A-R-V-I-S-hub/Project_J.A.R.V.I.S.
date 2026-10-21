from pathlib import Path

import pytest

from jarvis_bot.knowledge import KnowledgeBase, chunk_text, format_hits, format_sources


def test_chunk_text_splits_long_documents() -> None:
    text = ("Frase di prova. " * 200).strip()
    chunks = chunk_text(text, chunk_chars=300, overlap=50)

    assert len(chunks) > 1
    assert all(len(chunk) <= 360 for chunk in chunks)


def test_index_search_and_reindex(tmp_path: Path) -> None:
    db_path = tmp_path / "knowledge.db"
    document = tmp_path / "note.md"
    document.write_text(
        "Jarvis analizza i difetti di saldatura per prodotto.\n\n"
        "La categoria A contiene i difetti più frequenti.",
        encoding="utf-8",
    )

    knowledge = KnowledgeBase(db_path)
    assert knowledge.index_file(document) > 0
    sources = knowledge.list_sources()
    assert len(sources) == 1
    assert sources[0][0] == "note.md"

    hits = knowledge.search("saldatura")
    assert hits
    assert hits[0].source == "note.md"
    assert "note.md" in format_hits(hits)

    knowledge.index_file(document)
    sources = knowledge.list_sources()
    assert len(sources) == 1


def test_unsupported_format_is_rejected(tmp_path: Path) -> None:
    knowledge = KnowledgeBase(tmp_path / "knowledge.db")
    unsupported = tmp_path / "file.bin"
    unsupported.write_bytes(b"binary")

    with pytest.raises(ValueError):
        knowledge.index_file(unsupported)


def test_format_sources_empty(tmp_path: Path) -> None:
    knowledge = KnowledgeBase(tmp_path / "knowledge.db")
    assert "vuota" in format_sources(knowledge.list_sources())
