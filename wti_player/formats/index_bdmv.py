"""Read ``BDMV/index.bdmv`` and ``BDMV/MovieObject.bdmv``.

Between them these two files are the disc's table of contents: what plays
first, whether there is a Top Menu, how many titles there are, and — the part
the Player cares about most — whether any of it is **BD-J**.

BD-J titles need a Java virtual machine the Player does not ship. Knowing that
from the index, before anything plays, is the difference between "this disc's
menus need Java, which GoldWing does not run — here are its titles"
and a black screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .bitreader import BitReader, TruncatedError

INDEX_MAGIC = b"INDX"
MOBJ_MAGIC = b"MOBJ"
SUPPORTED_VERSIONS = ("0100", "0200", "0300")

OBJECT_TYPE_HDMV = 1
OBJECT_TYPE_BDJ = 2

#: Playback types an index entry can declare.
PLAYBACK_TYPES = {0: "movie", 1: "interactive", 2: "movie", 3: "interactive"}


class IndexError_(ValueError):
    """This file is not an index we can read."""


@dataclass(frozen=True)
class IndexEntry:
    """One slot of the index: First Play, Top Menu, or a title."""

    object_type: int
    playback_type: int
    #: HDMV: the MovieObject number. BD-J: 0, and ``bdjo_name`` is set instead.
    id_ref: int = 0
    bdjo_name: str = ""

    @property
    def is_bdj(self) -> bool:
        return self.object_type == OBJECT_TYPE_BDJ

    @property
    def is_present(self) -> bool:
        """False for an empty slot — a disc with no Top Menu, say."""
        return self.object_type in (OBJECT_TYPE_HDMV, OBJECT_TYPE_BDJ)


@dataclass(frozen=True)
class Index:
    """A parsed ``index.bdmv``."""

    version: str
    first_play: IndexEntry
    top_menu: IndexEntry
    titles: tuple[IndexEntry, ...] = ()

    @property
    def has_top_menu(self) -> bool:
        return self.top_menu.is_present

    @property
    def uses_bdj(self) -> bool:
        """True if any slot is BD-J. Those parts need a JVM we do not ship."""
        return any(
            entry.is_bdj for entry in (self.first_play, self.top_menu, *self.titles)
        )

    @property
    def title_count(self) -> int:
        return len(self.titles)


@dataclass(frozen=True)
class MovieObject:
    """One HDMV movie object: a short program of navigation commands."""

    resume_intention: bool
    menu_call_mask: bool
    title_search_mask: bool
    commands: tuple[bytes, ...] = ()

    @property
    def command_count(self) -> int:
        return len(self.commands)


def _parse_entry(reader: BitReader) -> IndexEntry:
    object_type = reader.bits(2)
    reader.bits(30)
    if object_type == OBJECT_TYPE_HDMV:
        playback_type = reader.bits(2)
        reader.bits(14)
        id_ref = reader.u16()
        reader.u32()
        return IndexEntry(object_type=object_type, playback_type=playback_type, id_ref=id_ref)
    if object_type == OBJECT_TYPE_BDJ:
        playback_type = reader.bits(2)
        reader.bits(14)
        name = reader.ascii(5)
        reader.u8()  # reserved — a BD-J slot is 12 bytes, same as an HDMV one
        return IndexEntry(object_type=object_type, playback_type=playback_type, bdjo_name=name)
    reader.u32()
    reader.u32()
    return IndexEntry(object_type=object_type, playback_type=0)


def parse_index(data: bytes) -> Index:
    """Parse ``index.bdmv`` bytes."""
    try:
        reader = BitReader(data)
        magic = reader.read(4)
        if magic != INDEX_MAGIC:
            raise IndexError_(f"not an index: magic {magic!r}")
        version = reader.ascii(4)
        if version not in SUPPORTED_VERSIONS:
            raise IndexError_(f"unsupported index version {version!r}")
        indexes_start = reader.u32()

        reader.seek(indexes_start)
        reader.u32()  # Indexes() length
        first_play = _parse_entry(reader)
        top_menu = _parse_entry(reader)
        title_count = reader.u16()
        titles = tuple(_parse_entry(reader) for _ in range(title_count))
    except TruncatedError as exc:
        raise IndexError_(f"index is truncated: {exc}") from exc

    return Index(version=version, first_play=first_play, top_menu=top_menu, titles=titles)


def parse_movie_objects(data: bytes) -> tuple[MovieObject, ...]:
    """Parse ``MovieObject.bdmv`` bytes into its movie objects.

    Commands are kept as raw 12-byte words. The Player does not run the HDMV
    virtual machine — libbluray does — so it only needs to count them and, for
    menu preview mode, show them.
    """
    try:
        reader = BitReader(data)
        magic = reader.read(4)
        if magic != MOBJ_MAGIC:
            raise IndexError_(f"not a movie object file: magic {magic!r}")
        version = reader.ascii(4)
        if version not in SUPPORTED_VERSIONS:
            raise IndexError_(f"unsupported movie object version {version!r}")

        reader.seek(40)
        reader.u32()  # MovieObjects() length
        reader.u32()  # reserved
        count = reader.u16()
        objects: list[MovieObject] = []
        for _ in range(count):
            resume = bool(reader.bits(1))
            menu_mask = bool(reader.bits(1))
            search_mask = bool(reader.bits(1))
            reader.bits(13)
            command_count = reader.u16()
            commands = tuple(reader.read(12) for _ in range(command_count))
            objects.append(
                MovieObject(
                    resume_intention=resume,
                    menu_call_mask=menu_mask,
                    title_search_mask=search_mask,
                    commands=commands,
                )
            )
    except TruncatedError as exc:
        raise IndexError_(f"movie objects are truncated: {exc}") from exc
    return tuple(objects)


def read_index(bdmv_dir: Path) -> Index:
    """Read ``index.bdmv`` from a ``BDMV`` directory, falling back to BACKUP."""
    for candidate in (bdmv_dir / "index.bdmv", bdmv_dir / "BACKUP" / "index.bdmv"):
        if candidate.is_file():
            try:
                return parse_index(candidate.read_bytes())
            except (IndexError_, OSError):
                continue
    raise IndexError_(f"no readable index.bdmv under {bdmv_dir}")


def read_movie_objects(bdmv_dir: Path) -> tuple[MovieObject, ...]:
    for candidate in (bdmv_dir / "MovieObject.bdmv", bdmv_dir / "BACKUP" / "MovieObject.bdmv"):
        if candidate.is_file():
            try:
                return parse_movie_objects(candidate.read_bytes())
            except (IndexError_, OSError):
                continue
    return ()
