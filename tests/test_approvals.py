from datetime import UTC, datetime
from pathlib import Path

from jarvis_bot.approvals import Approval, ApprovalStore, execute_approval
from jarvis_bot.audit import AuditStore
from jarvis_bot.config import Settings


def test_audit_store_roundtrip(tmp_path: Path) -> None:
    store = AuditStore(tmp_path / "app.db")
    store.record("macos.open_app", "Safari")
    store.record("email.send", "a=test@example.com")

    entries = store.recent()
    assert len(entries) == 2
    assert entries[0].action == "email.send"
    assert "macos.open_app" in store.format_recent()


def test_approval_store_lifecycle(tmp_path: Path) -> None:
    store = ApprovalStore(tmp_path / "app.db")
    approval = store.request(1, "email.send", {"to": "a@b.c"}, "Email di prova")

    assert store.get(approval.id) is not None
    assert len(store.pending(1)) == 1
    assert store.approve(approval.id) is not None
    assert store.pending(1) == []

    second = store.request(1, "email.send", {"to": "a@b.c"}, "Altra email")
    assert store.cancel(second.id) is True
    assert store.cancel(second.id) is False


def test_execute_shell_approval(tmp_path: Path) -> None:
    settings = Settings(TELEGRAM_BOT_TOKEN="123:abc", OPENROUTER_API_KEY="sk-test")
    approval = Approval(
        id=1,
        chat_id=1,
        action="shell.run",
        payload={"command": "echo ciao"},
        description="Echo",
        status="approved",
        created_at=datetime.now(UTC).isoformat(),
    )

    assert "ciao" in execute_approval(approval, settings)
