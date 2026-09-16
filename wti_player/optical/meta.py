"""``.wti_meta.json`` — what a We The Indies disc says about itself.

The disc's structure says what it *is*: a ``BDMV`` folder is a Blu-ray, a
``VIDEO_TS`` folder is a DVD, ``.cda`` tracks are an audio CD. What structure
cannot say is *whose* it is. A playlist knows it has fifteen chapters and
where each one starts; it does not know that one of them is called The Long
Way Round.

The factory writes those names down, once, at build time. This reads them.

    Authority   rialto2/rialto_core/disc_meta.schema.json
    Writer      rialto2/rialto_core/disc_meta.py
    Handoff     _Docs/WTI-DISC-META_2026-08-24.md

Version 1 is frozen. A new *optional* field with a default may be added at
any time, so this reads by name and ignores what it does not recognise —
except the ``schema`` number itself, which it reports rather than guesses at.

**A document that will not parse reads as absent, never as an error.** A
disc with a bad sector should degrade to "we know less about this one", not
to an exception in front of somebody watching a film.

Disc art
--------

A disc carries its own artwork as one or two small JPEGs beside the document:
``cover.jpg`` (the front of the case) and ``disc.jpg`` (the printed label).
Both optional, either or neither. The document may name them explicitly in an
``art`` block; when it does not, those two filenames are looked for, so a
disc built before the field existed still shows its art if somebody dropped
the file in beside it.

Nothing here decodes an image. That is the interface's job, and this module
has no business importing Qt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: The filename, the same for every kind of disc that has one.
META_NAME = ".wti_meta.json"

#: Where to look, in order, relative to the disc root. This list mirrors
#: ``rialto_core.disc_meta.META_SEARCH_PATHS`` exactly. A disc has at most one.
#:
#: A game disc keeps its document in ``menu/`` because the root of a WTI game
#: disc is Rialto 1.5's exact fileset and a test over there guards it name for
#: name. A movie disc keeps it at the root, because a Blu-ray player reads
#: ``BDMV/`` and ``CERTIFICATE/`` and ignores everything else.
SEARCH_PATHS: tuple[str, ...] = (
    ".wti_meta.json",
    "menu/.wti_meta.json",
)

#: The version this reader was written against.
KNOWN_SCHEMA = 1

#: A document is names and numbers. Anything larger than this is not one, and
#: reading it off a scratched disc is a wait nobody asked for.
MAX_DOCUMENT_BYTES = 512 * 1024

#: Cover art is meant to be a lightweight JPEG. Anything past this is either a
#: master somebody dropped in by mistake or a disc that is not what it claims,
#: and either way it is not going on screen.
MAX_ART_BYTES = 8 * 1024 * 1024

#: Looked for beside the document when it does not name its own art. Order
#: matters: the first that exists wins.
COVER_NAMES: tuple[str, ...] = ("cover.jpg", "cover.jpeg", "cover.png", "folder.jpg")
FACE_NAMES: tuple[str, ...] = ("disc.jpg", "disc.jpeg", "disc.png", "label.jpg")


@dataclass(frozen=True)
class Chapter:
    """A chapter's name and where it starts, as its author typed them."""

    title: str
    start: str

    @property
    def start_ms(self) -> int:
        """``H:MM:SS`` or ``MM:SS`` as milliseconds. 0 if it will not parse."""
        parts = self.start.split(":")
        try:
            numbers = [int(part) for part in parts]
        except ValueError:
            return 0
        if len(numbers) == 2:
            numbers = [0, *numbers]
        if len(numbers) != 3:
            return 0
        hours, minutes, seconds = numbers
        return ((hours * 60 + minutes) * 60 + seconds) * 1000


@dataclass(frozen=True)
class Extra:
    title: str
    description: str = ""


@dataclass(frozen=True)
class MovieMeta:
    runtime_minutes: int = 0
    aspect_ratio: str = ""
    menu_theme: str = ""
    rating_text: str = ""
    copyright_text: str = ""
    chapters: tuple[Chapter, ...] = ()
    audio_tracks: tuple[str, ...] = ()
    subtitle_tracks: tuple[str, ...] = ()
    extras: tuple[Extra, ...] = ()


@dataclass(frozen=True)
class GameMeta:
    launch_options: tuple[str, ...] = ()
    has_mod_tool: bool = False
    has_bonus: bool = False
    mac_build: bool = False
    linux_build: bool = False
    online_updates: bool = False
    menu_language: str = ""


