from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class AttachmentType(str, Enum):
    AUDIO = "audio"
    IMAGE = "image"
    PDF = "pdf"
    CSV = "csv"
    XLSX = "xlsx"
    DOCUMENT = "document"


@dataclass(slots=True)
class Attachment:
    kind: AttachmentType
    local_path: Path
    mime_type: str | None = None
    original_name: str | None = None


@dataclass(slots=True)
class IncomingMessage:
    chat_id: int
    user_id: int
    text: str = ""
    attachments: list[Attachment] = field(default_factory=list)
    audio_transcript: str | None = None


@dataclass(slots=True)
class PendingArtifact:
    local_path: Path
    caption: str = ""


@dataclass(slots=True)
class PreparedAgentInput:
    prompt: str
    images: list[Any] = field(default_factory=list)
    csv_paths: list[Path] = field(default_factory=list)
    document_paths: list[Path] = field(default_factory=list)
    histogram_data: list[tuple[str, float]] = field(default_factory=list)
    infographic_descriptions: list[str] = field(default_factory=list)


class ChartSeries(BaseModel):
    """Una serie di valori da disegnare sopra le etichette del grafico."""

    label: str = Field(description="Nome della serie, ad esempio 'Difetti' o 'Categoria A'.")
    values: list[float] = Field(description="Un valore numerico per ogni etichetta in labels.")


class ChartSpec(BaseModel):
    """Specifica tipizzata di un grafico.

    Esempio:
        {
          "title": "Difetti per prodotto",
          "labels": ["A4636", "A2524"],
          "series": [{"label": "Difetti", "values": [37, 20]}],
          "chart_type": "bar"
        }
    """

    title: str = Field(description="Titolo del grafico.")
    labels: list[str] = Field(description="Etichette dell'asse X, una per valore.")
    series: list[ChartSeries] = Field(description="Una o più serie di valori.")
    chart_type: Literal["bar", "grouped_bar", "line", "pie", "pareto"] = Field(
        default="bar",
        description=(
            "Tipo di grafico: 'bar' barre singole, 'grouped_bar' barre raggruppate "
            "per più serie, 'line' linee, 'pie' torta, 'pareto' barre ordinate + cumulata."
        ),
    )
    x_label: str = Field(default="", description="Etichetta opzionale dell'asse X.")
    y_label: str = Field(default="Valore", description="Etichetta opzionale dell'asse Y.")
