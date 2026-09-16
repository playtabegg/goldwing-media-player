"""The six designs, and the registry the rest of the world sees.

One per kind of film. Adding a seventh is a module and a line here; the point
of the split is that a design can be changed completely without touching the
other five, which was not true when all six came out of one drawing routine.
"""

from __future__ import annotations

from wti_player.menu.designs import (
    animation,
    classic_cinema,
    documentary,
    music_film,
    poster_art,
    quiet_arthouse,
)
from wti_player.menu.designs.base import Composition, Design, Scene, Slot, ThemeEntry

_MODULES = (
    classic_cinema,
    poster_art,
    quiet_arthouse,
    documentary,
    animation,
    music_film,
)

DESIGNS: dict[str, Design] = {module.DESIGN.key: module.DESIGN for module in _MODULES}

#: The same six keys the factory ships, so nothing downstream has to change.
THEMES: dict[str, ThemeEntry] = {
    key: ThemeEntry(
        key=key,
        name=item.name,
        description=item.description,
        references=item.references,
    )
    for key, item in DESIGNS.items()
}

#: What a film gets when intake does not say.
DEFAULT_THEME = "classic_cinema"


def design(key: str) -> Design:
    """One design by key. Falls back rather than failing.

    A disc with the wrong menu is a disappointment; a build that stops
    because somebody typed a retired theme name is a film that does not get
    pressed that day.
    """
    return DESIGNS.get(key, DESIGNS[DEFAULT_THEME])


def theme_keys() -> list[str]:
    return list(DESIGNS)


__all__ = [
    "DEFAULT_THEME",
    "DESIGNS",
    "THEMES",
    "Composition",
    "Design",
    "Scene",
    "Slot",
    "ThemeEntry",
    "design",
    "theme_keys",
]
