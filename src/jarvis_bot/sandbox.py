from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def docker_available() -> bool:
    return shutil.which("docker") is not None


def run_python_docker(
    code: str,
    image: str = "python:3.12-slim",
    timeout: int = 30,
    memory: str = "256m",
    cpus: str = "0.5",
) -> str:
    """Execute Python code in a disposable, network-isolated Docker container."""
    if not docker_available():
        raise RuntimeError("Docker non installato o non nel PATH.")
    if not code.strip():
        raise ValueError("Codice Python vuoto.")

    with tempfile.TemporaryDirectory(prefix="jarvis-sandbox-") as directory:
        script = Path(directory) / "main.py"
        script.write_text(code, encoding="utf-8")
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--memory",
            memory,
            "--cpus",
            cpus,
            "-v",
            f"{directory}:/work:ro",
            "-w",
            "/work",
            image,
            "python",
            "main.py",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return f"⛔ Sandbox: timeout dopo {timeout}s."
        output = (completed.stdout or completed.stderr).strip()
        if not output:
            output = "Codice eseguito nella sandbox (nessun output)."
        return output[:4000]
