from pathlib import Path

from jarvis_bot.agent import ArtifactQueue


def _queue(tmp_path: Path) -> ArtifactQueue:
    return ArtifactQueue(
        output_dir=tmp_path / "output",
        reports_dir=tmp_path / "reports",
        workspace_dir=tmp_path / "workspace",
    )


def test_send_local_file_allows_artifact_roots(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    artifact = tmp_path / "output" / "chart.png"
    artifact.write_bytes(b"png")

    result = queue.send_local_file(str(artifact))

    assert "accodato" in result
    assert len(queue.items) == 1


def test_send_local_file_rejects_paths_outside_roots(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")

    result = queue.send_local_file(str(secret))

    assert "non consentito" in result
    assert queue.items == []


def test_send_local_file_rejects_database_files(tmp_path: Path) -> None:
    queue = _queue(tmp_path)
    database = tmp_path / "workspace" / "jarvis.db"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"db")

    result = queue.send_local_file(str(database))

    assert "sicurezza" in result
    assert queue.items == []
