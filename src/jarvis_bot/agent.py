from __future__ import annotations

import json
import logging
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

from .app_state import AppStateStore
from .attachments import prepare_agent_input
from .config import Settings
from .integrations import macos, music
from .integrations.calendar import upcoming_events
from .integrations.email import EmailClient
from .integrations.github import GitHubClient
from .integrations.notion import NotionClient
from .integrations.weather import get_weather
from .knowledge import KnowledgeBase, format_hits, format_sources
from .media import generate_image, synthesize_speech
from .persona import persona_instructions
from .plugins import PluginContext, PluginRegistry
from .protocols import ProtocolRunner, ProtocolStore
from .quality import build_quality_artifacts, record_snapshot, trend_spec
from .reminders import ReminderStore
from .reporting import build_pdf_report, render_chart, slugify_filename, write_csv_file
from .schemas import ChartSeries, ChartSpec, IncomingMessage, PendingArtifact

LOGGER = logging.getLogger(__name__)


def _coerce_chart_spec(spec: ChartSpec | dict | None) -> ChartSpec | None:
    if spec is None or isinstance(spec, ChartSpec):
        return spec
    return ChartSpec.model_validate(spec)


class ArtifactQueue:
    """Collect files the agent wants to send back to Telegram."""

    def __init__(
        self,
        output_dir: Path,
        reports_dir: Path,
        workspace_dir: Path | None = None,
        app_db_path: Path | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.reports_dir = reports_dir
        self.workspace_dir = workspace_dir
        self.app_db_path = app_db_path
        self.settings = settings
        self.items: list[PendingArtifact] = []
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._allowed_roots = [self.output_dir.resolve(), self.reports_dir.resolve()]
        if self.workspace_dir is not None:
            self._allowed_roots.append(self.workspace_dir.resolve())

    def _ensure_allowed(self, path: Path) -> Path:
        resolved = path.expanduser().resolve()
        if not any(resolved.is_relative_to(root) for root in self._allowed_roots):
            raise ValueError(
                f"Percorso non consentito: {resolved}. Posso inviare solo file da output, reports o workspace."
            )
        if resolved.name.startswith(".") or resolved.suffix.lower() in {".db", ".sqlite", ".sqlite3", ".pem", ".key"}:
            raise ValueError(f"Per motivi di sicurezza non invio il file: {resolved.name}")
        return resolved

    def _queue_if_requested(self, path: Path, caption: str, queue_for_delivery: bool) -> None:
        if queue_for_delivery:
            self.items.append(PendingArtifact(local_path=path, caption=caption))

    def send_local_file(self, local_path: str, caption: str = "") -> str:
        path = Path(local_path).expanduser().resolve()
        if not path.exists():
            return f"File non trovato: {path}"
        try:
            path = self._ensure_allowed(path)
        except ValueError as exc:
            return str(exc)
        self.items.append(PendingArtifact(local_path=path, caption=caption))
        return f"File accodato per l'invio su Telegram: {path.name}"

    def create_pdf_report(
        self,
        title: str,
        body: str,
        chart_spec: ChartSpec | None = None,
        infographic_description: str = "",
        file_name: str = "jarvis-report.pdf",
        caption: str = "",
        queue_for_delivery: bool = True,
    ) -> str:
        """Crea un report PDF con testo e, opzionalmente, un grafico.

        `chart_spec` è una specifica tipizzata:
        {"title": "...", "labels": ["A","B"], "series": [{"label":"Valore","values":[1,2]}], "chart_type": "bar"}
        """
        safe_name = slugify_filename(file_name, "jarvis-report.pdf")
        if not safe_name.endswith(".pdf"):
            safe_name += ".pdf"
        descriptions = [line.strip() for line in infographic_description.splitlines() if line.strip()]
        report_path = self.reports_dir / safe_name
        build_pdf_report(
            report_path,
            title=title,
            summary=body,
            chart_spec=_coerce_chart_spec(chart_spec),
            infographic_descriptions=descriptions,
        )
        self._queue_if_requested(report_path, caption or title, queue_for_delivery)
        return str(report_path)

    def create_chart(
        self,
        spec: ChartSpec | dict,
        file_name: str = "jarvis-chart.png",
        caption: str = "",
        queue_for_delivery: bool = True,
    ) -> str:
        """Crea un grafico PNG (barre, barre raggruppate, linee, torta o Pareto).

        `spec` è una specifica tipizzata:
        {"title": "...", "labels": ["A","B"], "series": [{"label":"Valore","values":[1,2]}], "chart_type": "grouped_bar"}
        """
        typed_spec = _coerce_chart_spec(spec)
        assert typed_spec is not None
        safe_name = slugify_filename(file_name, "jarvis-chart.png")
        if not safe_name.endswith(".png"):
            safe_name += ".png"
        image_path = self.output_dir / safe_name
        render_chart(image_path, typed_spec)
        self._queue_if_requested(image_path, caption or typed_spec.title, queue_for_delivery)
        return str(image_path)

    def create_histogram_image(
        self,
        title: str,
        labels: list[str],
        values: list[float],
        file_name: str = "jarvis-chart.png",
        caption: str = "",
        queue_for_delivery: bool = True,
    ) -> str:
        """Crea un istogramma PNG con una etichetta per ogni valore."""
        spec = ChartSpec(
            title=title,
            labels=labels,
            series=[ChartSeries(label="Valore", values=values)],
            chart_type="bar",
        )
        return self.create_chart(spec, file_name=file_name, caption=caption, queue_for_delivery=queue_for_delivery)

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

    def create_quality_report(
        self,
        file_path: str,
        title: str = "",
        product_column: str = "",
        category_columns: str = "",
        caption: str = "",
        queue_for_delivery: bool = True,
    ) -> str:
        """Analizza una tabella di difetti (CSV/Excel) e crea grafici + report PDF.

        `file_path` è il percorso locale della tabella. `product_column` e
        `category_columns` sono opzionali: se vuoti vengono rilevati in automatico
        (la prima colonna testuale è il prodotto, le colonne numeriche sono le categorie).
        `category_columns` può essere una lista separata da virgole.
        """
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return f"File non trovato: {path}"
        try:
            report, artifacts = build_quality_artifacts(
                path,
                output_dir=self.output_dir,
                reports_dir=self.reports_dir,
                title=title or None,
                product_column=product_column or None,
                category_columns=category_columns or None,
            )
        except Exception as exc:
            return f"Analisi qualità non riuscita: {exc}"

        if self.app_db_path is not None:
            try:
                record_snapshot(self.app_db_path, report)
            except Exception:
                LOGGER.warning("Could not record the quality snapshot", exc_info=True)

        for artifact in artifacts:
            self._queue_if_requested(artifact, caption or report.source, queue_for_delivery)
        names = ", ".join(artifact.name for artifact in artifacts)
        return f"{report.summary}\n\nFile creati: {names}"

    def create_quality_trend(
        self,
        file_name: str = "quality-trend.png",
        caption: str = "",
        queue_for_delivery: bool = True,
    ) -> str:
        """Crea un grafico del trend dei difetti totali tra le analisi salvate."""
        if self.app_db_path is None:
            return "Trend non disponibile: database applicativo non configurato."
        spec = trend_spec(self.app_db_path)
        if spec is None:
            return "Servono almeno due analisi qualità salvate per disegnare il trend."
        return self.create_chart(spec, file_name=file_name, caption=caption, queue_for_delivery=queue_for_delivery)

    def create_voice_message(
        self,
        text: str,
        file_name: str = "jarvis-voice.ogg",
        caption: str = "",
        queue_for_delivery: bool = True,
    ) -> str:
        """Sintetizza un messaggio vocale con il testo indicato.

        Usa OpenAI TTS se OPENAI_API_KEY è configurata, altrimenti il comando
        macOS 'say'. Il file viene inviato su Telegram come audio.
        """
        if self.settings is None:
            return "Sintesi vocale non configurata."
        safe_name = slugify_filename(file_name, "jarvis-voice.ogg")
        if Path(safe_name).suffix.lower() not in {".ogg", ".mp3", ".m4a", ".wav"}:
            safe_name += ".ogg"
        try:
            path = synthesize_speech(
                text[: self.settings.voice_reply_max_chars],
                self.output_dir / safe_name,
                api_key=self.settings.openai_api_key,
                model=self.settings.tts_model,
                voice=self.settings.tts_voice,
            )
        except Exception as exc:
            return f"Sintesi vocale non riuscita: {exc}"
        self._queue_if_requested(path, caption or "Messaggio vocale", queue_for_delivery)
        return str(path)

    def create_image(
        self,
        prompt: str,
        file_name: str = "jarvis-image.png",
        caption: str = "",
        queue_for_delivery: bool = True,
    ) -> str:
        """Genera un'immagine dal prompt e la invia su Telegram."""
        if self.settings is None:
            return "Generazione immagini non configurata."
        safe_name = slugify_filename(file_name, "jarvis-image.png")
        if not safe_name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            safe_name += ".png"
        try:
            path = generate_image(
                prompt,
                self.output_dir / safe_name,
                api_key=self.settings.openai_api_key,
                model=self.settings.image_model,
            )
        except Exception as exc:
            return f"Generazione immagine non riuscita: {exc}"
        self._queue_if_requested(path, caption or prompt[:200], queue_for_delivery)
        return str(path)


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
        self.reminders = ReminderStore(settings.app_db_path_obj, settings.timezone)
        self.app_state = AppStateStore(settings.app_db_path_obj)
        self.protocols = ProtocolStore(settings.app_db_path_obj)
        self.protocol_runner = ProtocolRunner(settings.music_app)
        self.knowledge = (
            KnowledgeBase(settings.knowledge_db_path_obj, settings.knowledge_chunk_chars)
            if settings.knowledge_enabled
            else None
        )
        self.plugins = PluginRegistry()
        self.plugins.load_entry_points()

    def _knowledge_tools(self) -> list[object]:
        def search_knowledge(query: str, limit: int = 5) -> str:
            """Cerca nella knowledge base locale (PDF, DOCX, CSV, Excel, testi) e cita le fonti."""
            if self.knowledge is None:
                return "Knowledge base disabilitata."
            return format_hits(self.knowledge.search(query, limit=limit))

        def index_document(path: str) -> str:
            """Indicizza un documento locale nella knowledge base."""
            if self.knowledge is None:
                return "Knowledge base disabilitata."
            try:
                chunks = self.knowledge.index_file(path)
            except Exception as exc:
                return f"Indicizzazione non riuscita: {exc}"
            return f"Documento indicizzato in {chunks} chunk: {path}"

        def list_knowledge_sources() -> str:
            """Elenca i documenti presenti nella knowledge base."""
            if self.knowledge is None:
                return "Knowledge base disabilitata."
            return format_sources(self.knowledge.list_sources())

        return [search_knowledge, index_document, list_knowledge_sources]

    def _reminder_tools(self, chat_id: int) -> list[object]:
        def create_reminder(text: str, due_at: str, recurrence: str = "none") -> str:
            """Crea un promemoria e lo invia su Telegram alla data indicata.

            `due_at` accetta ISO ('2026-10-22 09:00') oppure forme come
            'domani alle 8', 'tra 2 ore', '+30m', '18:30'.
            `recurrence` può essere 'none', 'daily' o 'weekly'.
            """
            try:
                reminder = self.reminders.add(chat_id, text, due_at, recurrence)
            except ValueError as exc:
                return f"Impossibile creare il promemoria: {exc}"
            when = reminder.due_local(self.reminders.tz).strftime("%d/%m/%Y %H:%M")
            return f"Promemoria #{reminder.id} creato per {when}: {reminder.text}"

        def list_reminders() -> str:
            """Elenca i promemoria attivi di questa chat."""
            return self.reminders.format_list(self.reminders.list(chat_id))

        def cancel_reminder(reminder_id: int) -> str:
            """Annulla un promemoria attivo dato il suo id."""
            if self.reminders.cancel(chat_id, reminder_id):
                return f"Promemoria #{reminder_id} annullato."
            return f"Nessun promemoria attivo con id {reminder_id}."

        return [create_reminder, list_reminders, cancel_reminder]

    def _weather_tool(self) -> object:
        def current_weather(location: str = "") -> str:
            """Meteo attuale e previsione di oggi per una località."""
            return get_weather(
                location or self.settings.location_name,
                latitude=self.settings.latitude,
                longitude=self.settings.longitude,
                timezone=self.settings.timezone,
            )

        return current_weather

    def _macos_tools(self) -> list[object]:
        if not (self.settings.macos_control_enabled and macos.on_macos()):
            return []

        def mac_open_app(name: str) -> str:
            """Apre un'app macOS (es. 'Visual Studio Code', 'Safari')."""
            return macos.open_app(name)

        def mac_open_url(url: str) -> str:
            """Apre un URL nel browser predefinito."""
            return macos.open_url(url)

        def mac_set_volume(level: int) -> str:
            """Imposta il volume di sistema (0-100)."""
            return macos.set_volume(level)

        def mac_get_volume() -> str:
            """Legge il volume di sistema."""
            return macos.get_volume()

        def mac_toggle_mute() -> str:
            """Attiva/disattiva il mute audio."""
            return macos.toggle_mute()

        def mac_lock() -> str:
            """Blocca lo schermo del Mac."""
            return macos.lock_screen()

        def mac_screenshot() -> str:
            """Cattura uno screenshot dello schermo e lo salva in output."""
            return macos.screenshot(self.settings.output_path / "screenshot.png")

        def mac_notify(title: str, message: str) -> str:
            """Mostra una notifica macOS."""
            return macos.notify(title, message)

        def mac_clipboard_get() -> str:
            """Legge il contenuto degli appunti."""
            return macos.clipboard_get()

        def mac_clipboard_set(text: str) -> str:
            """Scrive testo negli appunti."""
            return macos.clipboard_set(text)

        def mac_run_shortcut(name: str) -> str:
            """Esegue una scorciatoia macOS (app Shortcuts)."""
            return macos.run_shortcut(name)

        def mac_system_health() -> str:
            """Report di salute del Mac: CPU, RAM, disco, batteria."""
            return macos.system_health()

        return [
            mac_open_app,
            mac_open_url,
            mac_set_volume,
            mac_get_volume,
            mac_toggle_mute,
            mac_lock,
            mac_screenshot,
            mac_notify,
            mac_clipboard_get,
            mac_clipboard_set,
            mac_run_shortcut,
            mac_system_health,
        ]

    def _music_tools(self) -> list[object]:
        if not (self.settings.macos_control_enabled and macos.on_macos()):
            return []
        app = self.settings.music_app

        def music_play() -> str:
            """Avvia la riproduzione musicale."""
            return music.play(app)

        def music_pause() -> str:
            """Mette in pausa la musica."""
            return music.pause(app)

        def music_play_pause() -> str:
            """Alterna play/pausa."""
            return music.play_pause(app)

        def music_next() -> str:
            """Passa al brano successivo."""
            return music.next_track(app)

        def music_previous() -> str:
            """Torna al brano precedente."""
            return music.previous_track(app)

        def music_current() -> str:
            """Mostra il brano in riproduzione."""
            return music.current_track(app)

        def music_volume(level: int) -> str:
            """Imposta il volume dell'app musicale (0-100)."""
            return music.set_volume(app, level)

        return [music_play, music_pause, music_play_pause, music_next, music_previous, music_current, music_volume]

    def _protocol_tools(self, chat_id: int) -> list[object]:
        if not self.settings.protocols_enabled:
            return []

        def list_protocols() -> str:
            """Elenca i protocolli disponibili."""
            return self.protocols.format_list()

        def run_protocol(name: str) -> str:
            """Esegue un protocollo per nome (es. 'lavoro', 'buonanotte')."""
            protocol = self.protocols.get(name)
            if protocol is None:
                return f"Protocollo '{name}' non trovato. Usa list_protocols per vedere quelli disponibili."
            results = self.protocol_runner.run(protocol)
            return f"🧩 Protocollo **{protocol.name}**\n" + "\n".join(results)

        def create_protocol(name: str, description: str, steps_json: str) -> str:
            """Crea o aggiorna un protocollo.

            `steps_json` è una lista JSON di passi, ad esempio:
            [{"type": "open_app", "value": "Safari"}, {"type": "notify", "title": "Ciao", "message": "Fatto"}]
            Tipi supportati: open_app, open_url, notify, volume, lock, screenshot, shortcut, sleep, music, home_assistant, backup.
            """
            try:
                steps = json.loads(steps_json)
            except ValueError as exc:
                return f"JSON non valido: {exc}"
            try:
                protocol = self.protocols.upsert(name, description, steps)
            except ValueError as exc:
                return f"Protocollo non creato: {exc}"
            return f"Protocollo '{protocol.name}' salvato con {len(protocol.steps)} passi."

        return [list_protocols, run_protocol, create_protocol]

    def _integration_tools(self) -> list[object]:
        tools: list[object] = []

        if self.settings.github_token:
            github = GitHubClient(self.settings.github_token, self.settings.github_default_repo)

            def list_github_issues(repo: str = "", state: str = "open", limit: int = 10) -> str:
                """Elenca le issue di un repository GitHub (repo vuoto = repo predefinito)."""
                return github.list_issues(repo or None, state, limit)

            def list_github_pulls(repo: str = "", state: str = "open", limit: int = 10) -> str:
                """Elenca le pull request di un repository GitHub."""
                return github.list_pull_requests(repo or None, state, limit)

            def github_repo_summary(repo: str = "") -> str:
                """Mostra un riepilogo di un repository GitHub."""
                return github.repo_summary(repo or None)

            def search_github_issues(query: str, repo: str = "", limit: int = 5) -> str:
                """Cerca issue e pull request su GitHub."""
                return github.search_issues(query, repo or None, limit)

            def create_github_issue(title: str, body: str = "", repo: str = "") -> str:
                """Crea una issue su GitHub."""
                return github.create_issue(title, body, repo or None)

            tools.extend(
                [
                    list_github_issues,
                    list_github_pulls,
                    github_repo_summary,
                    search_github_issues,
                    create_github_issue,
                ]
            )

        if (
            self.settings.email_imap_host
            and self.settings.email_smtp_host
            and self.settings.email_username
            and self.settings.email_password
        ):
            email_client = EmailClient(
                self.settings.email_imap_host,
                self.settings.email_imap_port,
                self.settings.email_smtp_host,
                self.settings.email_smtp_port,
                self.settings.email_username,
                self.settings.email_password,
                self.settings.email_from,
            )

            def list_unread_email(limit: int = 10) -> str:
                """Elenca le email non lette."""
                return email_client.list_unread(limit)

            def search_email(query: str, limit: int = 10) -> str:
                """Cerca email per testo."""
                return email_client.search(query, limit)

            def send_email(to: str, subject: str, body: str) -> str:
                """Invia una email."""
                return email_client.send(to, subject, body)

            tools.extend([list_unread_email, search_email, send_email])

        if self.settings.calendar_ics_url:
            calendar_source = self.settings.calendar_ics_url

            def upcoming_calendar(limit: int = 10) -> str:
                """Mostra i prossimi eventi del calendario configurato."""
                return upcoming_events(calendar_source, self.settings.timezone, limit)

            tools.append(upcoming_calendar)

        if self.settings.notion_token:
            notion = NotionClient(self.settings.notion_token, self.settings.notion_database_id)

            def notion_search(query: str = "", limit: int = 5) -> str:
                """Cerca pagine e database su Notion."""
                return notion.search(query, limit)

            def notion_add_note(title: str, content: str = "") -> str:
                """Crea una pagina/nota nel database Notion configurato."""
                return notion.add_note(title, content)

            tools.extend([notion_search, notion_add_note])

        return tools

    def _build_tools(
        self,
        chat_id: int,
        csv_paths: list[Path],
        runtime_tools: list[object],
        extra_tools: list[object] | None = None,
    ) -> list[object]:
        tools: list[object] = [
            FileTools(base_dir=self.settings.workspace_path, enable_delete_file=False),
            LocalFileSystemTools(target_directory=str(self.settings.output_path)),
            PythonTools(base_dir=self.settings.python_sandbox_path),
            ShellTools(base_dir=self.settings.shell_sandbox_path),
            WebSearchTools(fixed_max_results=5),
            HackerNewsTools(),
            self._weather_tool(),
            *self._reminder_tools(chat_id),
            *self._knowledge_tools(),
            *self._macos_tools(),
            *self._music_tools(),
            *self._protocol_tools(chat_id),
            *self._integration_tools(),
            *runtime_tools,
            *(extra_tools or []),
        ]
        if csv_paths:
            tools.append(CsvTools(csvs=csv_paths))
        if self.settings.browserbase_api_key and self.settings.browserbase_project_id:
            try:
                from agno.tools.browserbase import BrowserbaseTools
            except ImportError:
                LOGGER.warning(
                    "Browserbase configurato ma dipendenza mancante: installa con pip install -e '.[browser]'"
                )
            else:
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
        artifact_queue: ArtifactQueue | None = None,
    ) -> Agent:
        plugin_tools, plugin_instructions = self.plugins.build(
            PluginContext(self.settings, chat_id, artifact_queue)
        )
        persona_name = self.app_state.get(chat_id, "persona", self.settings.persona)
        persona_lines = persona_instructions(persona_name, self.settings.address_as)
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
            tools=self._build_tools(chat_id, csv_paths, runtime_tools, plugin_tools),
            instructions=[
                *persona_lines,
                "Sei Jarvis, un assistente personale privato, proattivo e preciso.",
                "Quando l'utente invia un audio usa la trascrizione come fonte primaria e cita eventuali incertezze.",
                "Quando l'utente invia un PDF o un CSV senza testo, capisci automaticamente che deve essere riassunto o analizzato.",
                "Quando generi un file finale per l'utente, usa i tool create_chart, create_pdf_report, create_histogram_image, create_csv_file o send_local_file.",
                "Per analisi di difetti o tabelle qualità (prodotto × categorie) usa create_quality_report; per il trend usa create_quality_trend.",
                "Se l'utente chiede di generare un'immagine usa create_image. Se chiede una risposta vocale usa create_voice_message.",
                "Gestisci promemoria con create_reminder, list_reminders e cancel_reminder; usa il meteo con current_weather.",
                "Per controllare il Mac usa i tool mac_* e music_*; per azioni composite usa list_protocols e run_protocol.",
                "Per domande su documenti già inviati usa search_knowledge e cita sempre la fonte (nome file).",
                "Se sono disponibili, usa i tool GitHub, email, calendario e Notion per azioni concrete; non inventare dati che non puoi verificare.",
                "Per i CSV preferisci spiegazioni semplici, con istogrammi facili da leggere e un breve testo che descriva il significato dell'infografica.",
                "Usa FileTools, PythonTools e ShellTools solo nelle sandbox previste.",
                *plugin_instructions,
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
        if self.knowledge is not None:
            for document_path in prepared.document_paths:
                try:
                    self.knowledge.index_file(document_path)
                except Exception:
                    LOGGER.warning("Could not index attachment %s", document_path, exc_info=True)
        runtime_tools = [
            artifact_queue.send_local_file,
            artifact_queue.create_chart,
            artifact_queue.create_pdf_report,
            artifact_queue.create_histogram_image,
            artifact_queue.create_csv_file,
            artifact_queue.create_quality_report,
            artifact_queue.create_quality_trend,
            artifact_queue.create_voice_message,
            artifact_queue.create_image,
        ]
        agent = self._build_agent(
            chat_id=message.chat_id,
            user_id=f"telegram:{message.user_id}",
            csv_paths=prepared.csv_paths,
            runtime_tools=runtime_tools,
            vision_enabled=bool(prepared.images),
            artifact_queue=artifact_queue,
        )
        response = agent.run(
            input=prepared.prompt,
            images=prepared.images or None,
        )

        if prepared.histogram_data and not artifact_queue.items and message.text.strip().lower().endswith("pdf"):
            spec = ChartSpec(
                title="Istogramma sintetico",
                labels=[label for label, _ in prepared.histogram_data],
                series=[ChartSeries(label="Valore", values=[value for _, value in prepared.histogram_data])],
                chart_type="bar",
            )
            artifact_queue.create_pdf_report(
                title="Report Jarvis",
                body=str(response.content),
                chart_spec=spec,
                infographic_description="\n".join(prepared.infographic_descriptions),
                file_name="jarvis-auto-report.pdf",
                caption="Report generato da Jarvis",
                queue_for_delivery=True,
            )

        return str(response.content).strip()
