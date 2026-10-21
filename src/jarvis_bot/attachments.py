from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from agno.media import Image
from pypdf import PdfReader

from .schemas import AttachmentType, IncomingMessage, PreparedAgentInput

MAX_TEXT_CHARS = 6000
INDEXABLE_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx", ".xls", ".json"}


@dataclass(slots=True)
class CsvInsight:
    text: str
    histogram_data: list[tuple[str, float]] = field(default_factory=list)
    descriptions: list[str] = field(default_factory=list)


def _truncate(value: str, limit: int = MAX_TEXT_CHARS) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[contenuto troncato]"


def extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    chunks: list[str] = []
    for page in reader.pages:
        chunks.append(page.extract_text() or "")
    return _truncate("\n".join(chunks))


def load_table(path: Path):
    """Load a CSV or Excel file into a pandas DataFrame."""
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path)


def analyse_csv(path: Path) -> CsvInsight:
    frame = load_table(path)
    head = frame.head(10).to_csv(index=False).strip()
    lines = [
        f"Tabella allegata: {path.name}",
        f"Righe: {len(frame)}",
        f"Colonne: {', '.join(frame.columns.astype(str).tolist())}",
        "Anteprima:",
        head,
    ]

    histogram_data: list[tuple[str, float]] = []
    descriptions: list[str] = []

    numeric_columns = frame.select_dtypes(include="number").columns.tolist()
    if numeric_columns:
        column = numeric_columns[0]
        series = frame[column].dropna().head(8)
        histogram_data = [(str(index + 1), float(value)) for index, value in enumerate(series.tolist())]
        descriptions.append(
            f"L'istogramma mostra i primi valori numerici della colonna '{column}', utile per cogliere rapidamente scala e variazioni."
        )
    else:
        category_columns = frame.select_dtypes(exclude="number").columns.tolist()
        if category_columns:
            column = category_columns[0]
            counts = frame[column].astype(str).value_counts().head(8)
            histogram_data = [(str(label), float(value)) for label, value in counts.items()]
            descriptions.append(
                f"L'istogramma rappresenta la frequenza delle categorie principali nella colonna '{column}', così da evidenziare i valori più ricorrenti."
            )

    return CsvInsight(text=_truncate("\n".join(lines)), histogram_data=histogram_data, descriptions=descriptions)


def default_user_instruction(message: IncomingMessage) -> str:
    if message.attachments and not message.text.strip():
        kinds = {attachment.kind for attachment in message.attachments}
        if AttachmentType.CSV in kinds:
            return "Analizza il CSV allegato, spiega i dati in modo semplice e prepara anche un eventuale export PDF con istogrammi comprensibili."
        if AttachmentType.XLSX in kinds:
            return "Analizza il foglio Excel allegato, spiega i dati in modo semplice e prepara anche un eventuale export PDF con grafici comprensibili."
        if AttachmentType.PDF in kinds:
            return "Riassumi il PDF allegato, estrai i punti chiave e proponi un report PDF finale se utile."
        if AttachmentType.IMAGE in kinds:
            return "Descrivi e analizza l'immagine allegata in dettaglio."
        if AttachmentType.AUDIO in kinds:
            return "Usa la trascrizione audio allegata come input principale e rispondi in modo operativo."
    return message.text.strip() or "Rispondi in modo utile e operativo."


def prepare_agent_input(message: IncomingMessage) -> PreparedAgentInput:
    prompt_sections = [
        "Sei Jarvis, un assistente AI privato ispirato all'AI di Tony Stark.",
        "Rispondi in italiano, in modo conciso ma concreto.",
    ]
    images: list[Image] = []
    csv_paths: list[Path] = []
    document_paths: list[Path] = []
    histogram_data: list[tuple[str, float]] = []
    infographic_descriptions: list[str] = []

    if message.audio_transcript:
        prompt_sections.append("Trascrizione audio:\n" + _truncate(message.audio_transcript))

    for attachment in message.attachments:
        if attachment.kind is not AttachmentType.AUDIO and attachment.local_path.suffix.lower() in INDEXABLE_SUFFIXES:
            document_paths.append(attachment.local_path)
        if attachment.kind is AttachmentType.IMAGE:
            images.append(Image(filepath=str(attachment.local_path)))
            prompt_sections.append(f"Immagine allegata disponibile in locale: {attachment.local_path.name}")
        elif attachment.kind is AttachmentType.PDF:
            try:
                extracted = extract_pdf_text(attachment.local_path)
            except Exception as exc:  # pragma: no cover - defensive path
                extracted = f"Impossibile estrarre il PDF: {exc}"
            prompt_sections.append(f"Contenuto estratto dal PDF {attachment.local_path.name}:\n{extracted}")
        elif attachment.kind is AttachmentType.CSV or attachment.kind is AttachmentType.XLSX:
            insight = analyse_csv(attachment.local_path)
            csv_paths.append(attachment.local_path)
            prompt_sections.append(insight.text)
            prompt_sections.append(f"Percorso locale della tabella: {attachment.local_path}")
            if insight.histogram_data and not histogram_data:
                histogram_data = insight.histogram_data
            infographic_descriptions.extend(insight.descriptions)
        else:
            prompt_sections.append(f"File allegato disponibile in locale: {attachment.local_path.name}")

    prompt_sections.append("Richiesta utente:\n" + default_user_instruction(message))

    return PreparedAgentInput(
        prompt="\n\n".join(section for section in prompt_sections if section.strip()),
        images=images,
        csv_paths=csv_paths,
        document_paths=document_paths,
        histogram_data=histogram_data,
        infographic_descriptions=infographic_descriptions,
    )
