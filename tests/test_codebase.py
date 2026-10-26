from pathlib import Path

from jarvis_bot.codebase import index_repository, repo_status, search_code
from jarvis_bot.knowledge import KnowledgeBase


def test_repo_status_reads_git() -> None:
    status = repo_status()
    assert "Branch" in status
    assert "Repo" in status


def test_search_code_finds_function() -> None:
    result = search_code("def build_status")
    assert "dashboard.py" in result


def test_index_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    (repository / "src").mkdir(parents=True)
    (repository / "src" / "sample.py").write_text("def hello():\n    return 'ciao'\n", encoding="utf-8")

    knowledge = KnowledgeBase(tmp_path / "knowledge.db")
    message = index_repository(knowledge, repository)

    assert "1 file" in message
    hits = knowledge.search("hello")
    assert hits
    assert hits[0].source == "sample.py"
