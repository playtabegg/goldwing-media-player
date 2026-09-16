"""The shelf: local copies of discs, beside the drives (W2, 30 Aug 2026).

The Player has a film shelf, an album shelf and
a game shelf, and plays a film or an album from the disc or from a local
copy without the disc in the drive, and opens a game's menu the same way.

A local copy is a folder laid out exactly like the disc: the same
``.wti_meta.json``, the same art beside it, the same ``.wti_edition.json``
when the copy came from a signed disc, and for a game the same ``menu``
folder the disc carries. The locker download makes such folders; so does
copying a disc by hand. The shelf is the list of those folders a person
has added, read fresh each time the empty screen shows, so a folder that
has gone is simply not there.

Nothing here is looked up anywhere. The document on the copy is the whole
truth the shelf knows, which is the same truth the disc carries.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .optical import edition as disc_edition
from .optical import meta as disc_meta

#: What the document's ``kind`` means on the shelf. Anything else with a
#: document is still shown, as a disc; the Player opens it the way it opens
#: any folder.
KIND_LABEL = {"movie": "Film", "music": "Album", "game": "Game"}
SHELF_KINDS = ("film", "album", "game", "disc")
KIND_ORDER = {kind: index for index, kind in enumerate(SHELF_KINDS)}

#: The disc menu a Rialto disc carries, under the disc root, the same place
#: ``start_menu.bat`` looks first (rialto2 ``disc_root.py``). It reads its
#: ``menu_config.json`` beside itself, so it is started from its own folder.
MENU_DIR = "menu"
MENU_EXE = "menu.exe"

MAX_SHELF = 200

#: What a verified record earns on a row. Said only when the signature
#: verifies against a key in the Player's trusted list; never a gate.
SIGNED_BY_US = "signed by We The Indies"


@dataclass(frozen=True)
class ShelfEntry:
    """One copy on the shelf, as its own document describes it."""

    root: Path
    kind: str
    title: str
    author: str = ""
    version: str = ""
    cover: Path | None = None
    face: Path | None = None
    edition_line: str = ""
    signed: bool = False
    #: L4: the record verifies against the factory's key. Never a gate.
    signed_by_us: bool = False

    @property
    def kind_label(self) -> str:
        return {"film": "Film", "album": "Album", "game": "Game"}.get(self.kind, "Disc")

    @property
    def has_menu(self) -> bool:
        return self.kind == "game" and menu_executable(self.root) is not None

    def describe(self) -> str:
        """One line for a row: the title, then what it is and whose."""
        parts = [self.kind_label]
        if self.author:
            parts.append(self.author)
        if self.edition_line:
            parts.append(self.edition_line)
        if self.signed_by_us:
            parts.append(SIGNED_BY_US)
        return " · ".join(parts)


def shelf_kind(document_kind: str) -> str:
    return {"movie": "film", "music": "album", "game": "game"}.get(document_kind, "disc")


def read_entry(root: Path | str) -> ShelfEntry | None:
    """What this folder is, from its own document; ``None`` if it has none.

    Never raises: a folder that has gone, or one somebody pointed at by
    mistake, is not a copy and the shelf says so by leaving it out.
    """
    try:
        folder = Path(root)
        if not folder.is_dir():
            return None
    except OSError:
        return None
    document = disc_meta.read(folder)
    if document is None or not document.title:
        return None
    record = disc_edition.read(folder)
    edition_line = ""
    signed = False
    if record is not None and record.number:
        edition_line = record.line
        signed = bool(record.signed)
    return ShelfEntry(
        root=folder,
        kind=shelf_kind(document.kind),
        title=document.title,
        author=document.author,
        version=document.version,
        cover=document.art.cover,
        face=document.art.face,
        edition_line=edition_line,
        signed=signed,
        signed_by_us=bool(record is not None and record.signed_by_us),
    )


def scan(roots: Sequence[Path | str]) -> list[ShelfEntry]:
    """Every copy that is still there, films first, then albums, then games."""
    entries: list[ShelfEntry] = []
    seen: set[str] = set()
    for root in roots:
        key = os.path.normcase(str(root)).rstrip("\\/")
        if key in seen:
            continue
        seen.add(key)
        entry = read_entry(root)
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda e: (KIND_ORDER.get(e.kind, len(SHELF_KINDS)), e.title.lower()))
    return entries


def add_root(roots: Sequence[Path], root: Path, limit: int = MAX_SHELF) -> list[Path]:
    """The list with ``root`` in it once, newest last, at most ``limit`` long."""
    key = os.path.normcase(str(root)).rstrip("\\/")
    kept = [Path(p) for p in roots if os.path.normcase(str(p)).rstrip("\\/") != key]
    return [*kept, Path(root)][-limit:]


def remove_root(roots: Sequence[Path], root: Path) -> list[Path]:
    key = os.path.normcase(str(root)).rstrip("\\/")
    return [Path(p) for p in roots if os.path.normcase(str(p)).rstrip("\\/") != key]


class MenuMissing(Exception):
    """The copy has no disc menu to open."""


def menu_executable(root: Path | str) -> Path | None:
    """``<root>/menu/menu.exe`` when it is a real file inside the root."""
    try:
        base = Path(root).resolve()
        candidate = (base / MENU_DIR / MENU_EXE).resolve()
        if candidate.is_file() and base in candidate.parents:
            return candidate
    except OSError:
        return None
    return None


def open_game_menu(
    root: Path | str,
    popen: Callable[..., object] = subprocess.Popen,
) -> Path:
    """Start the copy's own disc menu, by path, from its own folder.

    Nothing else is launched: not the installer, not the game. The menu is
    the disc's, it reads its own ``menu_config.json`` beside itself, and
    what happens after is the player's business, exactly as if the disc
    were in the drive and Windows had opened it. Returns the path started.
    """
    exe = menu_executable(root)
    if exe is None:
        raise MenuMissing(str(root))
    popen([str(exe)], cwd=str(exe.parent))
    return exe
