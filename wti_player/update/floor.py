"""The highest feed version a successful signed parse has already shown.

The check used to remember nothing. A still-validly-signed older
``latest.json`` that is newer than the running build would then be
offered (feed rollback, stale mirror). The floor is that mark: persist
a parsed feed's version when it is newer than what is stored, and refuse
an older signed feed even when it is newer than the running build. First
run has no mark, so that feed is accepted and written as today's.

The file is local, one version string, never sent. A read or write
problem is treated as "no mark": refusing every future offer because the
disk filled up, or a power cut truncated the file, would be the worse
failure.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from ._semver import vercmp

#: Same org/app names as the preferences store, a file beside them rather
#: than a QSettings key: the update package must not import Qt.
_ORG = "We The Indies"
_APP = "Player"
_NAME = "last-seen-version"
_VERSION = re.compile(r"\d+\.\d+\.\d+")


def default_path() -> Path:
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        root = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(root) / _ORG / _APP / _NAME


def last_seen(path: Path) -> str | None:
    """The stored floor, or ``None`` if missing or unreadable."""
    try:
        text = path.read_text(encoding="ascii").strip()
    except OSError:
        return None
    return text if _VERSION.fullmatch(text) else None


def remember(path: Path, version: str) -> None:
    """Write ``version`` as the new floor. Failures are ignored."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(version + "\n", encoding="ascii")
    except OSError:
        return


def raise_floor(path: Path, version: str) -> str | None:
    """Persist ``version`` when it is newer than the stored floor.

    Returns the floor that now applies (the stored one, or ``version``
    on first run / when raised). ``None`` only if there is no stored
    mark and the write failed.
    """
    seen = last_seen(path)
    if seen is None:
        remember(path, version)
        return last_seen(path) or version
    if vercmp(version, seen) > 0:
        remember(path, version)
        return version
    return seen
