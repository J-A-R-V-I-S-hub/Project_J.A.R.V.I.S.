from jarvis_bot.presence import PresenceTracker


def test_presence_transitions() -> None:
    sequence = iter([True, True, False, False])
    tracker = PresenceTracker("192.168.1.10", ping=lambda ip: next(sequence))

    first = tracker.check()
    assert first.at_home is True
    assert first.changed is False

    second = tracker.check()
    assert second.at_home is True
    assert second.changed is False

    third = tracker.check()
    assert third.at_home is False
    assert third.changed is True


def test_presence_disabled() -> None:
    tracker = PresenceTracker(None)
    assert tracker.enabled is False
    assert "non configurato" in tracker.describe()
