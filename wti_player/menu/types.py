"""The shapes the renderer hands back, and the frame it draws in.

Deliberately the same names and fields the factory's renderer already
exposes (``rialto2/rialto_core/film_menu_render.py``), so the other stream
can swap one import and keep its call sites. Anything added here has a
default, for the same reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

#: The frame every menu is authored at. BD-ROM's only HD menu size.
MENU_WIDTH = 1920
MENU_HEIGHT = 1080

#: The outer five percent of a frame can be off the edge of a television.
#: Nothing pressable and nothing readable goes there.
TITLE_SAFE_MARGIN = 0.05

ButtonState = Literal["normal", "selected", "activated"]
BUTTON_STATES: tuple[ButtonState, ...] = ("normal", "selected", "activated")

#: WCAG's ratio for body text. A button label has to clear it against the
#: pixels actually behind it, measured, not guessed at from the palette.
MIN_CONTRAST = 4.5

#: Large display type gets WCAG's large-text ratio. Titles here run
#: 50-120px, well past the 24px the guideline draws the line at.
MIN_LARGE_CONTRAST = 3.0


class RenderUnavailable(RuntimeError):
    """Pillow is not installed. The renderer is built on it."""


class ContrastFailure(RuntimeError):
    """A label came out unreadable and reinforcing the backing did not fix it.

    Raised rather than shipped. The old renderer reported a scrim strength
    of 0.00 while drawing grey monospace on a grey photograph, so a number
    that says "no correction needed" and a menu nobody can read looked the
    same from the outside.
    """


@dataclass(frozen=True)
class Button:
    """One thing on the menu."""

    key: str
    label: str


@dataclass(frozen=True)
class RenderedButton:
    """Where a button sits, and the three pictures of it.

    The three images are always the same size. The HDMV writer positions
    one rectangle and swaps the picture inside it; states of different
    sizes make the selection appear to jump.
    """

    key: str
    label: str
    x: int
    y: int
    width: int
    height: int
    #: ``{state: path}``, all three present, all three the same size.
    images: dict[str, Path]
    #: Worst measured contrast of this button's text against what is behind
    #: it, across all three states. Never below :data:`MIN_CONTRAST` in a
    #: menu that was returned rather than raised on.
    contrast: float = 0.0


@dataclass(frozen=True)
class RenderedMenu:
    """Everything one menu is made of."""

    background: Path
    buttons: tuple[RenderedButton, ...]
    theme_key: str
    #: Kept for the factory's call sites. How hard the backing behind the
    #: buttons had to be reinforced, 0.0 when the design's own structure
    #: was enough. All six designs are built so it is 0.0; a strange piece
    #: of artwork is what it exists for.
    local_scrim: float = 0.0
    #: Worst button contrast on the whole menu.
    contrast: float = 0.0
    #: Worst contrast of the display type - title, captions - against what
    #: is behind it. Held to :data:`MIN_LARGE_CONTRAST`.
    display_contrast: float = 0.0
    #: Whether the film's own artwork was used in this render.
    used_artwork: bool = False
    #: What each button ended up saying. Equal to the input labels, cased
    #: by the design. A theme that cannot fit a label shrinks its type or
    #: wraps; nothing is ever cut short.
    labels: tuple[str, ...] = field(default_factory=tuple)


def safe_box() -> tuple[int, int, int, int]:
    """``(left, top, right, bottom)`` of the title-safe area, in pixels."""
    margin_x = int(MENU_WIDTH * TITLE_SAFE_MARGIN)
    margin_y = int(MENU_HEIGHT * TITLE_SAFE_MARGIN)
    return (margin_x, margin_y, MENU_WIDTH - margin_x, MENU_HEIGHT - margin_y)


__all__ = [
    "BUTTON_STATES",
    "MENU_HEIGHT",
    "MENU_WIDTH",
    "MIN_CONTRAST",
    "MIN_LARGE_CONTRAST",
    "TITLE_SAFE_MARGIN",
    "Button",
    "ButtonState",
    "ContrastFailure",
    "RenderUnavailable",
    "RenderedButton",
    "RenderedMenu",
    "safe_box",
]