@dataclass(frozen=True)
class DiscArt:
    """Where a disc keeps its own picture of itself."""

    #: The front of the case. Portrait, roughly 2:3.
    cover: Path | None = None
    #: The printed label. Square, drawn as a circle.
    face: Path | None = None

    @property
    def any(self) -> bool:
        return self.cover is not None or self.face is not None


@dataclass(frozen=True)
class DiscMeta:
    """One disc's document, as far as this reader understands it."""

    schema: int = KNOWN_SCHEMA
    kind: str = ""
    title: str = ""
    author: str = ""
    publisher_text: str = ""
    identifier: str = ""
    version: str = ""
    disc_label: str = ""
    made_by: str = ""
    movie: MovieMeta | None = None
    game: GameMeta | None = None
    art: DiscArt = field(default_factory=DiscArt)
    #: Where the document was found, for the inspector to show.
    source: Path | None = None

    @property
    def ours(self) -> bool:
        """Did We The Indies make this disc?"""
        return self.made_by == "We the Indies"

    @property
    def newer_than_us(self) -> bool:
        """A document from a factory later than this Player.

        Worth saying out loud rather than guessing at: the schema promises
        that version 1 fields keep their meaning, so everything read below is
        still right, but there may be more on the disc than is being shown.
        """
        return self.schema > KNOWN_SCHEMA

    @property
    def year(self) -> str:
        """A year out of the copyright line, when there is one in it.

        The first year written, with its punctuation taken off: a line such as
        "Nosferatu (1922) is in the public domain ... Murnau died 1931" is about
        1922, and reading "(1922)" as not-a-year gave the director's death.
        """
        for text in (self.publisher_text, getattr(self.movie, "copyright_text", "")):
            for token in (text or "").replace(",", " ").split():
                token = token.strip("()[].;:'\"©")
                if len(token) == 4 and token.isdigit() and token.startswith(("18", "19", "20")):
                    return token
        return ""

    def chapter_names(self) -> tuple[str, ...]:
        if self.movie is None:
            return ()
        return tuple(chapter.title for chapter in self.movie.chapters)


def find_document(root: Path) -> Path | None:
    """The disc's document, or ``None``. Never raises."""
    for relative in SEARCH_PATHS:
        candidate = root / relative
        try:
            if candidate.is_file() and candidate.stat().st_size <= MAX_DOCUMENT_BYTES:
                return candidate
        except OSError:
            continue
    return None


def read(root: Path | str) -> DiscMeta | None:
    """Read the disc at ``root``. ``None`` when it has no document.

    Every failure below — no file, unreadable sector, malformed JSON, a
    document that is a list rather than an object — reads as "this disc does
    not have one", because from where a person is sitting those are the same
    thing.
    """
    path = find_document(Path(root))
    if path is None:
        return None
    try:
        # utf-8-sig, not utf-8: Notepad, PowerShell's Out-File and .NET all
        # write a byte-order mark by default, and json.loads rejects one. A
        # disc whose document was edited on Windows lost its name, its
        # chapters and its artwork over three invisible bytes.
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        # Deliberately everything. This module's promise is that a document
        # which will not parse reads as absent, and a RecursionError from a
        # deeply nested file is a RuntimeError, which the narrow tuple here
        # let through — turning a perfectly good disc into "This disc could
        # not be read" and blaming the disc for a metadata file.
        return None
    if not isinstance(raw, dict):
        return None
    return _from_document(raw, path)


def _from_document(raw: dict[str, Any], path: Path) -> DiscMeta:
    kind = _text(raw.get("kind"))
    return DiscMeta(
        schema=_whole(raw.get("schema"), KNOWN_SCHEMA),
        kind=kind,
        title=_text(raw.get("title")),
        author=_text(raw.get("author")),
        publisher_text=_text(raw.get("publisher_text")),
        identifier=_text(raw.get("id")),
        version=_text(raw.get("version")),
        disc_label=_text(raw.get("disc_label")),
        made_by=_text(raw.get("made_by")),
        movie=_movie(raw.get("movie")) if isinstance(raw.get("movie"), dict) else None,
        game=_game(raw.get("game")) if isinstance(raw.get("game"), dict) else None,
        art=find_art(path.parent, raw.get("art")),
        source=path,
    )


def find_art(folder: Path, named: Any = None) -> DiscArt:
    """The disc's cover and label, beside its document.

    ``named`` is the document's own ``art`` block when it has one — an
    optional field, so it usually will not. What it names wins; the
    conventional filenames are the fallback.
    """
    cover = face = None
    if isinstance(named, dict):
        cover = _art_file(folder, _text(named.get("cover")))
        face = _art_file(folder, _text(named.get("disc")) or _text(named.get("face")))
    if cover is None:
        cover = _first_art(folder, COVER_NAMES)
    if face is None:
        face = _first_art(folder, FACE_NAMES)
    return DiscArt(cover=cover, face=face)


