from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Settings


def capture_screen(path: str | Path) -> Path:
    if platform.system() != "Darwin":
        raise RuntimeError("Cattura schermo disponibile solo su macOS.")
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["screencapture", "-x", str(target)], check=True, timeout=20)
    return target


def capture_camera(path: str | Path, device: str = "0") -> Path:
    if platform.system() != "Darwin":
        raise RuntimeError("Cattura camera disponibile solo su macOS.")
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)

    if shutil.which("imagesnap"):
        subprocess.run(["imagesnap", "-q", str(target)], check=True, timeout=20)
        return target

    if shutil.which("ffmpeg"):
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "avfoundation",
                "-i",
                device,
                "-frames:v",
                "1",
                str(target),
            ],
            check=True,
            timeout=30,
        )
        return target

    raise RuntimeError("Installa 'imagesnap' (brew install imagesnap) oppure ffmpeg per usare la camera.")


def analyze_image(path: str | Path, question: str, settings: Settings) -> str:
    from agno.agent import Agent
    from agno.media import Image
    from agno.models.openrouter import OpenRouterResponses

    agent = Agent(
        name="Jarvis Vision",
        model=OpenRouterResponses(id=settings.openrouter_vision_model),
        markdown=True,
        instructions=[
            "Sei Jarvis. Analizza l'immagine in italiano, in modo preciso e conciso.",
            "Se l'utente fa una domanda specifica, rispondi prima a quella.",
            "Se noti errori, testi o dettagli utili, evidenziali. Non inventare ciò che non vedi.",
        ],
    )
    response = agent.run(
        input=question or "Descrivi l'immagine e segnala ciò che è rilevante.",
        images=[Image(filepath=str(path))],
    )
    return str(response.content).strip()


def image_difference(path_a: str | Path, path_b: str | Path, size: tuple[int, int] = (160, 120)) -> float:
    from PIL import Image, ImageChops, ImageStat

    first = Image.open(path_a).convert("L").resize(size)
    second = Image.open(path_b).convert("L").resize(size)
    diff = ImageChops.difference(first, second)
    statistics = ImageStat.Stat(diff)
    return float(sum(statistics.mean) / len(statistics.mean))


@dataclass(slots=True)
class SentinelResult:
    motion: bool
    difference: float
    snapshot: Path


class Sentinel:
    """Camera motion detector based on visual frame difference."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.output_path.mkdir(parents=True, exist_ok=True)
        self._last_snapshot: Path | None = None

    def check(self) -> SentinelResult:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        snapshot = self.settings.output_path / f"sentinel-{stamp}.jpg"
        capture_camera(snapshot, self.settings.camera_device)

        if self._last_snapshot is None:
            self._last_snapshot = snapshot
            return SentinelResult(False, 0.0, snapshot)

        try:
            difference = image_difference(self._last_snapshot, snapshot)
        except Exception:
            difference = 0.0
        motion = difference >= self.settings.sentinel_threshold
        previous = self._last_snapshot
        self._last_snapshot = snapshot
        if motion and previous.exists():
            previous.unlink(missing_ok=True)
        return SentinelResult(motion, difference, snapshot)
