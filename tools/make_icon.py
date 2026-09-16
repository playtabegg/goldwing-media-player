"""Draw the Player's icon.

An icon is not decoration on Windows. It is how somebody finds the program
in a taskbar of twenty identical grey rectangles, and how they tell an
installer they trust from one they do not. A build with `icon=None` ships
PyInstaller's own mark, which belongs to somebody else's project.

Drawn rather than drawn-by-hand so the sizes stay consistent: Windows picks
from six, and the 16px one is not the 256px one scaled down — at 16px the
hole and the highlight have to be redrawn or the whole thing turns to mud.

    python tools/make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "wti_player" / "ui" / "player.ico"
MARK = REPO / "wti_player" / "ui" / "marks" / "goldwing.png"

#: The Player's own palette, from wti_player/ui/theme.py.
INK = (13, 15, 20, 255)
BRASS = (201, 169, 97, 255)
BRASS_HI = (220, 192, 127, 255)
BONE = (232, 226, 214, 255)

#: What Windows asks for. Everything from the taskbar to the Alt-Tab card.
SIZES = (16, 24, 32, 48, 64, 128, 256)


def _pillow():
    try:
        from PIL import Image, ImageDraw

        return Image, ImageDraw
    except ImportError:  # pragma: no cover - Pillow is a dependency
        raise SystemExit("Pillow is not installed, and this draws with it.") from None


def draw(size: int):
    """The gold bird on an ink plate, or a disc if the bird file is missing.

    Supersampled 4x and then reduced, because a shape drawn straight at
    16 pixels has stairs on it and a shape reduced from 64 does not.
    """
    _pillow()  # Pillow must be importable before either branch draws
    if MARK.is_file():
        return _bird(size)
    return _disc(size)


def _bird(size: int):
    """The Goldwing mark, on the same rounded plate as the rest of the set."""
    Image, ImageDraw = _pillow()
    scale = 4
    edge = size * scale
    image = Image.new("RGBA", (edge, edge), (0, 0, 0, 0))
    draw_on = ImageDraw.Draw(image)
    radius = int(edge * 0.22)
    draw_on.rounded_rectangle((0, 0, edge - 1, edge - 1), radius=radius, fill=INK)
    mark = Image.open(MARK).convert("RGBA")
    inner = int(edge * 0.78)
    mark = mark.resize((inner, inner), Image.LANCZOS)
    left = (edge - inner) // 2
    image.alpha_composite(mark, (left, left))
    return image.resize((size, size), Image.LANCZOS)


def _disc(size: int):
    Image, ImageDraw = _pillow()
    scale = 4
    edge = size * scale
    image = Image.new("RGBA", (edge, edge), (0, 0, 0, 0))
    draw_on = ImageDraw.Draw(image)

    # A rounded square of ink, the way every other icon on the taskbar is
    # shaped, so this one sits among them rather than beside them.
    radius = int(edge * 0.22)
    draw_on.rounded_rectangle((0, 0, edge - 1, edge - 1), radius=radius, fill=INK)

    # The disc.
    margin = edge * 0.18
    stroke = max(1, int(edge * 0.055))
    box = (margin, margin, edge - margin, edge - margin)
    draw_on.ellipse(box, outline=BRASS, width=stroke)

    # Where the light catches it: the same ring, brighter for a quarter of
    # its run. Drawn at the ring's own radius and width, so it reads as one
    # band changing brightness rather than as a notch cut out of it.
    if size >= 24:
        draw_on.arc(box, start=190, end=265, fill=BRASS_HI, width=stroke)

    # The hole. Bigger proportionally at small sizes: a to-scale hole at
    # 16px closes up and the disc becomes a dot.
    hole = edge * (0.20 if size <= 24 else 0.15)
    centre = edge / 2
    draw_on.ellipse(
        (centre - hole, centre - hole, centre + hole, centre + hole),
        fill=INK,
        outline=BONE if size >= 32 else None,
        width=max(1, int(edge * 0.012)),
    )
    return image.resize((size, size), Image.LANCZOS)


def build(out: Path = OUT) -> Path:
    _image, _draw = _pillow()
    frames = [draw(size) for size in SIZES]
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[-1].save(out, format="ICO", sizes=[(s, s) for s in SIZES])
    return out


def main() -> int:
    path = build()
    print(f"wrote {path} ({path.stat().st_size} bytes, {len(SIZES)} sizes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
