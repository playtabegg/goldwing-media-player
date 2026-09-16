"""What this build calls itself."""

from __future__ import annotations

#: Bumped by hand at release. The download page shows the same string, and
#: pyproject.toml reads it from here, so there is one place it lives.
VERSION = "1.0.0"

#: Kept for source compatibility; release UI uses the stable version.
EARLY_BUILD = False

#: Which build this is. Written by tools/build_exe.py as
#: wti_player/_build_stamp.py (git commit and date) and absent in a source
#: checkout; it goes into the PE version block and the About box so a bug
#: report can say exactly which bytes it came from.
try:
    from ._build_stamp import BUILD_STAMP
except ImportError:  # pragma: no cover - a source checkout
    BUILD_STAMP = ""

APP_NAME = "Goldwing Media Player"
SHORT_NAME = "Goldwing"
PUBLISHER = "We The Indies, LLC"

#: The named mutex a running Player holds. The installer's ``AppMutex``
#: looks for it, so an upgrade over a running Player asks first instead of
#: replacing files under it; the update path releases it before it starts
#: the installer.
MUTEX_NAME = "WeTheIndiesPlayer.Mutex"


def build_stamp() -> str:
    """``<short sha> <date>`` for a built Player, or ``source checkout``."""
    return BUILD_STAMP or "source checkout"


def display_version() -> str:
    return VERSION


def window_title(subject: str = "") -> str:
    parts = [subject, APP_NAME] if subject else [APP_NAME]
    # A middle dot, never an em-dash: the one house rule on every string.
    return " · ".join(parts)
