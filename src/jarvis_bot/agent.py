from __future__ import annotations

import json
import logging
from datetime import datetime
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
from .approvals import ApprovalStore
from .attachments import prepare_agent_input
from .audit import AuditStore
from .codebase import index_repository, repo_status, search_code
from .config import Settings
from .integrations import macos, music
from .integrations.calendar import upcoming_events
from .integrations.email import EmailClient
from .integrations.github import GitHubClient
from .integrations.home_assistant import HomeAssistantClient
from .integrations.notion import NotionClient
from .integrations.weather import get_weather
from .knowledge import KnowledgeBase, format_hits, format_sources
from .media import generate_image, synthesize_speech
from .meetings import MeetingRecorder, MeetingStore
from .models import choose_model
from .persona import persona_instructions
from .plugins import PluginContext, PluginRegistry
from .presence import PresenceTracker
from .proactive import ProactiveEngine
from .profile import ProfileStore
from .protocols import ProtocolRunner, ProtocolStore
from .quality import build_quality_artifacts, record_snapshot, trend_spec
from .reminders import ReminderStore
from .reporting import build_pdf_report, render_chart, slugify_filename, write_csv_file
from .sandbox import docker_available, run_python_docker
from .schemas import ChartSeries, ChartSpec, IncomingMessage, PendingArtifact
from .security import run_safe_command
from .simulation import scenarios_from_json, simulate_file
from .vision import Sentinel, analyze_image, capture_camera, capture_screen

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

    def create_simulation_report(
        self,
        file_path: str,
        value_column: str = "",
        scenarios_json: str = "",
        file_name: str = "simulazione",
        caption: str = "",
        queue_for_delivery: bool = True,
    ) -> str:
        """Simula scenari su una colonna numerica di un CSV/Excel e crea PNG + CSV + PDF.

        `scenarios_json` è opzionale, ad esempio:
        [{"name": "Taglio costi", "change_pct": -15}, {"name": "Crescita", "change_pct": 20}]
        """
        path = Path(file_path).expanduser().resolve()
        if not path.exists():
            return f"File non trovato: {path}"
        try:
            scenarios = scenarios_from_json(scenarios_json)
            result = simulate_file(path, value_column or None, scenarios)
        except Exception as exc:
            return f"Simulazione non riuscita: {exc}"
        if result.spec is None:
            return "Simulazione senza dati da rappresentare."

        stem = slugify_filename(path.stem, "simulation")
        chart_path = render_chart(self.output_dir / f"{stem}-simulazione.png", result.spec)
        rows = [
            {
                "scenario": item["name"],
                "totale": item["total"],
                "delta": item["delta"],
                "delta_pct": item["delta_pct"],
            }
            for item in result.scenarios
        ]
        csv_path = self.output_dir / f"{stem}-simulazione.csv"
        write_csv_file(csv_path, json.dumps(rows, ensure_ascii=False))
        pdf_path = self.reports_dir / f"{stem}-simulazione.pdf"
        build_pdf_report(
            pdf_path,
            title=f"Simulazione — {path.name}",
            summary=result.summary,
            chart_spec=result.spec,
        )
        for artifact in (chart_path, csv_path, pdf_path):
            self._queue_if_requested(artifact, caption or f"Simulazione {path.name}", queue_for_delivery)
        return result.summary + "\n\nFile creati: " + ", ".join(p.name for p in (chart_path, csv_path, pdf_path))

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
        self.meetings = MeetingStore(settings.app_db_path_obj)
        self.meeting_recorder = MeetingRecorder(settings)
        self.home_assistant = HomeAssistantClient.from_settings(settings)
        self.presence = PresenceTracker(settings.phone_ip) if settings.presence_enabled else None
        self.sentinel = Sentinel(settings) if settings.sentinel_enabled else None
        self.profile = ProfileStore(settings.app_db_path_obj)
        self.proactive = ProactiveEngine(settings, self.presence) if settings.proactive_enabled else None
        self.audit = AuditStore(settings.app_db_path_obj)
        self.approvals = ApprovalStore(settings.app_db_path_obj)
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

    def _safe_shell_tool(self) -> object:
        def run_shell_safe(command: str) -> str:
            """Esegue un comando shell in allowlist dentro la sandbox (ls, git status, pytest...)."""
            result = run_safe_command(command, self.settings.shell_sandbox_path)
            if self.settings.audit_enabled:
                self.audit.record("shell.run", command)
            return result

        return run_shell_safe

    def _python_tools(self) -> list[object]:
        if self.settings.sandbox_backend.lower() != "docker":
            return [PythonTools(base_dir=self.settings.python_sandbox_path)]

        def run_python_sandboxed(code: str) -> str:
            """Esegue codice Python in un container Docker isolato (senza rete, memoria limitata)."""
            if not docker_available():
                return "Sandbox Docker non disponibile: installa Docker oppure usa JARVIS_SANDBOX_BACKEND=local."
            try:
                result = run_python_docker(
                    code,
                    image=self.settings.sandbox_image,
                    timeout=self.settings.sandbox_timeout_seconds,
                    memory=self.settings.sandbox_memory,
                    cpus=self.settings.sandbox_cpus,
                )
            except Exception as exc:
                return f"Sandbox Python non riuscita: {exc}"
            if self.settings.audit_enabled:
                self.audit.record("sandbox.python", "docker")
            return result

        return [run_python_sandboxed]

    def _macos_tools(self) -> list[object]:
        if not (self.settings.macos_control_enabled and macos.on_macos()):
            return []

        def _log(action: str, result: str) -> str:
            if self.settings.audit_enabled:
                self.audit.record(f"macos.{action}", str(result)[:500])
            return result

        def mac_open_app(name: str) -> str:
            """Apre un'app macOS (es. 'Visual Studio Code', 'Safari')."""
            return _log("open_app", macos.open_app(name))

        def mac_open_url(url: str) -> str:
            """Apre un URL nel browser predefinito."""
            return _log("open_url", macos.open_url(url))

        def mac_set_volume(level: int) -> str:
            """Imposta il volume di sistema (0-100)."""
            return _log("volume", macos.set_volume(level))

        def mac_get_volume() -> str:
            """Legge il volume di sistema."""
            return macos.get_volume()

        def mac_toggle_mute() -> str:
            """Attiva/disattiva il mute audio."""
            return _log("mute", macos.toggle_mute())

        def mac_lock() -> str:
            """Blocca lo schermo del Mac."""
            return _log("lock", macos.lock_screen())

        def mac_screenshot() -> str:
            """Cattura uno screenshot dello schermo e lo salva in output."""
            return _log("screenshot", macos.screenshot(self.settings.output_path / "screenshot.png"))

        def mac_notify(title: str, message: str) -> str:
            """Mostra una notifica macOS."""
            return _log("notify", macos.notify(title, message))

        def mac_clipboard_get() -> str:
            """Legge il contenuto degli appunti."""
            return macos.clipboard_get()

        def mac_clipboard_set(text: str) -> str:
            """Scrive testo negli appunti."""
            return _log("clipboard_set", macos.clipboard_set(text))

        def mac_run_shortcut(name: str) -> str:
            """Esegue una scorciatoia macOS (app Shortcuts)."""
            return _log("shortcut", macos.run_shortcut(name))

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
            if self.settings.require_approval:
                approval = self.approvals.request(
                    chat_id,
                    "protocol.run",
                    {"name": protocol.name},
                    f"Eseguire il protocollo '{protocol.name}'",
                )
                return (
                    f"Protocollo in attesa di approvazione (#{approval.id}). "
                    f"Usa /confirm {approval.id} oppure /cancel {approval.id}."
                )
            results = self.protocol_runner.run(protocol)
            if self.settings.audit_enabled:
                self.audit.record("protocol.run", protocol.name)
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

    def _home_tools(self) -> list[object]:
        client = self.home_assistant
        if client is None:
            return []

        def _log(action: str, result: str) -> str:
            if self.settings.audit_enabled:
                self.audit.record(f"home_assistant.{action}", str(result)[:500])
            return result

        def home_list(domain: str = "") -> str:
            """Elenca le entità Home Assistant, opzionalmente filtrate per dominio (light, climate, switch...)."""
            return client.list_entities(domain)

        def home_state(entity_id: str) -> str:
            """Legge lo stato di una entità Home Assistant (es. light.soggiorno)."""
            return client.get_state(entity_id)

        def home_turn_on(entity_id: str) -> str:
            """Accende una entità Home Assistant."""
            return _log("turn_on", client.turn_on(entity_id))

        def home_turn_off(entity_id: str) -> str:
            """Spegne una entità Home Assistant."""
            return _log("turn_off", client.turn_off(entity_id))

        def home_toggle(entity_id: str) -> str:
            """Alterna una entità Home Assistant."""
            return _log("toggle", client.toggle(entity_id))

        def home_set_temperature(entity_id: str, temperature: float) -> str:
            """Imposta la temperatura di un clima Home Assistant."""
            return _log("set_temperature", client.set_temperature(entity_id, temperature))

        def home_run_scene(entity_id: str) -> str:
            """Attiva una scena Home Assistant."""
            return _log("scene", client.run_scene(entity_id))

        def home_summary() -> str:
            """Riepilogo delle entità Home Assistant per dominio."""
            return client.summary()

        return [
            home_list,
            home_state,
            home_turn_on,
            home_turn_off,
            home_toggle,
            home_set_temperature,
            home_run_scene,
            home_summary,
        ]

    def _presence_tools(self) -> list[object]:
        if self.presence is None:
            return []

        def is_user_home() -> str:
            """Controlla se il telefono dell'utente è raggiungibile in rete (presenza a casa)."""
            return self.presence.describe()

        return [is_user_home]

    def _vision_tools(self, artifact_queue: ArtifactQueue | None) -> list[object]:
        if not self.settings.vision_enabled:
            return []

        def look_at_screen(question: str = "Cosa vedi sullo schermo? Segnala errori o elementi rilevanti.") -> str:
            """Cattura lo schermo del Mac e lo analizza con il modello vision."""
            analysis, path = self.look_at_screen(question)
            if self.settings.audit_enabled:
                self.audit.record("vision.screen", question[:300])
            if artifact_queue is not None:
                artifact_queue.send_local_file(str(path), "Screenshot analizzato")
            return analysis

        def look_at_camera(question: str = "Cosa vedi davanti alla camera?") -> str:
            """Cattura uno scatto dalla webcam e lo analizza con il modello vision."""
            analysis, path = self.look_at_camera(question)
            if artifact_queue is not None:
                artifact_queue.send_local_file(str(path), "Scatto camera")
            return analysis

        return [look_at_screen, look_at_camera]

    def _profile_tools(self) -> list[object]:
        def remember_fact(category: str, key: str, value: str) -> str:
            """Salva un fatto stabile sul profilo utente (es. categoria 'preferenze', key 'caffè', value 'amaro')."""
            fact = self.profile.remember(category, key, value)
            return f"Salvato: [{fact.category}] {fact.key} = {fact.value}"

        def recall_profile(category: str = "") -> str:
            """Mostra i fatti del profilo, opzionalmente filtrati per categoria."""
            return self.profile.format_facts(category or None)

        def forget_fact(category: str, key: str) -> str:
            """Rimuove un fatto dal profilo."""
            return "Fatto rimosso." if self.profile.forget(category, key) else "Fatto non trovato."

        def add_goal(title: str, due_at: str = "") -> str:
            """Aggiunge un obiettivo al profilo."""
            goal = self.profile.add_goal(title, due_at)
            return f"Obiettivo #{goal.id} aggiunto: {goal.title}"

        def list_goals() -> str:
            """Elenca gli obiettivi aperti."""
            goals = self.profile.goals()
            if not goals:
                return "Nessun obiettivo aperto."
            return "\n".join(
                f"• #{goal.id} {goal.title}" + (f" (scadenza {goal.due_at})" if goal.due_at else "")
                for goal in goals
            )

        def complete_goal(goal_id: int) -> str:
            """Segna un obiettivo come completato."""
            return f"Obiettivo #{goal_id} completato." if self.profile.complete_goal(goal_id) else "Obiettivo non trovato."

        def add_project(name: str, description: str = "") -> str:
            """Aggiunge o aggiorna un progetto nel profilo."""
            project = self.profile.add_project(name, description)
            return f"Progetto '{project.name}' salvato."

        def list_projects() -> str:
            """Elenca i progetti del profilo."""
            projects = self.profile.projects()
            if not projects:
                return "Nessun progetto salvato."
            return "\n".join(f"• {project.name}: {project.description or 'nessuna descrizione'}" for project in projects)

        return [
            remember_fact,
            recall_profile,
            forget_fact,
            add_goal,
            list_goals,
            complete_goal,
            add_project,
            list_projects,
        ]

    def _code_tools(self) -> list[object]:
        def repo_status_tool() -> str:
            """Mostra branch, stato e ultimi commit del repository locale."""
            return repo_status(self.settings.repo_path)

        def index_repository_tool() -> str:
            """Indicizza il codice del repository nella knowledge base per la ricerca semantica."""
            if self.knowledge is None:
                return "Knowledge base disabilitata."
            return index_repository(self.knowledge, self.settings.repo_path)

        def search_code_tool(query: str) -> str:
            """Cerca testo nel codice del repository (ripgrep o fallback)."""
            return search_code(query, self.settings.repo_path)

        return [repo_status_tool, index_repository_tool, search_code_tool]

    def _proactive_tools(self) -> list[object]:
        def check_proactive_now() -> str:
            """Esegue subito i controlli proattivi (email, GitHub, calendario, meteo, presenza)."""
            if self.proactive is None:
                return "Proattività disattivata."
            messages = self.proactive.check()
            return "\n".join(messages) if messages else "Nessun evento proattivo al momento."

        return [check_proactive_now]

    def look_at_screen(self, question: str = "Cosa vedi sullo schermo?") -> tuple[str, Path]:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.settings.output_path / f"screen-{stamp}.png"
        capture_screen(path)
        return analyze_image(path, question, self.settings), path

    def look_at_camera(self, question: str = "Cosa vedi?") -> tuple[str, Path]:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.settings.output_path / f"camera-{stamp}.jpg"
        capture_camera(path, self.settings.camera_device)
        return analyze_image(path, question, self.settings), path

    def _integration_tools(self, chat_id: int) -> list[object]:
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
                if self.settings.require_approval:
                    approval = self.approvals.request(
                        chat_id,
                        "email.send",
                        {"to": to, "subject": subject, "body": body},
                        f"Email a {to}: {subject}",
                    )
                    return (
                        f"Email in attesa di approvazione (#{approval.id}). "
                        f"Usa /confirm {approval.id} oppure /cancel {approval.id}."
                    )
                result = email_client.send(to, subject, body)
                if self.settings.audit_enabled:
                    self.audit.record("email.send", f"a={to} oggetto={subject}")
                return result

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
        artifact_queue: ArtifactQueue | None = None,
    ) -> list[object]:
        tools: list[object] = [
            FileTools(base_dir=self.settings.workspace_path, enable_delete_file=False),
            LocalFileSystemTools(target_directory=str(self.settings.output_path)),
            *self._python_tools(),
            *(
                [self._safe_shell_tool()]
                if self.settings.safe_shell_enabled
                else [ShellTools(base_dir=self.settings.shell_sandbox_path)]
            ),
            WebSearchTools(fixed_max_results=5),
            HackerNewsTools(),
            self._weather_tool(),
            *self._reminder_tools(chat_id),
            *self._knowledge_tools(),
            *self._macos_tools(),
            *self._music_tools(),
            *self._protocol_tools(chat_id),
            *self._home_tools(),
            *self._presence_tools(),
            *self._vision_tools(artifact_queue),
            *self._profile_tools(),
            *self._code_tools(),
            *self._proactive_tools(),
            *self._integration_tools(chat_id),
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
        model_id: str | None = None,
    ) -> Agent:
        plugin_tools, plugin_instructions = self.plugins.build(
            PluginContext(self.settings, chat_id, artifact_queue)
        )
        persona_name = self.app_state.get(chat_id, "persona", self.settings.persona)
        persona_lines = persona_instructions(persona_name, self.settings.address_as)
        profile_summary = self.profile.summary()
        selected_model = (
            self.settings.openrouter_vision_model
            if vision_enabled
            else (model_id or self.settings.openrouter_model)
        )
        return Agent(
            name="Jarvis",
            user_id=user_id,
            session_id=self.session_id_for(chat_id),
            db=self.db,
            model=OpenRouterResponses(id=selected_model),
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
            tools=self._build_tools(chat_id, csv_paths, runtime_tools, plugin_tools, artifact_queue),
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
                "Per la casa usa i tool home_* (Home Assistant); per la presenza is_user_home.",
                "Per analizzare schermo o webcam usa look_at_screen e look_at_camera, e cita ciò che vedi senza inventare.",
                "Usa remember_fact/recall_profile per la memoria strutturata, add_goal/list_goals per gli obiettivi e add_project per i progetti.",
                "Per simulazioni what-if su CSV/Excel usa create_simulation_report; per il codice usa repo_status_tool, index_repository_tool e search_code_tool.",
                f"Profilo utente (memoria strutturata):\n{profile_summary}",
                "Per domande su documenti già inviati usa search_knowledge e cita sempre la fonte (nome file).",
                "Se sono disponibili, usa i tool GitHub, email, calendario e Notion per azioni concrete; non inventare dati che non puoi verificare.",
                "Per i CSV preferisci spiegazioni semplici, con istogrammi facili da leggere e un breve testo che descriva il significato dell'infografica.",
                "Usa FileTools, PythonTools e ShellTools solo nelle sandbox previste.",
                *plugin_instructions,
            ],
        )

    def _run_fallback(self, prepared):
        from agno.models.ollama import Ollama

        fallback = Agent(
            name="Jarvis Fallback",
            model=Ollama(id=self.settings.ollama_model, host=self.settings.ollama_base_url),
            markdown=True,
            instructions=[
                "Sei Jarvis. Rispondi in italiano, in modo conciso e utile.",
                "Il modello principale non è disponibile: lavora con le informazioni nel prompt.",
            ],
        )
        return fallback.run(input=prepared.prompt)

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
            artifact_queue.create_simulation_report,
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
            model_id=choose_model(
                message.text or "",
                self.settings,
                has_images=bool(prepared.images),
                has_attachments=bool(message.attachments),
            ),
        )
        try:
            response = agent.run(
                input=prepared.prompt,
                images=prepared.images or None,
            )
        except Exception:
            LOGGER.exception("Primary model failed")
            if not self.settings.ollama_enabled:
                raise
            response = self._run_fallback(prepared)

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
