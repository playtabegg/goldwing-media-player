"""What a design is, and what it is handed.

A design is not a row of colours any more. The old system made a theme a
palette plus a layout name, and the result was six screens with the same
bones - a title at the top and a list of words under it - in six colour
schemes. Six designs that are actually different cannot come out of one
drawing routine, so each one here draws itself and shares only materials.

What they all still share is the contract: given a title, some buttons and
whatever artwork exists, produce a background picture and a set of button
rectangles with a painter for each. The renderer does the rest, including
checking that what came out can be read.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from wti_player.menu import paint
from wti_player.menu.surface import Surface
from wti_player.menu.types import MENU_HEIGHT, MENU_WIDTH, Button, safe_box

#: A design draws one button into a fresh surface, once per state.
Painter = Callable[[Surface, str], None]


@dataclass(frozen=True)
class Slot:
    """One button's rectangle on the frame, and how to paint it.

    The rectangle is fixed across all three states because the HDMV writer
    positions it once and only swaps the picture inside. States of different
    sizes make the selection appear to jump as it moves.
    """

    key: str
    label: str
    x: int
    y: int
    width: int
    height: int
    paint: Painter


@dataclass(frozen=True)
class Composition:
    """What a design hands back."""

    background: Surface
    slots: tuple[Slot, ...]
    used_artwork: bool


@dataclass
class Scene:
    """Everything a design is given to work with."""

    title: str
    buttons: tuple[Button, ...]
    #: The film's frame still and its poster, either or both possibly absent.
    still: Any = None
    poster: Any = None
    seed: int = 1968

    def art(self, prefer: Literal["still", "poster"] = "still") -> Any:
        """The picture this design wants, or the other one, or nothing.

        The old renderer keyed off a per-theme ``backdrop`` name, and five of
        the six named a poster. Passing a valid still to all six produced one
        composited render and five identical flat grounds, which read as a
        renderer that ignores artwork. A design asks for what suits it and
        takes what it is given.
        """
        first, second = (self.still, self.poster) if prefer == "still" else (self.poster, self.still)
        return first if first is not None else second


class Design:
    """Base class. Subclasses override :meth:`compose` and the class fields."""

    key: str = ""
    name: str = ""
    description: str = ""
    #: For whoever reviews the render. Not shown on screen.
    references: tuple[str, ...] = ()
    #: The colour the buttons sit on. Used only if the contrast gate has to
    #: reinforce the backing behind them, which none of the six needs on the
    #: artwork tried so far - every one of them puts its labels on stock,
    #: not on the picture.
    backing: str = "#000000"
    #: Whether that backing is lighter than the labels on it.
    backing_is_light: bool = False

    def compose(self, scene: Scene) -> Composition:  # pragma: no cover - abstract
        raise NotImplementedError

    # -- shared helpers -----------------------------------------------------

    @staticmethod
    def frame(fill: str) -> Surface:
        return Surface((MENU_WIDTH, MENU_HEIGHT), paint.rgba(fill))

    @staticmethod
    def safe() -> tuple[int, int, int, int]:
        return safe_box()


@dataclass(frozen=True)
class ThemeEntry:
    """What the registry exposes, for callers that treat themes as data.

    Same attribute names the factory's ``FilmTheme`` had where they still
    mean something, so ``tools/theme_menu.py`` listing themes keeps working.
    """

    key: str
    name: str
    description: str
    references: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LabelSet:
    """Every button label, set at one size, none of them cut short."""

    font: Any
    size: int
    tracking: float
    #: Wrapped lines, per button, in the order they were handed in.
    lines: tuple[tuple[str, ...], ...]
    leading: int

    @property
    def depth(self) -> int:
        """The most lines any one label needed."""
        return max(len(lines) for lines in self.lines)

    @property
    def text_height(self) -> int:
        from wti_player.menu import fonts

        return self.leading * (self.depth - 1) + fonts.height_of(self.font)


def set_labels(
    labels: list[str],
    *,
    family: str,
    weight: int,
    max_width: float,
    size: int,
    min_size: int,
    tracking: float = 0.0,
    max_lines: int = 2,
    leading: float = 1.12,
) -> LabelSet:
    """One type size that fits all of them, chosen by measuring.

    The rule is that nothing gets truncated. "AUDIO AND SU…" and "ABOUT THIS
    D…" shipped on the music theme because its five buttons were laid across
    one line and each got a fifth of the width; the fix is to make the type
    fit, not the words.

    Every button gets the same size even if only one is long. A menu whose
    buttons are set at different sizes reads as broken rather than as full.
    """
    from wti_player.menu import fonts

    cleaned = [fonts.clean(label) for label in labels]
    fallback: tuple[Any, int, list[list[str]]] | None = None
    for trial in range(int(size), int(min_size) - 1, -1):
        font = fonts.face(family, trial, weight)
        wrapped = [fonts.wrap(label, font, tracking, max_width) for label in cleaned]
        depth = max(len(lines) for lines in wrapped)
        if depth == 1:
            return LabelSet(font, trial, tracking, tuple(tuple(w) for w in wrapped), int(trial * leading))
        if fallback is None and depth <= max_lines:
            fallback = (font, trial, wrapped)
    if fallback is not None:
        font, trial, wrapped = fallback
        return LabelSet(font, trial, tracking, tuple(tuple(w) for w in wrapped), int(trial * leading))
    font = fonts.face(family, int(min_size), weight)
    wrapped = [fonts.wrap(label, font, tracking, max_width) for label in cleaned]
    return LabelSet(
        font, int(min_size), tracking, tuple(tuple(w) for w in wrapped), int(min_size * leading)
    )


__all__ = [
    "Composition",
    "Design",
    "LabelSet",
    "Painter",
    "Scene",
    "Slot",
    "ThemeEntry",
    "set_labels",
]
