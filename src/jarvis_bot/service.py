from __future__ import annotations

import asyncio
import logging
import mimetypes
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from datetime import time as dt_time
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from .agent import ArtifactQueue, JarvisAgentRunner
from .config import Settings
from .integrations.weather import get_weather
from .knowledge import format_hits, format_sources
from .meetings import summarize_meeting
from .persona import PERSONAS, normalize_persona, persona_choices, persona_label
from .quality import (
    build_quality_artifacts,
    mark_quality_file,
    pending_quality_files,
    record_snapshot,
    trend_spec,
)
from .reporting import render_chart
from .schemas import Attachment, AttachmentType, IncomingMessage, PendingArtifact
from .stats import collect_stats, format_stats
from .voice_loop import transcribe_audio as transcribe_audio_file

LOGGER = logging.getLogger(__name__)
TELEGRAM_MESSAGE_LIMIT = 4096

ITALIAN_DAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
ITALIAN_MONTHS = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]


def italian_date(moment: datetime) -> str:
    return f"{ITALIAN_DAYS[moment.weekday()]} {moment.day} {ITALIAN_MONTHS[moment.month - 1]} {moment.year}"

HELP_TEXT = (
    "🤖 **J.A.R.V.I.S.**\n\n"
    "Sono il tuo assistente personale. Puoi scrivermi, mandarmi vocali, foto, PDF e CSV.\n\n"
    "**Comandi**\n"
    "/start — presentazione\n"
    "/help — questo messaggio\n"
    "/reset — dimentica la conversazione corrente\n"
    "/stats — statistiche d'uso\n"
    "/files — ultimi file generati\n"
    "/voice on|off — risposte vocali\n"
    "/index [file] — indicizza documenti\n"
    "/ask <domanda> — cerca nella knowledge base\n"
    "/sources — documenti indicizzati\n\n"
    "/brief — brief di oggi su richiesta\n"
    "/reminders — promemoria attivi\n"
    "/quality <file> — analisi difetti CSV/Excel\n"
    "/persona [nome] — cambia personalità\n"
    "/protocol [nome] — elenca o esegue protocolli\n"
    "/meeting start|stop|list|show — registra e riassume riunioni\n"
    "/look screen|camera [domanda] — analizza schermo o webcam\n"
    "/sentinel on|off|status — modalità sentinella\n\n"
    "**Cosa so fare**\n"
    "• rispondere e ricordare il contesto della chat\n"
    "• trascrivere audio e descrivere immagini\n"
    "• analizzare PDF e CSV, creare grafici e report PDF\n"
    "• creare promemoria e inviarti il brief del mattino\n"
    "• usare il web, i file e una sandbox Python/shell\n"
)


