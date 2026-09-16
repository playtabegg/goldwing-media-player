"""What the Player remembers between runs, and nothing else.

Window size and place, the volume, the last few folders and images
opened by hand, and the folders on the shelf (W2). All of it local (QSettings under the user's profile), none
of it identifying, none of it ever sent. Drive letters are not remembered:
a disc in a drive is found by looking, not by a list.

``MemoryPreferences`` is the same contract without a disk, for tests and
for a run that must leave no trace.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

MAX_RECENT = 8
#: W2 (30 Aug 2026): the folders on the shelf, local copies of discs. Roots
#: only; what each one is comes from its own document, read every time.
MAX_SHELF = 200
IMAGE_SUFFIXES = (".iso", ".img", ".bin")


class Preferences(Protocol):
    def geometry(self) -> bytes | None: ...
    def set_geometry(self, blob: bytes) -> None: ...
    def volume(self) -> int | None: ...
    def set_volume(self, percent: int) -> None: ...
    def recent(self) -> list[Path]: ...
    def set_recent(self, paths: list[Path]) -> None: ...
    def shelf(self) -> list[Path]: ...
    def set_shelf(self, roots: list[Path]) -> None: ...
    def sync(self) -> None: ...


def _same_root(a: str, b: str) -> bool:
    return a.replace("/", "\\").rstrip("\\").lower() == b.replace("/", "\\").rstrip("\\").lower()


def is_rememberable(path: Path, drive_roots: set[str] | frozenset[str] = frozenset()) -> bool:
    """A folder or a disc image somebody chose: never a drive root, and
    never anything on an optical drive, whose disc can leave."""
    try:
        resolved = Path(path)
    except (TypeError, ValueError):
        return False
    text = str(resolved)
    if resolved.anchor and _same_root(text, resolved.anchor):
        return False
    if resolved.anchor and any(_same_root(resolved.anchor, root) for root in drive_roots):
        return False
    if resolved.is_dir():
        return True
    return resolved.suffix.lower() in IMAGE_SUFFIXES


def remember(
    recent: list[Path],
    path: Path,
    limit: int = MAX_RECENT,
    drive_roots: set[str] | frozenset[str] = frozenset(),
) -> list[Path]:
    """The list with ``path`` at the front, once, at most ``limit`` long."""
    if not is_rememberable(path, drive_roots):
        return list(recent)
    key = str(path)
    kept = [p for p in recent if str(p) != key]
    return [Path(key), *kept][:limit]


def clamp_volume(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(str(value).strip())
    except ValueError:
        return None
    return max(0, min(100, number))


class MemoryPreferences:
    """The contract, in a dict."""

    def __init__(self) -> None:
        self._geometry: bytes | None = None
        self._volume: int | None = None
        self._recent: list[Path] = []
        # W2: the folders on the shelf, local copies of discs.
        self._shelf: list[Path] = []
        self.synced = 0

    def geometry(self) -> bytes | None:
        return self._geometry

    def set_geometry(self, blob: bytes) -> None:
        self._geometry = bytes(blob)

    def volume(self) -> int | None:
        return self._volume

    def set_volume(self, percent: int) -> None:
        self._volume = clamp_volume(percent)

    def recent(self) -> list[Path]:
        return list(self._recent)

    def set_recent(self, paths: list[Path]) -> None:
        self._recent = [Path(p) for p in paths][:MAX_RECENT]

    def shelf(self) -> list[Path]:
        return list(self._shelf)

    def set_shelf(self, roots: list[Path]) -> None:
        self._shelf = [Path(p) for p in roots][:MAX_SHELF]

    def sync(self) -> None:
        self.synced += 1


class QtPreferences:
    """QSettings, under HKCU on Windows. Keys are few and named."""

    ORGANISATION = "We The Indies"
    APPLICATION = "Player"

    def __init__(self) -> None:
        from PyQt6.QtCore import QSettings

        self._settings = QSettings(self.ORGANISATION, self.APPLICATION)

    def geometry(self) -> bytes | None:
        value = self._settings.value("window/geometry")
        if value is None:
            return None
        try:
            return bytes(value)
        except (TypeError, ValueError):
            return None

    def set_geometry(self, blob: bytes) -> None:
        self._settings.setValue("window/geometry", bytes(blob))

    def volume(self) -> int | None:
        return clamp_volume(self._settings.value("sound/volume"))

    def set_volume(self, percent: int) -> None:
        self._settings.setValue("sound/volume", int(percent))

    def recent(self) -> list[Path]:
        raw = self._settings.value("recent/paths")
        if not isinstance(raw, (list, tuple)):
            return []
        return [Path(str(item)) for item in raw if str(item).strip()][:MAX_RECENT]

    def set_recent(self, paths: list[Path]) -> None:
        self._settings.setValue("recent/paths", [str(p) for p in paths][:MAX_RECENT])

    def shelf(self) -> list[Path]:
        raw = self._settings.value("shelf/roots")
        if not isinstance(raw, (list, tuple)):
            return []
        return [Path(str(item)) for item in raw if str(item).strip()][:MAX_SHELF]

    def set_shelf(self, roots: list[Path]) -> None:
        self._settings.setValue("shelf/roots", [str(p) for p in roots][:MAX_SHELF])

    def sync(self) -> None:
        self._settings.sync()
