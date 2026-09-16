"""Film menu designs, and the renderer that draws them.

Six designs, one per kind of film, each drawn by its own module rather than
by one routine with six palettes. That is the whole change: what shipped
before was a title at the top and a list of words underneath, six times, in
six colour schemes.

A drop-in for ``rialto2/rialto_core/film_menu_render.py``. Same names, same
call signature, same output filenames, so a caller changes one import:

    from wti_player.menu import Button, render_menu

    render_menu(
        [Button("play", "Play"), Button("chapters", "Chapters")],
        Path("out"),
        theme_key="documentary",
        title="Nanook of the North",
        still=Path("frame.png"),
    )

This module also stands in for ``film_themes``: ``THEMES``, ``theme_keys``
and ``DEFAULT_THEME`` are here under the same names.

Pillow is imported inside the functions that need it, so importing
``wti_player`` in the Player itself does not drag an imaging library into a
program that only plays discs.
"""

from __future__ import annotations

from wti_player.menu.contrast import contrast_ratio, measure, relative_luminance
from wti_player.menu.designs import DEFAULT_THEME, DESIGNS, THEMES, design, theme_keys
from wti_player.menu.render import SEED, render_menu
from wti_player.menu.types import (
    BUTTON_STATES,
    MENU_HEIGHT,
    MENU_WIDTH,
    MIN_CONTRAST,
    MIN_LARGE_CONTRAST,
    TITLE_SAFE_MARGIN,
    Button,
    ButtonState,
    ContrastFailure,
    RenderedButton,
    RenderedMenu,
    RenderUnavailable,
    safe_box,
)

#: The factory's registry called this ``theme``. Same shape, same fallback.
theme = design

__all__ = [
    "BUTTON_STATES",
    "DEFAULT_THEME",
    "DESIGNS",
    "MENU_HEIGHT",
    "MENU_WIDTH",
    "MIN_CONTRAST",
    "MIN_LARGE_CONTRAST",
    "SEED",
    "THEMES",
    "TITLE_SAFE_MARGIN",
    "Button",
    "ButtonState",
    "ContrastFailure",
    "RenderUnavailable",
    "RenderedButton",
    "RenderedMenu",
    "contrast_ratio",
    "design",
    "measure",
    "relative_luminance",
    "render_menu",
    "safe_box",
    "theme",
    "theme_keys",
]