class JarvisTelegramService:
    def __init__(self, settings: Settings, agent_runner: JarvisAgentRunner | None = None) -> None:
        self.settings = settings
        self.agent_runner = agent_runner or JarvisAgentRunner(settings)
        self.bot = Bot(token=settings.telegram_bot_token)
        self.dispatcher = Dispatcher()
        self._chat_locks: dict[int, asyncio.Lock] = {}
        self._run_semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_runs))
        self._last_sentinel_check = 0.0
        self._register_handlers()

    def _register_handlers(self) -> None:
        # Commands must be registered before the catch-all text handler.
        self.dispatcher.message.register(self.handle_start, Command("start"))
        self.dispatcher.message.register(self.handle_help, Command("help"))
        self.dispatcher.message.register(self.handle_reset, Command("reset"))
        self.dispatcher.message.register(self.handle_stats, Command("stats"))
        self.dispatcher.message.register(self.handle_files, Command("files"))
        self.dispatcher.message.register(self.handle_voice_mode, Command("voice"))
        self.dispatcher.message.register(self.handle_index, Command("index"))
        self.dispatcher.message.register(self.handle_ask, Command("ask"))
        self.dispatcher.message.register(self.handle_sources, Command("sources"))
        self.dispatcher.message.register(self.handle_brief, Command("brief"))
        self.dispatcher.message.register(self.handle_reminders, Command("reminders"))
        self.dispatcher.message.register(self.handle_quality, Command("quality"))
        self.dispatcher.message.register(self.handle_persona, Command("persona"))
        self.dispatcher.message.register(self.handle_protocol, Command("protocol"))
        self.dispatcher.message.register(self.handle_meeting, Command("meeting"))
        self.dispatcher.message.register(self.handle_look, Command("look"))
        self.dispatcher.message.register(self.handle_sentinel, Command("sentinel"))
        self.dispatcher.message.register(self.handle_voice, F.voice)
        self.dispatcher.message.register(self.handle_audio, F.audio)
        self.dispatcher.message.register(self.handle_photo, F.photo)
        self.dispatcher.message.register(self.handle_document, F.document)
        self.dispatcher.message.register(self.handle_text, F.text)

    def is_allowed_user(self, user_id: int | None) -> bool:
        return bool(user_id and user_id == self.settings.telegram_allowed_user_id)

    def _guard(self, message: Message) -> bool:
        user = message.from_user
        allowed = self.is_allowed_user(user.id if user else None)
        if not allowed:
            LOGGER.info("Rejected telegram user %s", getattr(user, "id", None))
        return allowed

    async def run_polling(self) -> None:
        self.settings.ensure_directories()
        scheduler = asyncio.create_task(self._scheduler_loop())
        try:
            await self.dispatcher.start_polling(self.bot, allowed_updates=["message"])
        finally:
            scheduler.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler
            await self.bot.session.close()

    async def handle_start(self, message: Message) -> None:
        if not self._guard(message):
            return
        await message.answer(HELP_TEXT, parse_mode="Markdown")

    async def handle_help(self, message: Message) -> None:
        if not self._guard(message):
            return
        await message.answer(HELP_TEXT, parse_mode="Markdown")

    async def handle_reset(self, message: Message) -> None:
        if not self._guard(message):
            return
        reset = getattr(self.agent_runner, "reset_session", None)
        if reset is None:
            await message.answer("Questo runner non supporta il reset della sessione.")
            return
        await asyncio.to_thread(reset, message.chat.id)
        await message.answer("Sessione azzerata. Ripartiamo da zero. 🧠")

    async def handle_stats(self, message: Message) -> None:
        if not self._guard(message):
            return
        stats = await asyncio.to_thread(collect_stats, self.settings.db_path)
        await message.answer(format_stats(stats), parse_mode="Markdown")

    async def handle_files(self, message: Message) -> None:
        if not self._guard(message):
            return
        files = self._recent_files()
        if not files:
            await message.answer("Nessun file generato finora.")
            return
        lines = ["🗂️ **Ultimi file generati**"]
        for path in files:
            size_kb = max(1, path.stat().st_size // 1024)
            moment = datetime.fromtimestamp(path.stat().st_mtime).strftime("%d/%m %H:%M")
            lines.append(f"• `{path.name}` — {size_kb} KB — {moment}")
        await message.answer("\n".join(lines), parse_mode="Markdown")

    async def handle_voice_mode(self, message: Message) -> None:
        if not self._guard(message):
            return
        state = getattr(self.agent_runner, "app_state", None)
        if state is None:
            await message.answer("Preferenze vocali non disponibili con questo runner.")
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 1:
            enabled = state.get_bool(message.chat.id, "voice_replies", False)
            status = "attive" if enabled else "disattive"
            await message.answer(f"Risposte vocali: **{status}**.\nUsa /voice on oppure /voice off.", parse_mode="Markdown")
            return
        enabled = parts[1].strip().lower() in {"on", "si", "sì", "true", "1", "attiva", "attive"}
        state.set(message.chat.id, "voice_replies", "true" if enabled else "false")
        await message.answer("Risposte vocali attivate. 🔊" if enabled else "Risposte vocali disattivate. 🔇")

    async def handle_index(self, message: Message) -> None:
        if not self._guard(message):
            return
        knowledge = getattr(self.agent_runner, "knowledge", None)
        if knowledge is None:
            await message.answer("Knowledge base disabilitata.")
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 1:
            files, chunks = await asyncio.to_thread(knowledge.index_directory, self.settings.knowledge_path)
            await message.answer(
                f"Indicizzati {files} file ({chunks} chunk) da `{self.settings.knowledge_path}`."
            )
            return
        target = parts[1].strip()
        try:
            chunks = await asyncio.to_thread(knowledge.index_file, target)
        except Exception as exc:
            await message.answer(f"Indicizzazione non riuscita: {exc}")
            return
        await message.answer(f"Documento indicizzato in {chunks} chunk: `{Path(target).name}`")

    async def handle_ask(self, message: Message) -> None:
        if not self._guard(message):
            return
        knowledge = getattr(self.agent_runner, "knowledge", None)
        if knowledge is None:
            await message.answer("Knowledge base disabilitata.")
            return
        query = (message.text or "").partition(" ")[2].strip()
        if not query:
            await message.answer("Uso: /ask <domanda>")
            return
        hits = await asyncio.to_thread(
            knowledge.search, query, self.settings.knowledge_max_results
        )
        await self._reply_chunks(message, format_hits(hits), parse_mode="Markdown")

    async def handle_sources(self, message: Message) -> None:
        if not self._guard(message):
            return
        knowledge = getattr(self.agent_runner, "knowledge", None)
        if knowledge is None:
            await message.answer("Knowledge base disabilitata.")
            return
        sources = await asyncio.to_thread(knowledge.list_sources)
        await message.answer(format_sources(sources), parse_mode="Markdown")

    async def handle_brief(self, message: Message) -> None:
        if not self._guard(message):
            return
        now = datetime.now(ZoneInfo(self.settings.timezone))
        brief = await asyncio.to_thread(self._build_daily_brief, now)
        await self._reply_chunks(message, brief, parse_mode="Markdown")

    async def handle_reminders(self, message: Message) -> None:
        if not self._guard(message):
            return
        store = self._reminder_store
        if store is None:
            await message.answer("Promemoria non disponibili con questo runner.")
            return
        reminders = await asyncio.to_thread(store.list, message.chat.id)
        await message.answer(store.format_list(reminders), parse_mode="Markdown")

    async def handle_quality(self, message: Message) -> None:
        if not self._guard(message):
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 1:
            await message.answer(
                "Uso: `/quality <percorso CSV/Excel>`. "
                f"Oppure metti il file in `{self.settings.quality_watch_path}` e verrà analizzato automaticamente."
            )
            return
        target = parts[1].strip()
        try:
            report, artifacts = await asyncio.to_thread(
                build_quality_artifacts,
                target,
                self.settings.output_path,
                self.settings.reports_path,
            )
            await asyncio.to_thread(record_snapshot, self.settings.app_db_path_obj, report)
        except Exception as exc:
            await message.answer(f"Analisi qualità non riuscita: {exc}")
            return
        await self._reply_chunks(message, report.summary)
        await self._deliver_artifacts(
            message.chat.id,
            [PendingArtifact(local_path=artifact, caption=f"Qualità — {Path(target).name}") for artifact in artifacts],
        )

    async def handle_persona(self, message: Message) -> None:
        if not self._guard(message):
            return
        state = getattr(self.agent_runner, "app_state", None)
        parts = (message.text or "").split(maxsplit=1)
        current = state.get(message.chat.id, "persona", self.settings.persona) if state else self.settings.persona
        if len(parts) == 1:
            await message.answer(
                f"Persona attuale: **{persona_label(current)}**\n"
                f"Disponibili: {', '.join(persona_choices())}.\n"
                "Uso: /persona butler | friendly | concise | mentor | stark",
                parse_mode="Markdown",
            )
            return
        requested = parts[1].strip().lower()
        if requested not in PERSONAS:
            await message.answer(f"Persona non valida. Scegli tra: {', '.join(persona_choices())}.")
            return
        if state is None:
            await message.answer("Preferenze non disponibili con questo runner.")
            return
        state.set(message.chat.id, "persona", normalize_persona(requested))
        await message.answer(f"Persona impostata su **{persona_label(requested)}**.", parse_mode="Markdown")

    async def handle_protocol(self, message: Message) -> None:
        if not self._guard(message):
            return
        store = getattr(self.agent_runner, "protocols", None)
        runner = getattr(self.agent_runner, "protocol_runner", None)
        if store is None or runner is None:
            await message.answer("Protocolli non disponibili con questo runner.")
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 1:
            await message.answer(store.format_list(), parse_mode="Markdown")
            return
        protocol = store.get(parts[1].strip().lower())
        if protocol is None:
            await message.answer(f"Protocollo non trovato. Ecco quelli disponibili:\n\n{store.format_list()}", parse_mode="Markdown")
            return
        results = await asyncio.to_thread(runner.run, protocol)
        await message.answer(
            f"🧩 **{protocol.name}**\n" + "\n".join(results),
            parse_mode="Markdown",
        )

    async def handle_meeting(self, message: Message) -> None:
        if not self._guard(message):
            return
        recorder = getattr(self.agent_runner, "meeting_recorder", None)
        store = getattr(self.agent_runner, "meetings", None)
        if recorder is None or store is None:
            await message.answer("Meeting assistant non disponibile con questo runner.")
            return

        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 1:
            await message.answer(
                "Uso:\n"
                "/meeting start [titolo] — avvia la registrazione\n"
                "/meeting stop — ferma, trascrive e riassume\n"
                "/meeting list — ultime riunioni\n"
                "/meeting show <id> — dettaglio riunione"
            )
            return

        command, _, rest = parts[1].partition(" ")
        command = command.strip().lower()
        rest = rest.strip()

        if command == "start":
            try:
                path = await asyncio.to_thread(recorder.start, rest or "Riunione")
            except Exception as exc:
                await message.answer(f"Registrazione non avviata: {exc}")
                return
            await message.answer(f"🎙️ Registrazione avviata: `{path.name}`", parse_mode="Markdown")
            return

        if command == "stop":
            try:
                path, duration = await asyncio.to_thread(recorder.stop)
            except Exception as exc:
                await message.answer(f"Registrazione non fermata: {exc}")
                return
            await message.answer("⏳ Trascrivo e riassumo la riunione…")
            try:
                transcript = await asyncio.to_thread(transcribe_audio_file, path, self.settings)
                summary, action_items = await asyncio.to_thread(summarize_meeting, transcript, self.settings)
            except Exception as exc:
                await message.answer(f"Riassunto non riuscito: {exc}")
                return
            meeting = await asyncio.to_thread(
                store.add,
                path.stem,
                transcript,
                summary,
                action_items,
                duration,
            )
            transcript_path = path.with_suffix(".txt")
            transcript_path.write_text(transcript, encoding="utf-8")
            await self._reply_chunks(message, store.format_meeting(meeting), parse_mode="Markdown")
            return

        if command == "list":
            meetings = await asyncio.to_thread(store.list)
            await message.answer(store.format_list(meetings), parse_mode="Markdown")
            return

        if command == "show":
            try:
                meeting_id = int(rest)
            except ValueError:
                await message.answer("Uso: /meeting show <id>")
                return
            meeting = await asyncio.to_thread(store.get, meeting_id)
            if meeting is None:
                await message.answer(f"Nessuna riunione con id {meeting_id}.")
                return
            await self._reply_chunks(message, store.format_meeting(meeting), parse_mode="Markdown")
            return

        await message.answer("Comando meeting non riconosciuto. Usa /meeting per l'elenco.")

    async def handle_look(self, message: Message) -> None:
        if not self._guard(message):
            return
        parts = (message.text or "").split(maxsplit=2)
        target = parts[1].strip().lower() if len(parts) > 1 else "screen"
        question = parts[2].strip() if len(parts) > 2 else ""
        runner = self.agent_runner
        if target.startswith("cam"):
            action = getattr(runner, "look_at_camera", None)
            default_question = "Cosa vedi davanti alla camera?"
            caption = "Scatto camera"
        elif target.startswith("screen") or target in {"schermo", "monitor"}:
            action = getattr(runner, "look_at_screen", None)
            default_question = "Cosa vedi sullo schermo? Segnala errori o elementi rilevanti."
            caption = "Screenshot"
        else:
            await message.answer("Uso: /look screen [domanda] oppure /look camera [domanda]")
            return
        if action is None:
            await message.answer("Visione non disponibile con questo runner.")
            return
        try:
            analysis, path = await asyncio.to_thread(action, question or default_question)
        except Exception as exc:
            await message.answer(f"Analisi non riuscita: {exc}")
            return
        await self._reply_chunks(message, analysis, parse_mode="Markdown")
        await self._deliver_artifacts(message.chat.id, [PendingArtifact(local_path=path, caption=caption)])

    async def handle_sentinel(self, message: Message) -> None:
        if not self._guard(message):
            return
        runner = self.agent_runner
        state = getattr(runner, "app_state", None)
        parts = (message.text or "").split(maxsplit=1)
        action = parts[1].strip().lower() if len(parts) > 1 else "status"
        enabled = (
            state.get_bool(message.chat.id, "sentinel", self.settings.sentinel_enabled)
            if state is not None
            else self.settings.sentinel_enabled
        )

        if action in {"on", "off"}:
            if state is None:
                await message.answer("Preferenze non disponibili con questo runner.")
                return
            wanted = action == "on"
            state.set(message.chat.id, "sentinel", "true" if wanted else "false")
            if wanted and getattr(runner, "sentinel", None) is None:
                from .vision import Sentinel

                runner.sentinel = Sentinel(self.settings)
            await message.answer(
                "🚨 Sentinella attiva: controllerò la webcam periodicamente."
                if wanted
                else "Sentinella disattivata."
            )
            return

        status = "attiva" if enabled else "disattiva"
        await message.answer(
            f"🚨 Sentinella **{status}**.\n"
            f"Intervallo: {self.settings.sentinel_interval_seconds}s · soglia: {self.settings.sentinel_threshold}.\n"
            "Usa /sentinel on oppure /sentinel off.",
            parse_mode="Markdown",
        )

    def _recent_files(self, limit: int = 10) -> list[Path]:
        candidates: list[Path] = []
        for directory in (self.settings.output_path, self.settings.reports_path):
            if not directory.exists():
                continue
            candidates.extend(
                path for path in directory.iterdir() if path.is_file() and not path.name.startswith(".")
            )
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return candidates[:limit]

    async def _scheduler_loop(self) -> None:
        """Deliver due reminders and the optional morning brief."""
        last_brief_date = None
        await asyncio.sleep(2)
        while True:
            try:
                await self._dispatch_due_reminders()
                last_brief_date = await self._maybe_send_daily_brief(last_brief_date)
                await self._process_quality_inbox()
                await self._check_sentinel()
                await asyncio.to_thread(self._cleanup_incoming)
            except Exception:
                LOGGER.exception("Scheduler iteration failed")
            await asyncio.sleep(max(5, self.settings.reminder_poll_seconds))

    @property
    def _reminder_store(self):
        return getattr(self.agent_runner, "reminders", None)

    async def _dispatch_due_reminders(self) -> None:
        store = self._reminder_store
        if store is None:
            return
        for reminder in await asyncio.to_thread(store.due):
            try:
                await self.bot.send_message(
                    reminder.chat_id,
                    f"⏰ Promemoria\n\n{reminder.text}",
                    disable_notification=False,
                )
            except Exception:
                LOGGER.exception("Failed to deliver reminder %s", reminder.id)
                continue
            await asyncio.to_thread(store.mark_sent, reminder)

    async def _maybe_send_daily_brief(self, last_brief_date):
        if not self.settings.daily_brief_enabled:
            return last_brief_date
        timezone_info = ZoneInfo(self.settings.timezone)
        now = datetime.now(timezone_info)
        hour, minute = (int(part) for part in self.settings.daily_brief_time.split(":", 1))
        if now.time() < dt_time(hour, minute) or last_brief_date == now.date():
            return last_brief_date

        text = await asyncio.to_thread(self._build_daily_brief, now)
        try:
            await self.bot.send_message(self.settings.telegram_allowed_user_id, text)
        except Exception:
            LOGGER.exception("Failed to deliver the daily brief")
            return last_brief_date
        return now.date()

    def _build_daily_brief(self, now: datetime) -> str:
        timezone_info = ZoneInfo(self.settings.timezone)
        sections = [f"☀️ **Buongiorno, signore.**\n{italian_date(now)}"]
        sections.append(
            get_weather(
                self.settings.location_name,
                latitude=self.settings.latitude,
                longitude=self.settings.longitude,
                timezone=self.settings.timezone,
            )
        )

        store = self._reminder_store
        if store is not None:
            today = [
                reminder
                for reminder in store.list(self.settings.telegram_allowed_user_id)
                if reminder.due_local(timezone_info).date() == now.date()
            ]
            if today:
                lines = ["⏰ **Oggi**"]
                for reminder in today:
                    lines.append(f"• {reminder.due_local(timezone_info).strftime('%H:%M')} — {reminder.text}")
                sections.append("\n".join(lines))

        return "\n\n".join(sections)

    async def _check_sentinel(self) -> None:
        runner = self.agent_runner
        sentinel = getattr(runner, "sentinel", None)
        state = getattr(runner, "app_state", None)
        enabled = (
            state.get_bool(self.settings.telegram_allowed_user_id, "sentinel", self.settings.sentinel_enabled)
            if state is not None
            else self.settings.sentinel_enabled
        )
        if not enabled or sentinel is None:
            return
        now = time.time()
        if now - self._last_sentinel_check < max(10, self.settings.sentinel_interval_seconds):
            return
        self._last_sentinel_check = now
        result = await asyncio.to_thread(sentinel.check)
        if result.motion:
            await self.bot.send_photo(
                chat_id=self.settings.telegram_allowed_user_id,
                photo=FSInputFile(str(result.snapshot)),
                caption=f"🚨 Movimento rilevato dalla sentinella (differenza {result.difference:.1f}).",
            )

    async def _process_quality_inbox(self) -> None:
        if not self.settings.quality_watch_enabled:
            return
        pending = await asyncio.to_thread(
            pending_quality_files,
            self.settings.quality_watch_path,
            self.settings.app_db_path_obj,
        )
        for path in pending:
            try:
                report, artifacts = await asyncio.to_thread(
                    build_quality_artifacts,
                    path,
                    self.settings.output_path,
                    self.settings.reports_path,
                )
                await asyncio.to_thread(record_snapshot, self.settings.app_db_path_obj, report)
                spec = await asyncio.to_thread(trend_spec, self.settings.app_db_path_obj)
                if spec is not None:
                    trend_path = await asyncio.to_thread(
                        render_chart,
                        self.settings.output_path / f"{path.stem}-trend.png",
                        spec,
                    )
                    artifacts.append(trend_path)
                await self._deliver_artifacts(
                    self.settings.telegram_allowed_user_id,
                    [
                        PendingArtifact(local_path=artifact, caption=f"Analisi qualità — {path.name}")
                        for artifact in artifacts
                    ],
                )
            except Exception:
                LOGGER.exception("Quality watcher failed for %s", path)
            finally:
                with suppress(Exception):
                    await asyncio.to_thread(mark_quality_file, self.settings.app_db_path_obj, path)

    def _cleanup_incoming(self) -> None:
        cutoff = datetime.now().timestamp() - self.settings.file_retention_days * 86400
        if not self.settings.incoming_path.exists():
            return
        for path in self.settings.incoming_path.iterdir():
            if path.is_file() and path.stat().st_mtime < cutoff:
                with suppress(OSError):
                    path.unlink()

    async def handle_text(self, message: Message) -> None:
        await self._process_message(message)

    async def handle_voice(self, message: Message) -> None:
        voice = message.voice
        if voice is None:
            return
        attachment = await self._download_attachment(
            file_id=voice.file_id,
            desired_name=f"voice-{message.message_id}.ogg",
            kind=AttachmentType.AUDIO,
            mime_type="audio/ogg",
        )
        await self._process_message(message, attachments=[attachment])

    async def handle_audio(self, message: Message) -> None:
        audio = message.audio
        if audio is None:
            return
        suffix = Path(audio.file_name or "audio.mp3").suffix or ".mp3"
        attachment = await self._download_attachment(
            file_id=audio.file_id,
            desired_name=f"audio-{message.message_id}{suffix}",
            kind=AttachmentType.AUDIO,
            mime_type=audio.mime_type,
            original_name=audio.file_name,
        )
        await self._process_message(message, attachments=[attachment])

    async def handle_photo(self, message: Message) -> None:
        if not message.photo:
            return
        photo = message.photo[-1]
        attachment = await self._download_attachment(
            file_id=photo.file_id,
            desired_name=f"photo-{message.message_id}.jpg",
            kind=AttachmentType.IMAGE,
            mime_type="image/jpeg",
        )
        await self._process_message(message, attachments=[attachment])

    async def handle_document(self, message: Message) -> None:
        document = message.document
        if document is None:
            return
        kind = self._document_kind(document.file_name or "", document.mime_type)
        suffix = Path(document.file_name or "document.bin").suffix or ".bin"
        attachment = await self._download_attachment(
            file_id=document.file_id,
            desired_name=f"document-{message.message_id}{suffix}",
            kind=kind,
            mime_type=document.mime_type,
            original_name=document.file_name,
        )
        await self._process_message(message, attachments=[attachment])

    async def _process_message(self, message: Message, attachments: list[Attachment] | None = None) -> None:
        if not self._guard(message):
            return

        user = message.from_user
        assert user is not None  # guaranteed by _guard
        incoming = IncomingMessage(
            chat_id=message.chat.id,
            user_id=user.id,
            text=self._extract_user_text(message),
            attachments=attachments or [],
        )

        lock = self._chat_locks.setdefault(message.chat.id, asyncio.Lock())
        async with lock, self._typing(message.chat.id):
            try:
                for attachment in incoming.attachments:
                    if attachment.kind is not AttachmentType.AUDIO:
                        continue
                    try:
                        transcript = await asyncio.to_thread(
                            self.agent_runner.transcribe_audio, attachment.local_path
                        )
                    except Exception:
                        LOGGER.exception("Audio transcription failed for %s", attachment.local_path)
                        await message.answer("⚠️ Non sono riuscito a trascrivere l'audio, procedo senza.")
                        continue
                    incoming.audio_transcript = transcript
                    await self._reply_chunks(message, f"Trascrizione audio:\n\n{transcript}")
                    break

                artifact_queue = ArtifactQueue(
                    self.settings.output_path,
                    self.settings.reports_path,
                    self.settings.workspace_path,
                    self.settings.app_db_path_obj,
                    self.settings,
                )
                async with self._run_semaphore:
                    reply_text = await asyncio.to_thread(self.agent_runner.run, incoming, artifact_queue)
                state = getattr(self.agent_runner, "app_state", None)
                if state is not None and state.get_bool(message.chat.id, "voice_replies", False):
                    await asyncio.to_thread(
                        artifact_queue.create_voice_message,
                        reply_text,
                        "jarvis-reply.ogg",
                        "Risposta vocale",
                    )
                await self._reply_chunks(message, reply_text, parse_mode="Markdown")
                await self._deliver_artifacts(message.chat.id, artifact_queue.items)
            except Exception:
                LOGGER.exception("Failed to process message %s", message.message_id)
                await message.answer(
                    "⚠️ Qualcosa è andato storto mentre elaboravo il messaggio. "
                    "Riprova tra poco."
                )

    @asynccontextmanager
    async def _typing(self, chat_id: int):
        task = asyncio.create_task(self._keep_typing(chat_id))
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _keep_typing(self, chat_id: int) -> None:
        while True:
            with suppress(Exception):
                await self.bot.send_chat_action(chat_id, "typing")
            await asyncio.sleep(4)

    def _extract_user_text(self, message: Message) -> str:
        return (message.text or message.caption or "").strip()

    def _document_kind(self, file_name: str, mime_type: str | None) -> AttachmentType:
        lowered = file_name.lower()
        mime = (mime_type or "").lower()
        if lowered.endswith(".pdf") or mime == "application/pdf":
            return AttachmentType.PDF
        if lowered.endswith(".csv") or mime == "text/csv":
            return AttachmentType.CSV
        if lowered.endswith((".xlsx", ".xls")) or mime in {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
        }:
            return AttachmentType.XLSX
        guessed_mime, _ = mimetypes.guess_type(file_name)
        if (guessed_mime or mime).startswith("image/"):
            return AttachmentType.IMAGE
        return AttachmentType.DOCUMENT

    async def _download_attachment(
        self,
        file_id: str,
        desired_name: str,
        kind: AttachmentType,
        mime_type: str | None = None,
        original_name: str | None = None,
    ) -> Attachment:
        telegram_file = await self.bot.get_file(file_id)
        safe_name = f"{uuid4().hex}-{desired_name}"
        target_path = self.settings.incoming_path / safe_name
        await self.bot.download_file(telegram_file.file_path, destination=target_path)
        return Attachment(
            kind=kind,
            local_path=target_path,
            mime_type=mime_type,
            original_name=original_name,
        )

    async def _reply_chunks(self, message: Message, text: str, parse_mode: str | None = None) -> None:
        clean = text.strip() or "Operazione completata."
        for start in range(0, len(clean), TELEGRAM_MESSAGE_LIMIT):
            chunk = clean[start : start + TELEGRAM_MESSAGE_LIMIT]
            if parse_mode is None:
                await message.answer(chunk)
                continue
            try:
                await message.answer(chunk, parse_mode=parse_mode)
            except TelegramBadRequest:
                # LLM output may contain malformed Markdown: fall back to plain text.
                await message.answer(chunk)

    async def _deliver_artifacts(self, chat_id: int, artifacts: list[PendingArtifact]) -> None:
        for artifact in artifacts:
            suffix = artifact.local_path.suffix.lower()
            input_file = FSInputFile(str(artifact.local_path))
            caption = artifact.caption[:1024]
            if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                await self.bot.send_photo(chat_id=chat_id, photo=input_file, caption=caption)
            elif suffix in {".mp3", ".wav", ".ogg", ".m4a"}:
                await self.bot.send_audio(chat_id=chat_id, audio=input_file, caption=caption)
            else:
                await self.bot.send_document(chat_id=chat_id, document=input_file, caption=caption)
