from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

from .agent import ArtifactQueue, JarvisAgentRunner
from .config import Settings
from .media import synthesize_speech
from .schemas import IncomingMessage

SAMPLE_RATE = 16000
BLOCK_SECONDS = 0.1
ENERGY_THRESHOLD = 0.012


def strip_wake_word(text: str, wake_word: str, require: bool = True) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""
    wake = " ".join(wake_word.lower().split())
    lowered = cleaned.lower()
    if wake and wake in lowered:
        index = lowered.find(wake)
        remainder = cleaned[index + len(wake) :].lstrip(" ,.!?;:-").strip()
        return remainder
    if require:
        return ""
    return cleaned.strip(" ,;:-")


def _write_wav(path: Path, samples) -> None:
    import numpy as np

    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())


def record_utterance(settings: Settings, prompt: str = "Parla ora…") -> Path | None:
    import numpy as np
    import sounddevice as sd

    print(prompt, flush=True)
    frames = []
    recording = False
    silence_started: float | None = None
    started = time.time()

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        device=settings.voice_device,
    ) as stream:
        while True:
            block, _ = stream.read(int(SAMPLE_RATE * BLOCK_SECONDS))
            energy = float(np.sqrt(np.mean(np.square(block))))
            if energy > ENERGY_THRESHOLD:
                recording = True
                silence_started = None
                frames.append(block.copy())
            elif recording:
                frames.append(block.copy())
                if silence_started is None:
                    silence_started = time.time()
                elif time.time() - silence_started >= settings.voice_silence_seconds:
                    break
            if time.time() - started >= settings.voice_max_seconds:
                break

    if not frames:
        return None

    audio = np.concatenate(frames, axis=0)
    target = Path(tempfile.mkdtemp(prefix="jarvis-voice-")) / "utterance.wav"
    _write_wav(target, audio)
    return target


def transcribe_audio(audio_path: Path, settings: Settings) -> str:
    backend = settings.voice_stt_backend.lower()
    if backend in {"auto", "local"}:
        try:
            from faster_whisper import WhisperModel

            model = WhisperModel(settings.voice_stt_model, device="cpu", compute_type="int8")
            segments, _ = model.transcribe(str(audio_path), language="it")
            return " ".join(segment.text.strip() for segment in segments).strip()
        except ImportError:
            if backend == "local":
                raise RuntimeError(
                    "faster-whisper non installato. Esegui: pip install -e '.[voice]'"
                ) from None

    if not settings.openai_api_key:
        raise RuntimeError(
            "Trascrizione non disponibile: installa faster-whisper oppure imposta OPENAI_API_KEY."
        )

    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    with audio_path.open("rb") as handle:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=handle,
            language="it",
        )
    return result.text.strip()


def play_audio(path: Path) -> None:
    if sys.platform == "darwin" and shutil.which("afplay"):
        subprocess.run(["afplay", str(path)], check=False)
        return
    if shutil.which("ffplay"):
        subprocess.run(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)], check=False)
        return
    if shutil.which("aplay"):
        subprocess.run(["aplay", "-q", str(path)], check=False)
        return
    print(f"[audio pronto: {path}]", flush=True)


def speak(text: str, settings: Settings) -> None:
    if not text.strip():
        return
    target = Path(tempfile.mkdtemp(prefix="jarvis-tts-")) / "reply.ogg"
    try:
        path = synthesize_speech(
            text[: settings.voice_reply_max_chars],
            target,
            api_key=settings.openai_api_key,
            model=settings.tts_model,
            voice=settings.tts_voice,
        )
    except Exception as exc:
        print(f"[TTS non disponibile: {exc}]", flush=True)
        return
    play_audio(path)


def wait_for_wake_word(settings: Settings) -> bool:
    """Optional low-power wake word via openWakeWord; falls back to STT gating."""
    try:
        import numpy as np
        import sounddevice as sd
        from openwakeword.model import Model
    except ImportError:
        return False

    try:
        model = Model(wakeword_models=["hey_jarvis"])
    except Exception:
        return False

    print(f"In ascolto per '{settings.voice_wake_word}'…", flush=True)
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        device=settings.voice_device,
    ) as stream:
        while True:
            block, _ = stream.read(1280)
            audio = (block[:, 0] * 32767).astype(np.int16)
            scores = model.predict(audio)
            if scores and max(scores.values()) > 0.5:
                return True


class VoiceAssistant:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.runner = JarvisAgentRunner(settings)
        self.settings.ensure_directories()

    def ask(self, text: str) -> str:
        message = IncomingMessage(
            chat_id=self.settings.telegram_allowed_user_id,
            user_id=self.settings.telegram_allowed_user_id,
            text=text,
        )
        queue = ArtifactQueue(
            self.settings.output_path,
            self.settings.reports_path,
            self.settings.workspace_path,
            self.settings.app_db_path_obj,
            self.settings,
        )
        reply = self.runner.run(message, queue)
        for artifact in queue.items:
            print(f"[file generato: {artifact.local_path}]", flush=True)
        return reply

    def run_once(self, push_to_talk: bool = False) -> bool:
        if not push_to_talk and wait_for_wake_word(self.settings):
            audio = record_utterance(self.settings, "Ti ascolto…")
        else:
            audio = record_utterance(self.settings)
        if audio is None:
            return True

        transcript = transcribe_audio(audio, self.settings)
        text = strip_wake_word(transcript, self.settings.voice_wake_word, require=not push_to_talk)
        if not text:
            print("(nessuna richiesta riconosciuta)", flush=True)
            return True
        if text.lower() in {"esci", "stop", "chiudi", "basta"}:
            return False

        print(f"\nTu: {text}", flush=True)
        reply = self.ask(text)
        print(f"Jarvis: {reply}\n", flush=True)
        speak(reply, self.settings)
        return True

    def loop(self, push_to_talk: bool = False) -> None:
        print("Jarvis voice loop attivo. Di' 'esci' per terminare.", flush=True)
        while True:
            try:
                if not self.run_once(push_to_talk=push_to_talk):
                    break
            except KeyboardInterrupt:
                break
            except Exception as exc:
                print(f"[errore: {exc}]", flush=True)
                time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis voice loop locale")
    parser.add_argument("--push-to-talk", action="store_true", help="Registra solo dopo Invio, senza wake word")
    parser.add_argument("--once", action="store_true", help="Esegui un solo turno")
    args = parser.parse_args()

    settings = Settings()
    settings.validate_required_secrets()

    try:
        import numpy  # noqa: F401
        import sounddevice  # noqa: F401
    except ImportError:
        print(
            "Voice loop non disponibile: installa le dipendenze con\n"
            "  python -m pip install -e '.[voice]'"
        )
        return

    assistant = VoiceAssistant(settings)

    if args.once:
        assistant.run_once(push_to_talk=args.push_to_talk)
    else:
        assistant.loop(push_to_talk=args.push_to_talk)


if __name__ == "__main__":
    main()
