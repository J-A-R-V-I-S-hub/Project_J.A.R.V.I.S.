from __future__ import annotations

import asyncio
import logging
import mimetypes
from contextlib import asynccontextmanager, suppress
from datetime import datetime, time as dt_time
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from .agent import ArtifactQueue, JarvisAgentRunner
from .config import Settings
from .integrations.weather import get_weather
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
    "/voice on|off — risposte vocali\n\n"
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
        self._register_handlers()

    def _register_handlers(self) -> None:
        # Commands must be registered before the catch-all text handler.
        self.dispatcher.message.register(self.handle_start, Command("start"))
        self.dispatcher.message.register(self.handle_help, Command("help"))
        self.dispatcher.message.register(self.handle_reset, Command("reset"))
        self.dispatcher.message.register(self.handle_stats, Command("stats"))
        self.dispatcher.message.register(self.handle_files, Command("files"))
        self.dispatcher.message.register(self.handle_voice_mode, Command("voice"))
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
        await message.answer(HELP_TEXT)

    async def handle_help(self, message: Message) -> None:
        if not self._guard(message):
            return
        await message.answer(HELP_TEXT)

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
        await message.answer(format_stats(stats))

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
        await message.answer("\n".join(lines))

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
            await message.answer(f"Risposte vocali: **{status}**.\nUsa /voice on oppure /voice off.")
            return
        enabled = parts[1].strip().lower() in {"on", "si", "sì", "true", "1", "attiva", "attive"}
        state.set(message.chat.id, "voice_replies", "true" if enabled else "false")
        await message.answer("Risposte vocali attivate. 🔊" if enabled else "Risposte vocali disattivate. 🔇")

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
        async with lock:
            async with self._typing(message.chat.id):
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
                    await self._reply_chunks(message, reply_text)
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

    async def _reply_chunks(self, message: Message, text: str) -> None:
        clean = text.strip() or "Operazione completata."
        for start in range(0, len(clean), TELEGRAM_MESSAGE_LIMIT):
            await message.answer(clean[start : start + TELEGRAM_MESSAGE_LIMIT])

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