def _first_art(folder: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        found = _art_file(folder, name)
        if found is not None:
            return found
    return None


def _art_file(folder: Path, name: str) -> Path | None:
    """One art file, if it is there and is a plausible size.

    ``name`` comes off a disc, so it is treated as hostile: a document that
    names ``../../../Windows/System32/x.jpg`` gets nothing. Art lives beside
    the document or it does not exist.
    """
    if not name or "\\" in name or "/" in name or name.startswith("."):
        return None
    if Path(name).name != name:
        return None
    candidate = folder / name
    try:
        if not candidate.is_file():
            return None
        if candidate.stat().st_size > MAX_ART_BYTES:
            return None
    except OSError:
        return None
    return candidate


# -- the small, dull business of not trusting a file off a disc -------------


#: The longest any single string off a disc may be. A field can be the whole
#: document, and 400,000 characters of title froze the window for five
#: seconds laying it out. Longer than any real name by two orders.
MAX_TEXT = 400


def _text(value: Any) -> str:
    """One string from the disc's document, made safe to put on screen.

    Three things happen here, and all three are the trust boundary:

    Length, because word-wrapped layout is superlinear and one field can be
    the whole document. Control characters, because a newline paints extra
    lines of the disc's choosing into the Player's own headline and a
    right-to-left override reverses text after it. And that is all — the
    labels themselves are set to plain text, which is what stops a title of
    ``<img src="file:///...">`` from being fetched and drawn.
    """
    if not isinstance(value, str):
        return ""
    cleaned = "".join(
        character
        for character in value[:MAX_TEXT]
        if character.isprintable() or character == " "
    )
    return cleaned.strip()


def _whole(value: Any, fallback: int = 0) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return fallback


def _flag(value: Any) -> bool:
    return value is True


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(_text(item) for item in value if _text(item))


def _labels(value: Any) -> tuple[str, ...]:
    """An audio or subtitle track list, as the names a person would read.

    The schema carries a language code AND a label, and both matter: the
    label is what an author wrote, the code is which language it is. Keeping
    only one of them turns a disc with English and Japanese stereo tracks
    into two tracks both called "Stereo".
    """
    if not isinstance(value, list):
        return ()
    out = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = _text(item.get("label"))
        language = _text(item.get("language")).upper()
        if label and language:
            out.append(f"{label} ({language})")
        elif label or language:
            out.append(label or language)
    return tuple(out)


def _movie(raw: dict[str, Any]) -> MovieMeta:
    chapters = []
    if isinstance(raw.get("chapters"), list):
        for item in raw["chapters"]:
            if isinstance(item, dict) and _text(item.get("title")):
                chapters.append(Chapter(_text(item["title"]), _text(item.get("start"))))
    extras = []
    if isinstance(raw.get("extras"), list):
        for item in raw["extras"]:
            if isinstance(item, dict) and _text(item.get("title")):
                extras.append(Extra(_text(item["title"]), _text(item.get("description"))))
    return MovieMeta(
        runtime_minutes=_whole(raw.get("runtime_minutes")),
        aspect_ratio=_text(raw.get("aspect_ratio")),
        menu_theme=_text(raw.get("menu_theme")),
        rating_text=_text(raw.get("rating_text")),
        copyright_text=_text(raw.get("copyright_text")),
        chapters=tuple(chapters),
        audio_tracks=_labels(raw.get("audio_tracks")),
        subtitle_tracks=_labels(raw.get("subtitle_tracks")),
        extras=tuple(extras),
    )


def _game(raw: dict[str, Any]) -> GameMeta:
    return GameMeta(
        launch_options=_strings(raw.get("launch_options")),
        has_mod_tool=_flag(raw.get("has_mod_tool")),
        has_bonus=_flag(raw.get("has_bonus")),
        mac_build=_flag(raw.get("mac_build")),
        linux_build=_flag(raw.get("linux_build")),
        online_updates=_flag(raw.get("online_updates")),
        menu_language=_text(raw.get("menu_language")),
    )


__all__ = [
    "COVER_NAMES",
    "FACE_NAMES",
    "KNOWN_SCHEMA",
    "MAX_ART_BYTES",
    "META_NAME",
    "SEARCH_PATHS",
    "Chapter",
    "DiscArt",
    "DiscMeta",
    "Extra",
    "GameMeta",
    "MovieMeta",
    "find_art",
    "find_document",
    "read",
]
