import sqlite3
from pathlib import Path

from jarvis_bot.backup import create_backup


def test_create_backup_copies_databases(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database = data_dir / "jarvis.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE sample (id INTEGER)")
    connection.commit()
    connection.close()

    message = create_backup(data_dir, keep=7)

    backups = list((data_dir / "backups").iterdir())
    assert len(backups) == 1
    assert (backups[0] / "jarvis.db").exists()
    assert "Backup creato" in message
