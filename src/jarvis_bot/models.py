from __future__ import annotations

from .config import Settings

COMPLEX_HINTS = (
    "codice",
    "code",
    "python",
    "bug",
    "errore",
    "refactor",
    "test",
    "pr",
    "commit",
    "repo",
    "analizza",
    "analisi",
    "pdf",
    "csv",
    "excel",
    "grafico",
    "report",
    "simula",
    "architettura",
    "confronta",
)


def choose_model(
    text: str,
    settings: Settings,
    has_images: bool = False,
    has_attachments: bool = False,
) -> str:
    """Pick a model based on the request complexity and cost."""
    if has_images:
        return settings.openrouter_vision_model
    if not settings.model_routing_enabled:
        return settings.openrouter_model

    lowered = (text or "").lower()
    if (
        has_attachments
        or len(text or "") > 220
        or "```" in (text or "")
        or any(hint in lowered for hint in COMPLEX_HINTS)
    ):
        return settings.smart_model
    if len(text or "") <= 140:
        return settings.cheap_model
    return settings.openrouter_model
