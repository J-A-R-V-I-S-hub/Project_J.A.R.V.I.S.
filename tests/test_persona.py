from jarvis_bot.persona import normalize_persona, persona_choices, persona_instructions


def test_normalize_persona_falls_back_to_default() -> None:
    assert normalize_persona("stark") == "stark"
    assert normalize_persona("inesistente") == "butler"
    assert normalize_persona(None) == "butler"


def test_persona_instructions_include_address() -> None:
    lines = persona_instructions("butler", "Capo")
    text = " ".join(lines)
    assert "Capo" in text
    assert "maggiordomo" in text


def test_persona_choices_are_sorted() -> None:
    choices = persona_choices()
    assert choices == sorted(choices)
    assert "butler" in choices
