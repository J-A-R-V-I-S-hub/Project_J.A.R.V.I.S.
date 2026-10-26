from pathlib import Path

from jarvis_bot.protocols import ProtocolRunner, ProtocolStore


def test_protocol_store_seeds_defaults(tmp_path: Path) -> None:
    store = ProtocolStore(tmp_path / "app.db")
    names = {protocol.name for protocol in store.list()}

    assert {"lavoro", "focus", "buonanotte", "emergenza"} <= names
    assert store.get("lavoro") is not None


def test_protocol_upsert_and_delete(tmp_path: Path) -> None:
    store = ProtocolStore(tmp_path / "app.db")
    store.upsert("demo", "Protocollo demo", [{"type": "notify", "title": "Ciao", "message": "Fatto"}])

    protocol = store.get("demo")
    assert protocol is not None
    assert protocol.description == "Protocollo demo"
    assert store.delete("demo") is True
    assert store.get("demo") is None


def test_protocol_runner_executes_steps(tmp_path: Path, monkeypatch) -> None:
    store = ProtocolStore(tmp_path / "app.db")
    calls: list[tuple] = []

    monkeypatch.setattr("jarvis_bot.protocols.macos.open_app", lambda name: calls.append(("open", name)) or "ok")
    monkeypatch.setattr("jarvis_bot.protocols.macos.set_volume", lambda level: calls.append(("volume", level)) or "ok")
    monkeypatch.setattr(
        "jarvis_bot.protocols.macos.notify",
        lambda title, message: calls.append(("notify", title, message)) or "ok",
    )

    protocol = store.upsert(
        "test",
        "Test",
        [
            {"type": "open_app", "value": "Safari"},
            {"type": "volume", "value": 25},
            {"type": "notify", "title": "Titolo", "message": "Messaggio"},
        ],
    )
    results = ProtocolRunner().run(protocol)

    assert len(results) == 3
    assert calls == [("open", "Safari"), ("volume", 25), ("notify", "Titolo", "Messaggio")]
