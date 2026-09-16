"""Showing a DVD menu: the engine, the surface and the navigator, joined.

:mod:`dvd.menu` reads a menu off a disc. This puts one on screen and takes
presses for it, and it is the only place in the Player where those three
things meet.

The shape of it, and why:

* **The menu's video goes through a buffer we own, not a window.** The
  subpicture and the highlight have to be composited over the picture, and
  nothing can be composited over video the graphics card is painting straight
  to a window. So a menu takes the slow path, deliberately, and a film does
  not — a film keeps its native window and its hardware decoding.
* **Nothing here touches the path films play on.** Starting a menu swaps
  which widget is on screen and which sink the engine is writing to; leaving
  one puts both back. If this whole path has a bad day, titles still play.
* **The engine is held at arm's length.** Everything it is asked for goes
  through :class:`MenuHost`, which is four methods a fake can implement — so
  the whole of this is testable with no libvlc, no disc and no window.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from ..engine.base import MediaTarget, NavAction
from . import menu as menu_reader
from .menu import DVD_HEIGHT, DVD_WIDTH, DiscMenu
from .navigator import Action


class MenuHost(Protocol):
    """What showing a menu needs from the engine.

    Four methods. ``VlcEngine`` has all of them already; a test double needs
    nothing else.
    """

    def open(self, target: MediaTarget) -> None: ...

    def play(self) -> None: ...

    def stop(self) -> None: ...

    def use_memory_output(
        self, width: int, height: int, on_frame: Callable[[], None]
    ) -> memoryview: ...


class MenuSession:
    """One menu, up on screen, taking presses.

    Create it, :meth:`start` it, feed it presses, and read the
    :class:`~wti_player.dvd.navigator.Action` each one produces. The window
    decides what to do with the action; this decides nothing about playback.
    """

    def __init__(
        self,
        engine: MenuHost,
        *,
        width: int = DVD_WIDTH,
        height: int = DVD_HEIGHT,
    ) -> None:
        self.engine = engine
        self.width = width
        self.height = height
        self.menu: DiscMenu | None = None
        self._buffer: memoryview | None = None
        self._on_frame: Callable[[], None] = lambda: None

    # -- coming and going --------------------------------------------------

    def start(
        self,
        root: Path | str,
        *,
        title_set: int = 1,
        kind: str = "",
        on_frame: Callable[[], None] | None = None,
    ) -> DiscMenu | None:
        """Read the disc's menu and start its video. ``None`` if it has none.

        ``on_frame`` is called from libvlc's own thread every time a frame
        lands, so it must do nothing but wake the interface up — a queued
        signal, and no more.
        """
        found = menu_reader.read(root, title_set=title_set, kind=kind)
        if found is None:
            return None
        return self.start_with(found, on_frame=on_frame)

    def start_with(
        self, found: DiscMenu, *, on_frame: Callable[[], None] | None = None
    ) -> DiscMenu:
        """Start a menu somebody else already read (off the interface's thread)."""
        self.menu = found
        self._on_frame = on_frame or (lambda: None)
        self._buffer = self.engine.use_memory_output(
            self.width, self.height, self._frame_landed
        )
        self.engine.open(MediaTarget.dvd_title([found.vob]))
        self.engine.play()
        return found

    def stop(self) -> None:
        """Take the menu down. Whatever plays next gets a clean engine."""
        self.menu = None
        self._buffer = None
        self._on_frame = lambda: None
        self.engine.stop()

    @property
    def active(self) -> bool:
        return self.menu is not None

    @property
    def buffer(self) -> memoryview | None:
        """The frame the surface should paint from."""
        return self._buffer

    # -- being pressed -----------------------------------------------------

    def press(self, action: NavAction) -> Action:
        """A direction or an activation, from the keyboard, a pad or a remote."""
        if self.menu is None:
            return Action(kind="nothing")
        return self.menu.navigator.press(action)

    def point_at(self, x: int, y: int) -> bool:
        """The pointer moved. True when it changed which button is lit."""
        if self.menu is None:
            return False
        return self.menu.navigator.point_at(x, y)

    def click_at(self, x: int, y: int) -> Action:
        if self.menu is None:
            return Action(kind="nothing")
        return self.menu.navigator.click_at(x, y)

    # -- what the surface needs to draw ------------------------------------

    def presentation(self) -> dict:
        """Everything :class:`~wti_player.ui.menu_surface.MenuSurface` needs.

        Kept as a plain dictionary rather than a widget call so that this
        module never imports Qt, which is what keeps it testable.
        """
        if self.menu is None:
            return {}
        highlight = self.menu.navigator.highlight
        colours = (
            highlight.colours_for(self.menu.navigator.selected_button)
            if highlight is not None
            else None
        )
        return {
            "navigator": self.menu.navigator,
            "subpicture": self.menu.subpicture,
            "chain_palette": list(self.menu.palette),
            "highlight_palette": colours.selected_palette if colours else None,
            "highlight_alpha": colours.selected_alpha if colours else None,
        }

    def _frame_landed(self) -> None:
        self._on_frame()


__all__ = ["MenuHost", "MenuSession"]
