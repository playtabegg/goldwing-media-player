"""Everything a DVD menu needs, gathered in one place.

Six pieces were built separately, each complete and tested on its own:

    formats/ifo         which chains are menus, and the sixteen colours
                        each one is drawn in
    formats/dvd_nav     the NAV pack: where the buttons are, what they run,
                        and how they are coloured when lit
    formats/dvd_spu     the subpicture decoder: the words on the buttons
    formats/dvd_vm      what a button's eight bytes of command mean
    dvd/menu_stream     getting the subpicture out of the VOB
    dvd/navigator       which button is lit, and what pressing it means

This is the seventh: it reads a disc and hands back a menu ready to put on
screen. It is the only place that knows all six exist, and it touches no
engine and no widget. Give it a folder and it gives you a :class:`DiscMenu`,
which makes the navigation layer testable without a disc drive or a window.

Nothing here raises for a bad disc. A disc whose menu cannot be read still
plays its titles.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..formats import dvd_nav, dvd_spu, ifo
from . import menu_stream
from .navigator import Action, Navigator

#: A DVD's picture, and the coordinate space its buttons are in.
DVD_WIDTH = 720
DVD_HEIGHT = 480

#: What to fall back to when a disc's chain carries no palette. Sixteen
#: greys: a menu drawn in these is legible, which is the whole requirement.
#: Sixteen, counted rather than assumed. ``range(16, 256, 16)`` looks like
#: sixteen greys and is fifteen, and the entry it leaves out is index 15 —
#: which by convention is the white a menu's text is drawn in. A disc with no
#: palette of its own then got black text on a black ground: a menu nobody
#: can see, which is worse than a menu drawn in the wrong colours.
#:
#: 16 to 235 is the video-legal range for luma; outside it a television
#: clips.
_FALLBACK_PALETTE = tuple(
    (round(16 + step * (235 - 16) / 15) << 16) | (0x80 << 8) | 0x80
    for step in range(16)
)


@dataclass(frozen=True)
class DiscMenu:
    """One menu, read off a disc and ready to draw.

    ``navigator`` holds the selection and turns a press into an action.
    ``subpicture`` is the picture the buttons are drawn in. ``palette`` is
    the sixteen colours both of those index into.
    """

    navigator: Navigator
    subpicture: dvd_spu.Subpicture | None
    palette: tuple[int, ...]
    #: Which menu this is: root, title, chapter, audio…
    kind: str
    #: The VOB its video is in, for the engine to open.
    vob: Path
    #: Where the chain's first cell starts, in sectors.
    first_sector: int = 0
    #: What the menu's own entry forced (an activated button on arrival), if
    #: anything. Computed when the menu is read; the window carries it out
    #: once the menu is on screen. It used to be thrown away.
    entry_action: Action | None = None

    @property
    def drawable(self) -> bool:
        """Is there anything to put on screen beyond the video?"""
        return self.subpicture is not None and not self.subpicture.is_blank

    @property
    def name(self) -> str:
        return {
            "root": "Main menu",
            "title": "Title menu",
            "chapter": "Chapter menu",
            "audio": "Audio menu",
            "subtitle": "Subtitle menu",
            "angle": "Angle menu",
        }.get(self.kind, self.kind.title())

    def colours(self, *, lit: bool = False) -> tuple[tuple[int, int, int, int], ...] | None:
        """The four RGBA colours the subpicture is painted in.

        ``lit`` asks for the ones the selected button uses instead, which is
        how a DVD highlight works: the same pixels, four different palette
        entries.
        """
        highlight = self.navigator.highlight
        if highlight is None:
            return None
        if not lit:
            return None
        colours = highlight.colours_for(self.navigator.selected_button)
        if colours is None:
            return None
        return dvd_spu.resolve_palette(
            list(self.palette), colours.selected_palette, colours.selected_alpha
        )


def read(root: Path | str, *, title_set: int = 1, kind: str = "") -> DiscMenu | None:
    """The menu a viewer means when they press the menu button.

    ``kind`` asks for a particular one — "root", "chapter", "audio". Left
    empty, the disc's root menu is used, falling back to the title menu and
    then the chapter menu, which is the order every player uses and the order
    a disc's own tables imply.

    Returns ``None`` when the disc has no menu, or has one we cannot read.
    """
    try:
        return _read(Path(root), title_set, kind)
    except (OSError, ValueError, IndexError):
        # A disc with a bad sector should degrade to "no menu", never to an
        # exception in front of somebody holding a remote.
        return None


def _read(root: Path, title_set: int, kind: str) -> DiscMenu | None:
    menus = ifo.read_menus(root, title_set)
    if not menus.has_menus or not menus.vob_files:
        return None

    chosen = menus.of_kind(kind) if kind else menus.root
    if chosen is None:
        return None

    palette = chosen.chain.palette or _FALLBACK_PALETTE

    # The menu's video is in the title set's own VOB, or the disc's. Both are
    # tried, in that order, because a disc can put its root menu in either.
    for vob in menus.vob_files:
        highlight = dvd_nav.first_menu(vob)
        if highlight is None or not highlight.has_buttons:
            continue
        picture = menu_stream.read_menu_picture(vob)
        navigator = Navigator(title_set=title_set)
        forced = navigator.show(highlight)
        return DiscMenu(
            navigator=navigator,
            subpicture=picture.subpicture if picture is not None else None,
            palette=tuple(palette),
            kind=chosen.kind,
            vob=vob,
            first_sector=chosen.chain.first_sector,
            entry_action=None if forced.is_nothing else forced,
        )
    return None


def describe(root: Path | str, *, title_set: int = 1) -> list[str]:
    """What this disc's menus look like from outside, for the inspector.

    Reads and says; changes nothing. Written for the moment somebody puts in
    a disc whose menu does not come up and wants to know which of the six
    pieces above found nothing.
    """
    root = Path(root)
    lines: list[str] = []
    try:
        menus = ifo.read_menus(root, title_set)
    except (OSError, ValueError):
        return ["The disc's menu tables could not be read."]

    if not menus.has_menus:
        lines.append("No menu tables on this disc.")
        return lines

    lines.append(f"{len(menus.menus)} menu chain(s):")
    for menu in menus.menus:
        palette = "with a palette" if menu.chain.palette else "NO PALETTE"
        lines.append(
            f"  {menu.name:<14} {menu.domain:<10} language {menu.language or '?':<3} {palette}"
        )

    if not menus.vob_files:
        lines.append("No menu VOB — the tables point at video that is not there.")
        return lines

    for vob in menus.vob_files:
        size = vob.stat().st_size if vob.is_file() else 0
        lines.append(f"  {vob.name} ({size / 1e6:,.1f} MB)")
        highlight = dvd_nav.first_menu(vob)
        if highlight is None:
            lines.append("    no NAV pack carrying a highlight")
            continue
        real = [button for button in highlight.buttons if button.is_real]
        lines.append(f"    {len(real)} button(s), {highlight.selected_button} selected first")
        picture = menu_stream.read_menu_picture(vob)
        if picture is None:
            lines.append("    NO SUBPICTURE — the buttons would be invisible")
        else:
            lines.append(
                f"    subpicture {picture.subpicture.width}x{picture.subpicture.height}"
                f" from stream {picture.stream - menu_stream.SPU_FIRST}"
            )
    return lines


__all__ = ["DVD_HEIGHT", "DVD_WIDTH", "DiscMenu", "describe", "read"]
