from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


def _copy_sqlite(source: Path, target: Path) -> None:
    try:
        source_connection = sqlite3.connect(source)
        target_connection = sqlite3.connect(target)
        try:
            source_connection.backup(target_connection)
        finally:
            target_connection.close()
            source_connection.close()
    except sqlite3.Error:
        shutil.copy2(source, target)


def create_backup(data_dir: str | Path = "data", keep: int = 7) -> str:
    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = root / "backups" / stamp
    destination.mkdir(parents=True, exist_ok=True)

    copied = 0
    for database in sorted(root.glob("*.db")):
        _copy_sqlite(database, destination / database.name)
        copied += 1

    backups_root = root / "backups"
    existing = sorted(path for path in backups_root.iterdir() if path.is_dir())
    for old in existing[:-keep]:
        shutil.rmtree(old, ignore_errors=True)

    return f"Backup creato in {destination} ({copied} database, retention {keep})."
