import pytest

from jarvis_bot import sandbox


def test_docker_available_returns_bool() -> None:
    assert isinstance(sandbox.docker_available(), bool)


def test_run_python_docker_requires_docker(monkeypatch) -> None:
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError):
        sandbox.run_python_docker("print('ciao')")
