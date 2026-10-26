from pathlib import Path

from jarvis_bot.profile import ProfileStore


def test_profile_facts_goals_and_projects(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "app.db")
    store.remember("preferenze", "caffè", "amaro")
    store.remember("lavoro", "ruolo", "sviluppatore")

    facts = store.facts()
    assert len(facts) == 2
    assert "amaro" in store.format_facts()

    assert store.forget("preferenze", "caffè") is True
    assert len(store.facts()) == 1

    goal = store.add_goal("Riprendere Jarvis", "2026-12-31")
    assert store.goals()[0].title == "Riprendere Jarvis"
    assert store.complete_goal(goal.id) is True
    assert store.goals() == []

    project = store.add_project("Jarvis", "Assistente personale")
    assert project.name == "Jarvis"
    assert store.projects()[0].description == "Assistente personale"
    assert "Riprendere Jarvis" not in store.summary()
