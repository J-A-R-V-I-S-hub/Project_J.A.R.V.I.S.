from pathlib import Path

from PIL import Image

from jarvis_bot.vision import image_difference


def test_image_difference_detects_change(tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (120, 90), (0, 0, 0)).save(first)
    Image.new("RGB", (120, 90), (0, 0, 0)).save(second)

    assert image_difference(first, second) == 0.0

    Image.new("RGB", (120, 90), (255, 255, 255)).save(second)
    assert image_difference(first, second) > 20
