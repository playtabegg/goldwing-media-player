"""Turn one of the factory's film-menu themes into an HDMV stream.

The bridge between two halves that were built in different streams and have
not met.

The factory stream (`rialto2`) has six film-menu themes as data and a
renderer that produces exactly what a Blu-ray menu is made of: a background
picture, and per button three flat images the player swaps between. Its own
status doc says the next piece — the HDMV generator — is not started, and
that if it is not done by Sept 10 the film discs ship menu-less.

The Player stream has that piece and has had it since the day-one spike:
`tests/fixtures/authoring/hdmv.py` writes an interactive-graphics stream that
libbluray navigates, and `tools/author_disc.py` puts one on a disc.

This joins them. It reads the themes read-only, calls the renderer, and hands
back segments ready to splice into a menu clip.

    python tools/theme_menu.py --list
    python tools/theme_menu.py classic_cinema --title "The Long Way Round"

`rialto2` is not modified and not imported by anything that ships. This is a
tool; the Player itself has no idea the factory exists.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
FACTORY = REPO.parent / "rialto2"
sys.path.insert(0, str(REPO))
# Appended, never prepended: the factory has a `tests` package of its own and
# putting it first shadows ours, which fails a long way from here.
if FACTORY.is_dir() and str(FACTORY) not in sys.path:
    sys.path.append(str(FACTORY))

from tests.fixtures.authoring import graphics, hdmv  # noqa: E402

#: What a Blu-ray HD menu is authored at, and what the themes render at.
MENU_WIDTH = 1920
MENU_HEIGHT = 1080

#: The buttons a film disc offers, in the order they appear. The factory's
#: renderer takes any list; this is the set its own previews were made with.
DEFAULT_BUTTONS = (
    ("play", "Play"),
    ("chapters", "Chapters"),
    ("audio", "Audio and subtitles"),
    ("extras", "Extras"),
    ("about", "About this disc"),
)


#: Where the designs come from. "player" is `wti_player.menu`, the six
#: redrawn designs in this repo; "factory" is rialto2's original renderer,
#: kept reachable so the two can be put side by side.
PLAYER, RIALTO = "player", "factory"


class ThemesUnavailable(RuntimeError):
    """The renderer asked for will not import."""


def factory(source: str = PLAYER):
    """The theme registry and the renderer.

    Both halves come from one module now. `wti_player.menu` exposes THEMES
    the way `film_themes` did and render_menu the way `film_menu_render` did,
    which is what "drop-in" had to mean for this to be adoptable: the factory
    changes this import and nothing else.
    """
    if source == RIALTO:
        try:
            from rialto_core import film_menu_render, film_themes
        except ImportError as error:
            raise ThemesUnavailable(
                f"rialto2's own renderer lives in {FACTORY} and could not be imported: {error}"
            ) from error
        return film_themes, film_menu_render
    try:
        from wti_player import menu
    except ImportError as error:  # pragma: no cover - the package is right here
        raise ThemesUnavailable(f"wti_player.menu could not be imported: {error}") from error
    return menu, menu


def theme_keys(source: str = PLAYER) -> list[str]:
    themes, _render = factory(source)
    return list(themes.THEMES)


@dataclass(frozen=True)
class ThemedMenu:
    """A rendered theme, turned into the pieces a disc needs."""

    #: The picture the menu video is made of.
    background: Path
    #: The IG stream's segments, ready for ``hdmv.pes_packets``.
    segments: list[bytes]
    #: What each button is called, for a report.
    labels: tuple[str, ...]
    theme_key: str
    width: int = MENU_WIDTH
    height: int = MENU_HEIGHT

    @property
    def bytes_on_disc(self) -> int:
        return sum(len(segment) for segment in self.segments)


def build(
    out_dir: Path,
    *,
    theme_key: str,
    title: str = "",
    poster: Path | None = None,
    still: Path | None = None,
    buttons: tuple[tuple[str, str], ...] = DEFAULT_BUTTONS,
    commands: dict[str, tuple[bytes, ...]] | None = None,
    frame_rate_code: int = hdmv.FRAME_RATE_23_976,
    source: str = PLAYER,
) -> ThemedMenu:
    """Render ``theme_key`` and turn it into an HDMV interactive-graphics stream.

    ``commands`` maps a button key to what pressing it should do; anything not
    named gets nothing, which is a button that lights up and waits. The Play
    button defaults to jumping to title 1, because a menu whose Play button
    does nothing is worse than no menu.
    """
    themes, render = factory(source)
    if theme_key not in themes.THEMES:
        raise KeyError(f"no theme called {theme_key!r}. Have: {', '.join(themes.THEMES)}")

    rendered = render.render_menu(
        [render.Button(key=key, label=label) for key, label in buttons],
        out_dir,
        theme_key=theme_key,
        title=title,
        poster=poster,
        still=still,
    )

    actions = {"play": (hdmv.cmd_jump_title(1),)}
    actions.update(commands or {})

    palette = graphics.MenuPalette()
    segments = _to_segments(rendered, palette, actions, frame_rate_code)
    return ThemedMenu(
        background=rendered.background,
        segments=segments,
        labels=tuple(button.label for button in rendered.buttons),
        theme_key=theme_key,
    )


def _to_segments(
    rendered: Any,
    palette: graphics.MenuPalette,
    actions: dict[str, tuple[bytes, ...]],
    frame_rate_code: int,
) -> list[bytes]:
    """Quantise every button image into one palette, then build the menu.

    One palette is not a simplification, it is the format: an HDMV page has
    exactly one, and a button's normal and selected images have to index into
    the same 255 colours. So every image is measured together before any of
    them is quantised.
    """
    from PIL import Image

    order: list[tuple[int, str, str]] = []
    next_id = 0
    for button in rendered.buttons:
        for state in ("normal", "selected", "activated"):
            source = button.images.get(state)
            if source is None:
                continue
            palette.add(next_id, Image.open(source))
            order.append((next_id, button.key, state))
            next_id += 1
    palette.build()
    objects = palette.objects()

    slot = {(key, state): object_id for object_id, key, state in order}
    buttons: list[hdmv.Button] = []
    count = len(rendered.buttons)
    for index, button in enumerate(rendered.buttons):
        normal = slot.get((button.key, "normal"))
        if normal is None:
            continue
        buttons.append(
            hdmv.Button(
                button_id=index,
                x=button.x,
                y=button.y,
                normal_object=normal,
                selected_object=slot.get((button.key, "selected"), normal),
                activated_object=slot.get((button.key, "activated"), normal),
                # A column wraps top to bottom, which is what every disc does
                # and what somebody holding a remote expects.
                upper=(index - 1) % count,
                lower=(index + 1) % count,
                commands=actions.get(button.key, ()),
            )
        )

    page = hdmv.Page(page_id=0, palette_id=0, buttons=tuple(buttons), default_selected=0)
    menu = hdmv.Menu(
        width=MENU_WIDTH,
        height=MENU_HEIGHT,
        frame_rate_code=frame_rate_code,
        palette=palette.palette(0),
        objects=objects,
        pages=[page],
    )
    return menu.segments()


def describe(menu: ThemedMenu) -> list[str]:
    return [
        f"theme      {menu.theme_key}",
        f"background {menu.background.name} ({menu.width}x{menu.height})",
        f"buttons    {len(menu.labels)}: " + ", ".join(menu.labels),
        f"IG stream  {len(menu.segments)} segments, {menu.bytes_on_disc:,} bytes",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a film-menu theme as an HDMV stream.")
    parser.add_argument("theme", nargs="?", help="which theme")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--title", default="A Film")
    parser.add_argument("--poster", type=Path, default=None)
    parser.add_argument("--still", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=REPO / "_design" / "theme-menus")
    parser.add_argument(
        "--factory",
        action="store_true",
        help="use rialto2's original renderer instead of the redrawn designs",
    )
    args = parser.parse_args(argv)
    source = RIALTO if args.factory else PLAYER

    try:
        keys = theme_keys(source)
    except ThemesUnavailable as error:
        print(error)
        return 2

    if args.list or not args.theme:
        themes, _render = factory(source)
        for key in keys:
            print(f"  {key:<18} {themes.THEMES[key].name}")
        return 0
    if args.theme not in keys:
        print(f"no theme called {args.theme!r}")
        return 2

    built = build(
        args.out / args.theme,
        theme_key=args.theme,
        title=args.title,
        poster=args.poster,
        still=args.still,
        source=source,
    )
    for line in describe(built):
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
