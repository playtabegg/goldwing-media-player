"""What is inside a disc image, without mounting it.

``identify`` used to treat every ``.iso`` as a Blu-ray and hand it to
libbluray. Rialto 1.5 game discs (Rutted, The Wind's Path) then opened as
Blu-rays, failed to find ``BDMV``, and GoldWing told the person their DVD
was a locked commercial Blu-ray. The image's own bytes say what it is.

This reads a little of the file: the ISO 9660 volume descriptor when one
is there, and a short scan for the folder names a disc uses. It never
mounts the image and it never reads the whole file.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

SECTOR = 2048
#: Enough for the primary volume descriptor and the first directory records
#: on a typical ISO 9660 image. UDF names are also caught as raw strings.
SCAN_BYTES = 4 * 1024 * 1024
#: A Rialto 1.5 menu can sit past the first volume descriptor. We look a
#: little further for our own names, then stop. Never the whole image.
OURS_SCAN_BYTES = 32 * 1024 * 1024

IMAGE_SUFFIXES = (".iso", ".img", ".bin")


class ImageKind(Enum):
    BLU_RAY = "blu-ray"
    DVD_VIDEO = "dvd-video"
    GAME = "game-disc"
    DATA = "data"
    UNREADABLE = "unreadable"


def is_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES


@dataclass(frozen=True)
class ImagePeek:
    kind: ImageKind
    label: str = ""
    ours: bool = False


def peek_image(path: Path | str) -> ImagePeek:
    """What the image is, its volume label, and whether we made it.

    Kind is never Blu-ray unless the image actually carries a BDMV. An
    image we cannot read is data, not a guess. ``ours`` is We The Indies:
    our document, our edition, or the Rialto 1.5 menu fileset.
    """
    root = Path(path)
    try:
        size = root.stat().st_size
    except OSError:
        return ImagePeek(ImageKind.UNREADABLE)
    if size < SECTOR:
        return ImagePeek(ImageKind.DATA)

    try:
        with root.open("rb") as handle:
            blob = handle.read(min(SCAN_BYTES, size))
            if size > SCAN_BYTES and not _ours_in(blob):
                extra = handle.read(min(OURS_SCAN_BYTES - SCAN_BYTES, size - SCAN_BYTES))
                blob = blob + extra
    except OSError:
        return ImagePeek(ImageKind.UNREADABLE)

    names = _names_from_iso9660(blob)
    names.update(_marker_names(blob))
    kind = _kind_from_names(names)
    return ImagePeek(kind=kind, label=_iso_volume_label(blob), ours=_ours_in(blob))


def _ours_in(blob: bytes) -> bool:
    """The factory's own fingerprints, not a guess from 'this is a game'."""
    needles = (
        b".wti_meta.json",
        b".wti_edition.json",
        b"We The Indies",
        b"We the Indies",
        b"WE THE INDIES",
        b"menu.exe",
        b"MENU.EXE",
        b"menu_config.json",
    )
    return any(needle in blob or needle.decode("ascii").encode("utf-16le") in blob for needle in needles)


def _kind_from_names(names: set[str]) -> ImageKind:
    upper = {name.upper().replace("\\", "/") for name in names}
    if any(
        name == "BDMV"
        or name.startswith("BDMV/")
        or name.endswith("/BDMV")
        or name.endswith("INDEX.BDMV")
        for name in upper
    ):
        return ImageKind.BLU_RAY
    if any("VIDEO_TS" in name or name.endswith(".IFO") for name in upper):
        return ImageKind.DVD_VIDEO
    if any(name.endswith("AUTORUN.INF") or name == "AUTORUN.INF" for name in upper):
        return ImageKind.GAME
    if any(name.endswith("MENU.EXE") or name.endswith("/MENU.EXE") for name in upper):
        return ImageKind.GAME
    return ImageKind.DATA


def _marker_names(blob: bytes) -> set[str]:
    """Folder names a disc uses, as they sit in the image as text."""
    found: set[str] = set()
    markers = (
        "VIDEO_TS",
        "AUDIO_TS",
        "BDMV",
        "INDEX.BDMV",
        "AUTORUN.INF",
        "MENU.EXE",
        "AACS",
    )
    for name in markers:
        raw = name.encode("ascii")
        wide = name.encode("utf-16le")
        if raw in blob or wide in blob:
            found.add(name)
    return found


def _iso_volume_label(blob: bytes) -> str:
    pvd = _pvd(blob)
    if pvd is None:
        return ""
    return pvd[40:72].decode("ascii", "replace").strip()


def _pvd(blob: bytes) -> bytes | None:
    start = 16 * SECTOR
    if len(blob) < start + SECTOR:
        return None
    sector = blob[start : start + SECTOR]
    if sector[1:6] != b"CD001":
        return None
    return sector


def _names_from_iso9660(blob: bytes) -> set[str]:
    """The first level of an ISO 9660 directory, when the image has one."""
    pvd = _pvd(blob)
    if pvd is None:
        return set()
    record = pvd[156:190]
    if not record or record[0] < 34:
        return set()
    extent = int.from_bytes(record[2:6], "little")
    length = int.from_bytes(record[10:14], "little")
    start = extent * SECTOR
    end = start + min(length, 64 * SECTOR)
    if start < 0 or start >= len(blob):
        return set()
    table = blob[start : min(end, len(blob))]
    return _directory_names(table)


def _directory_names(table: bytes) -> set[str]:
    names: set[str] = set()
    offset = 0
    while offset < len(table):
        size = table[offset]
        if size == 0:
            offset = (offset // SECTOR + 1) * SECTOR
            continue
        if offset + size > len(table) or size < 34:
            break
        name_len = table[offset + 32]
        raw = table[offset + 33 : offset + 33 + name_len]
        offset += size
        if name_len <= 1:
            continue
        # ISO 9660 file ids look like NAME.EXT;2 — drop the version.
        text = raw.split(b";", 1)[0].decode("ascii", "replace").strip()
        if text:
            names.add(text)
    return names
