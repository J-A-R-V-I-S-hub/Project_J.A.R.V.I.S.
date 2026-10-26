from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .knowledge import SUPPORTED_SUFFIXES, KnowledgeBase

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "data",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "dist",
    "build",
    ".ruff_cache",
    ".mypy_cache",
}


def repo_root(path: str | Path | None = None) -> Path:
    if path:
        return Path(path).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def _git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"(git non disponibile: {exc})"
    return (completed.stdout or completed.stderr).strip()


def repo_status(path: str | Path | None = None) -> str:
    root = repo_root(path)
    branch = _git(root, "branch", "--show-current") or "?"
    status = _git(root, "status", "--short") or "working tree pulito"
    commits = _git(root, "log", "--oneline", "-5") or "nessun commit"
    diffstat = _git(root, "diff", "--stat")
    lines = [
        f"🧑‍💻 **Repo** — `{root.name}`",
        f"Branch: `{branch}`",
        "",
        "**Ultimi commit**",
        commits,
        "",
        "**Stato**",
        status,
    ]
    if diffstat:
        lines.extend(["", "**Diff**", diffstat])
    return "\n".join(lines)


def search_code(query: str, path: str | Path | None = None, limit: int = 20) -> str:
    root = repo_root(path)
    if shutil.which("rg"):
        completed = subprocess.run(
            [
                "rg",
                "-n",
                "--no-heading",
                "--color",
                "never",
                "--max-count",
                str(limit),
                "--glob",
                "!data/**",
                "--glob",
                "!.venv/**",
                "--glob",
                "!**/__pycache__/**",
                query,
                str(root / "src"),
                str(root / "tests"),
                str(root / "README.md"),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        output = completed.stdout.strip()
        if output:
            return f"🔎 **Ricerca: {query}**\n```\n{output}\n```"
        return f"Nessun risultato per '{query}'."

    matches: list[str] = []
    for candidate in root.rglob("*"):
        if not candidate.is_file() or candidate.suffix not in SUPPORTED_SUFFIXES:
            continue
        if any(part in EXCLUDED_DIRS for part in candidate.parts):
            continue
        try:
            for number, line in enumerate(candidate.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
                if query.lower() in line.lower():
                    matches.append(f"{candidate.relative_to(root)}:{number}: {line.strip()}")
                    if len(matches) >= limit:
                        break
        except OSError:
            continue
        if len(matches) >= limit:
            break
    if not matches:
        return f"Nessun risultato per '{query}'."
    return f"🔎 **Ricerca: {query}**\n```\n" + "\n".join(matches) + "\n```"


def index_repository(knowledge: KnowledgeBase, path: str | Path | None = None, max_bytes: int = 1_000_000) -> str:
    root = repo_root(path)
    files = 0
    chunks = 0
    skipped = 0
    for candidate in root.rglob("*"):
        if not candidate.is_file() or candidate.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if any(part in EXCLUDED_DIRS for part in candidate.parts):
            continue
        try:
            if candidate.stat().st_size > max_bytes:
                skipped += 1
                continue
            chunks += knowledge.index_file(candidate)
            files += 1
        except Exception:
            skipped += 1
    return f"Indicizzati {files} file del repo in {chunks} chunk (saltati {skipped})."
