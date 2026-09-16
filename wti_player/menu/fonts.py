"""Type, for the menu renderer.

Two families and no others: Playfair Display and Outfit, the faces the site
and the Player are already set in, vendored under the OFL in
``wti_player/ui/fonts``. Both are variable, so one file covers Outfit 100-900
and Playfair 400-900. Six designs get their difference from structure, scale
and weight rather than from six unrelated typefaces.

The factory's renderer named CSS-style stacks and walked ``C:/Windows/Fonts``
for them. That is why the same theme rendered differently on two machines and
why "Futura, Century Gothic, Trebuchet MS" quietly became Trebuchet. Nothing
here looks outside the repo.

The measuring functions all account for letter-spacing, because Pillow does
not have any and everything on a menu is tracked.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from wti_player.menu.types import RenderUnavailable
from wti_player.ui.theme import FONT_DIR

#: ``family -> filename``. Nothing resolves outside this.
FILES = {
    "display": "PlayfairDisplay.ttf",
    "display-italic": "PlayfairDisplay-Italic.ttf",
    "ui": "Outfit.ttf",
}

#: The weight axis each file actually carries. Asking for 200 of Playfair
#: silently gave 400 before this was clamped, which made a "light" title and
#: a "regular" one identical pictures.
WEIGHT_RANGE = {
    "display": (400, 900),
    "display-italic": (400, 900),
    "ui": (100, 900),
}


def _image_font() -> Any:
    try:
        from PIL import ImageFont
    except ImportError as exc:  # pragma: no cover - Pillow is a dependency here
        raise RenderUnavailable(
            "Pillow is not installed, and the menu renderer is built on it. "
            "pip install pillow"
        ) from exc
    return ImageFont


@lru_cache(maxsize=256)
def face(family: str, size: int, weight: int = 400) -> Any:
    """One font, at one size, at one weight.

    Cached because a design asks for the same face a few hundred times while
    it fits a title, and instancing a variable font is not free.
    """
    ImageFont = _image_font()
    filename = FILES.get(family)
    if filename is None:
        raise KeyError(f"no font family called {family!r}. Have: {', '.join(FILES)}")
    path = FONT_DIR / filename
    if not path.is_file():
        raise RenderUnavailable(
            f"{path} is missing. The menu designs are set in the vendored faces; "
            "run python tools/fetch_fonts.py"
        )
    font = ImageFont.truetype(str(path), max(1, int(size)))
    low, high = WEIGHT_RANGE[family]
    try:
        font.set_variation_by_axes([float(min(high, max(low, weight)))])
    except OSError:  # pragma: no cover - only if the file stops being variable
        pass
    return font


def width(text: str, font: Any, tracking: float = 0.0) -> float:
    """How wide ``text`` draws, letter-spacing included."""
    if not text:
        return 0.0
    return float(font.getlength(text)) + float(font.size) * tracking * (len(text) - 1)


def height_of(font: Any) -> int:
    """Line height for this face. Ascent plus descent, not the em box."""
    ascent, descent = font.getmetrics()
    return int(ascent) + int(descent)


def clean(text: str, *, fallback: str = "") -> str:
    """One printable line, or the fallback.

    Labels come off a web form, and a form is where somebody pastes a line
    break. Pillow refuses to measure multi-line text at all, so a pasted
    newline used to kill the render with an error about text metrics rather
    than about the label that caused it.
    """
    kept = "".join(
        " " if ch.isspace() else ch
        for ch in str(text or "")
        if ch.isprintable() or ch.isspace()
    )
    return " ".join(kept.split()) or fallback


def _split_long_word(word: str, font: Any, tracking: float, max_width: float) -> list[str]:
    """Break one unbreakable word across lines. Last resort, no hyphen added."""
    pieces: list[str] = []
    current = ""
    for ch in word:
        if current and width(current + ch, font, tracking) > max_width:
            pieces.append(current)
            current = ch
        else:
            current += ch
    if current:
        pieces.append(current)
    return pieces or [word]


def wrap(text: str, font: Any, tracking: float, max_width: float) -> list[str]:
    """``text`` broken into lines that fit. Never shortened.

    Truncation is what the old renderer did: "AUDIO AND SU…" on a menu whose
    other four buttons had room to spare. A label that does not fit is a
    layout problem, and the fixes are wrapping and a smaller size, both of
    which keep the words.
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if width(candidate, font, tracking) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        if width(word, font, tracking) > max_width:
            pieces = _split_long_word(word, font, tracking, max_width)
            lines.extend(pieces[:-1])
            current = pieces[-1]
        else:
            current = word
    if current:
        lines.append(current)
    return lines or [""]


class Block:
    """A run of text that has been made to fit, and knows how big it came out."""

    __slots__ = ("font", "height", "leading", "lines", "size", "tracking", "width")

    def __init__(
        self,
        lines: list[str],
        font: Any,
        size: int,
        tracking: float,
        leading: float,
    ) -> None:
        self.lines = lines
        self.font = font
        self.size = size
        self.tracking = tracking
        self.leading = int(size * leading)
        self.width = int(max((width(line, font, tracking) for line in lines), default=0))
        self.height = self.leading * (len(lines) - 1) + height_of(font)


def fit(
    text: str,
    *,
    family: str,
    weight: int,
    max_width: float,
    max_height: float | None = None,
    max_lines: int = 3,
    size: int,
    min_size: int,
    tracking: float = 0.0,
    leading: float = 1.12,
) -> Block:
    """Set ``text`` as large as it goes without cutting a word off.

    Shrinks first, in whole pixels, then accepts more lines. Both are
    reversible in a way truncation is not: a title two points smaller is
    still the title. It stops at ``min_size`` and returns whatever that gives,
    which is the only case where a block can end up taller than asked for -
    and a design that hits it should be told, not silently trimmed.
    """
    body = clean(text)
    for trial in range(int(size), int(min_size) - 1, -1):
        font = face(family, trial, weight)
        lines = wrap(body, font, tracking, max_width)
        if len(lines) > max_lines:
            continue
        block = Block(lines, font, trial, tracking, leading)
        if max_height is not None and block.height > max_height:
            continue
        return block
    font = face(family, int(min_size), weight)
    return Block(wrap(body, font, tracking, max_width), font, int(min_size), tracking, leading)


__all__ = [
    "FILES",
    "WEIGHT_RANGE",
    "Block",
    "clean",
    "face",
    "fit",
    "height_of",
    "width",
    "wrap",
]
