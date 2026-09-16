"""Render every menu design and put them on one page to look at.

A menu cannot be reviewed from a palette or from a passing test. It has to be
looked at, with real artwork and without, with a short title and with a long
one, because those are the four ways a design falls over and only one of them
shows up in the happy case.

    python tools/menu_contact_sheet.py
    python tools/menu_contact_sheet.py --stills path/to/stills --out _design/menus

Each composite shows the menu as a person would see it: button one selected,
button two activated, the rest at rest. That is the only way three states get
reviewed at once.

Writes four sheets - bare/artwork against short/long title - plus every
full-size composite, and prints the measured contrast for each.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from wti_player.menu import THEMES, Button, render_menu  # noqa: E402
from wti_player.menu.types import MENU_HEIGHT, MENU_WIDTH  # noqa: E402

DEFAULT_BUTTONS = (
    ("play", "Play"),
    ("chapters", "Chapters"),
    ("audio", "Audio and subtitles"),
    ("extras", "Extras"),
    ("about", "About this disc"),
)

SHORT_TITLE = "Nosferatu"
#: Deliberately awkward. Long, and with one word nothing can shorten.
LONG_TITLE = "The Cabinet of Dr. Caligari and Other Expressionist Nightmares"

#: A panel on the sheet. Six panels, three across.
PANEL_WIDTH = 800
COLUMNS = 3


@dataclass(frozen=True)
class Shot:
    theme: str
    title: str
    still: Path | None
    contrast: float
    display: float
    used_artwork: bool
    composite: Path


def compose(menu, out: Path) -> Path:
    """Background plus every button tile, with two of them off their rest state."""
    from PIL import Image

    frame = Image.open(menu.background).convert("RGBA")
    for index, button in enumerate(menu.buttons):
        state = "selected" if index == 0 else "activated" if index == 1 else "normal"
        with Image.open(button.images[state]) as tile:
            frame.alpha_composite(tile.convert("RGBA"), (button.x, button.y))
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.convert("RGB").save(out, "PNG")
    return out


def sheet(shots: list[Shot], out: Path, heading: str) -> Path:
    """Six composites on one page, labelled."""
    from PIL import Image, ImageDraw

    from wti_player.menu import fonts

    scale = PANEL_WIDTH / MENU_WIDTH
    panel_height = int(MENU_HEIGHT * scale)
    caption = 46
    rows = (len(shots) + COLUMNS - 1) // COLUMNS
    width = PANEL_WIDTH * COLUMNS
    page = Image.new("RGB", (width, 64 + rows * (panel_height + caption)), (18, 18, 20))
    draw = ImageDraw.Draw(page)
    draw.text((18, 20), heading, font=fonts.face("ui", 28, 600), fill=(236, 236, 232))

    label_font = fonts.face("ui", 19, 500)
    note_font = fonts.face("ui", 17, 400)
    for index, shot in enumerate(shots):
        column, row = index % COLUMNS, index // COLUMNS
        x = column * PANEL_WIDTH
        y = 64 + row * (panel_height + caption)
        with Image.open(shot.composite) as art:
            page.paste(art.resize((PANEL_WIDTH, panel_height), Image.LANCZOS), (x, y))
        draw.text((x + 14, y + panel_height + 12), shot.theme, font=label_font, fill=(236, 236, 232))
        draw.text(
            (x + 14 + 210, y + panel_height + 13),
            f"buttons {shot.contrast:.2f}:1   display {shot.display:.2f}:1"
            f"   artwork {'yes' if shot.used_artwork else 'none'}",
            font=note_font,
            fill=(150, 152, 156),
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    page.save(out, "PNG")
    return out


def stills_for(directory: Path | None) -> list[Path]:
    if directory is None or not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stills", type=Path, default=REPO / "_design" / "menus" / "stills")
    parser.add_argument("--out", type=Path, default=REPO / "_design" / "menus")
    parser.add_argument(
        "--full", type=Path, default=None, help="where full-size composites go (default: --out/full)"
    )
    args = parser.parse_args(argv)

    pool = stills_for(args.stills)
    if not pool:
        print(f"no stills in {args.stills}; rendering the bare pass only")
    full = args.full or (args.out / "full")

    keys = list(THEMES)
    buttons = [Button(key=key, label=label) for key, label in DEFAULT_BUTTONS]
    written: list[Path] = []

    for title_name, title in (("short", SHORT_TITLE), ("long", LONG_TITLE)):
        for art_name, use_art in (("bare", False), ("artwork", True)):
            if use_art and not pool:
                continue
            shots: list[Shot] = []
            for index, key in enumerate(keys):
                still = pool[index % len(pool)] if use_art else None
                tag = f"{key}-{title_name}-{art_name}"
                menu = render_menu(
                    buttons, full / tag, theme_key=key, title=title, still=still, poster=still
                )
                shots.append(
                    Shot(
                        theme=THEMES[key].name,
                        title=title,
                        still=still,
                        contrast=menu.contrast,
                        display=menu.display_contrast,
                        used_artwork=menu.used_artwork,
                        composite=compose(menu, full / tag / "composite.png"),
                    )
                )
                print(
                    f"  {key:16} {title_name:5} {art_name:7} "
                    f"buttons {menu.contrast:5.2f}:1  display {menu.display_contrast:5.2f}:1"
                    f"  labels {' / '.join(menu.labels)}"
                )
            heading = f"We The Indies film menus - {title_name} title, {art_name}"
            written.append(sheet(shots, args.out / f"contact-{title_name}-{art_name}.png", heading))

    print()
    for path in written:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
