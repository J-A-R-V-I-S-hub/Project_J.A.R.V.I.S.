from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path


def _macos_say(text: str, output: Path) -> Path:
    if not shutil.which("say") or not shutil.which("afconvert"):
        raise RuntimeError(
            "TTS non configurato: imposta OPENAI_API_KEY oppure esegui su macOS con i comandi 'say' e 'afconvert'."
        )
    aiff_path = output.with_suffix(".aiff")
    target = output.with_suffix(".m4a")
    subprocess.run(["say", "-o", str(aiff_path), text], check=True, capture_output=True)
    subprocess.run(
        ["afconvert", "-f", "m4af", "-d", "aac", str(aiff_path), str(target)],
        check=True,
        capture_output=True,
    )
    aiff_path.unlink(missing_ok=True)
    return target


def synthesize_speech(
    text: str,
    output_path: str | Path,
    api_key: str | None = None,
    model: str = "gpt-4o-mini-tts",
    voice: str = "alloy",
) -> Path:
    """Synthesize speech to an audio file (OpenAI if configured, else macOS say)."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    clean = text.strip()
    if not clean:
        raise ValueError("Testo vuoto da sintetizzare.")

    if api_key:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        target = output.with_suffix(".ogg")
        with client.audio.speech.with_streaming_response.create(
            model=model,
            voice=voice,
            input=clean,
            response_format="opus",
        ) as response:
            response.stream_to_file(target)
        return target

    return _macos_say(clean, output)


def generate_image(
    prompt: str,
    output_path: str | Path,
    api_key: str | None,
    model: str = "gpt-image-1",
    size: str = "1024x1024",
) -> Path:
    """Generate an image with the OpenAI images API."""
    if not api_key:
        raise RuntimeError("Generazione immagini non configurata: imposta OPENAI_API_KEY.")
    from openai import OpenAI

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    clean = prompt.strip()
    if not clean:
        raise ValueError("Prompt vuoto.")

    client = OpenAI(api_key=api_key)
    response = client.images.generate(model=model, prompt=clean, size=size)
    item = response.data[0]
    if getattr(item, "b64_json", None):
        output.write_bytes(base64.b64decode(item.b64_json))
    elif getattr(item, "url", None):
        import httpx

        output.write_bytes(httpx.get(item.url, timeout=60).content)
    else:
        raise RuntimeError("Il provider immagini non ha restituito dati.")
    return output
