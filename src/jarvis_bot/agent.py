from __future__ import annotations

import json
from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Audio
from agno.memory import MemoryManager
from agno.models.openrouter import OpenRouterResponses
from agno.tools.csv_toolkit import CsvTools
from agno.tools.file import FileTools
from agno.tools.hackernews import HackerNewsTools
from agno.tools.local_file_system import LocalFileSystemTools
from agno.tools.python import PythonTools
from agno.tools.shell import ShellTools
from agno.tools.websearch import WebSearchTools

from .attachments import prepare_agent_input
from .config import Settings
from .reporting import build_pdf_report, create_histogram_png, slugify_filename, write_csv_file
from .schemas import IncomingMessage, PendingArtifact


class ArtifactQueue:
    """Collect files the agent wants to send back to Telegram."""

    def __init__(self, output_dir: Path, reports_dir: Path) -> None:
        self.output_dir = output_dir
        self.reports_dir = reports_dir
        self.items: list[PendingArtifact] = []
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def _queue_if_requested(self, path: Path, caption: str, queue_for_delivery: bool) -> None:
        if queue_for_delivery:
            self.items.append(PendingArtifact(local_path=path, caption=caption))

    def send_local_file(self, local_path: str, caption: str = "") -> str:
        path = Path(local_path).expanduser().resolve()
        if not path.exists():
            return f"File non trovato: {path}"
        self.items.append(PendingArtifact(local_path=path, caption=caption))
        return f"File accodato per l'invio su Telegram: {path.name}"

    def create_pdf_report(
        self,
        title: str,
        body: str,
        chart_data_json: str = "",
        chart_title: str = "Istogramma",
        infographic_description: str = "",
        file_name: str = "jarvis-report.pdf",
        caption: str = "",
        queue_for_delivery: bool = True,
    ) -> str:
        safe_name = slugify_filename(file_name, "jarvis-report.pdf")
        if not safe_name.endswith(".pdf"):
            safe_name += ".pdf"
        descriptions = [line.strip() for line in infographic_description.splitlines() if line.strip()]
        report_path = self.reports_dir / safe_name
        build_pdf_report(
            report_path,
            title=title,
            summary=body,
            histogram_title=chart_title,
            histogram_data=chart_data_json or None,
            infographic_descriptions=descriptions,
        )
        self._queue_if_requested(report_path, caption or title, queue_for_delivery)
        return str(report_path)

    def create_histogram_image(
        self,
        title: str,
        chart_data_json: str,
        file_name: str = "jarvis-chart.png",
        caption: str = "",
        queue_for_delivery: bool = True,
    ) -> str:
        safe_name = slugify_filename(file_name, "jarvis-chart.png")
        if not safe_name.endswith(".png"):
            safe_name += ".png"
        image_path = self.output_dir / safe_name
        create_histogram_png(image_path, title=title, chart_data=chart_data_json)
        self._queue_if_requested(image_path, caption or title, queue_for_delivery)
        return str(image_path)

    def create_csv_file(
        self,
        file_name: str,
        rows_json: str,
        caption: str = "",
        queue_for_delivery: bool = True,
    ) -> str:
        safe_name = slugify_filename(file_name, "jarvis-output.csv")
        if not safe_name.endswith(".csv"):
            safe_name += ".csv"
        csv_path = self.output_dir / safe_name
        write_csv_file(csv_path, rows_json)
        self._queue_if_requested(csv_path, caption or safe_name, queue_for_delivery)
        return str(csv_path)


class JarvisAgentRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = SqliteDb(db_file=str(settings.db_path))
        self.memory_manager = MemoryManager(
            db=self.db,
            model=OpenRouterResponses(id=settings.openrouter_memory_model),
            additional_instructions=(
                "Salva solo preferenze stabili dell'utente, abitudini durature, vincoli ricorrenti e fatti utili a lungo termine. "
                "Non salvare segreti, token, chiavi o dettagli temporanei."
            ),
        )

    def _build_tools(self, csv_paths: list[Path], runtime_tools: list[object]) -> list[object]:
        tools: list[object] = [
            FileTools(base_dir=self.settings.workspace_path, enable_delete_file=False),
            LocalFileSystemTools(target_directory=str(self.settings.output_path)),
            PythonTools(base_dir=self.settings.python_sandbox_path),
            ShellTools(base_dir=self.settings.shell_sandbox_path),
            WebSearchTools(fixed_max_results=5),
            HackerNewsTools(),
            *runtime_tools,
        ]
        if csv_paths:
            tools.append(CsvTools(csvs=csv_paths))
        if self.settings.browserbase_api_key and self.settings.browserbase_project_id:
            from agno.tools.browserbase import BrowserbaseTools

            tools.append(
                BrowserbaseTools(
                    api_key=self.settings.browserbase_api_key,
                    project_id=self.settings.browserbase_project_id,
                )
            )
        return tools

    @staticmethod
    def session_id_for(chat_id: int) -> str:
        return f"telegram:{chat_id}"

    def reset_session(self, chat_id: int) -> bool:
        """Forget the conversation history for a Telegram chat."""
        return self.db.delete_session(self.session_id_for(chat_id))

    def _build_agent(
        self,
        chat_id: int,
        user_id: str,
        csv_paths: list[Path],
        runtime_tools: list[object],
        vision_enabled: bool,
    ) -> Agent:
        model_id = self.settings.openrouter_vision_model if vision_enabled else self.settings.openrouter_model
        return Agent(
            name="Jarvis",
            user_id=user_id,
            session_id=self.session_id_for(chat_id),
            db=self.db,
            model=OpenRouterResponses(id=model_id),
            memory_manager=self.memory_manager,
            enable_agentic_memory=True,
            add_history_to_context=True,
            num_history_runs=self.settings.agent_history_runs,
            enable_session_summaries=True,
            add_session_summary_to_context=True,
            add_datetime_to_context=True,
            timezone_identifier=self.settings.timezone,
            tool_call_limit=self.settings.agent_tool_call_limit,
            retries=self.settings.agent_retries,
            markdown=True,
            tools=self._build_tools(csv_paths, runtime_tools),
            instructions=[
                "Sei Jarvis, un assistente personale privato, proattivo e preciso.",
                "Quando l'utente invia un audio usa la trascrizione come fonte primaria e cita eventuali incertezze.",
                "Quando l'utente invia un PDF o un CSV senza testo, capisci automaticamente che deve essere riassunto o analizzato.",
                "Quando generi un file finale per l'utente, usa i tool create_pdf_report, create_histogram_image, create_csv_file o send_local_file.",
                "Per i CSV preferisci spiegazioni semplici, con istogrammi facili da leggere e un breve testo che descriva il significato dell'infografica.",
                "Usa FileTools, PythonTools e ShellTools solo nelle sandbox previste.",
            ],
        )

    def transcribe_audio(self, audio_path: Path) -> str:
        transcription_agent = Agent(
            name="Jarvis Transcriber",
            model=OpenRouterResponses(id=self.settings.openrouter_audio_model, modalities=["text"]),
            markdown=False,
            instructions=[
                "Trascrivi l'audio in italiano con accuratezza.",
                "Mantieni il testo completo e non riassumere.",
                "Se alcuni passaggi non sono chiari, indicali tra parentesi quadre.",
            ],
        )
        response = transcription_agent.run(
            input="Trascrivi completamente questo audio.",
            audio=[Audio(filepath=str(audio_path), format=audio_path.suffix.lstrip("."))],
        )
        return str(response.content).strip()

    def run(self, message: IncomingMessage, artifact_queue: ArtifactQueue) -> str:
        prepared = prepare_agent_input(message)
        runtime_tools = [
            artifact_queue.send_local_file,
            artifact_queue.create_pdf_report,
            artifact_queue.create_histogram_image,
            artifact_queue.create_csv_file,
        ]
        agent = self._build_agent(
            chat_id=message.chat_id,
            user_id=f"telegram:{message.user_id}",
            csv_paths=prepared.csv_paths,
            runtime_tools=runtime_tools,
            vision_enabled=bool(prepared.images),
        )
        response = agent.run(
            input=prepared.prompt,
            images=prepared.images or None,
        )

        if prepared.histogram_data and not artifact_queue.items and message.text.strip().lower().endswith("pdf"):
            chart_json = json.dumps([{"label": label, "value": value} for label, value in prepared.histogram_data])
            artifact_queue.create_pdf_report(
                title="Report Jarvis",
                body=str(response.content),
                chart_data_json=chart_json,
                chart_title="Istogramma sintetico",
                infographic_description="\n".join(prepared.infographic_descriptions),
                file_name="jarvis-auto-report.pdf",
                caption="Report generato da Jarvis",
                queue_for_delivery=True,
            )

        return str(response.content).strip()
