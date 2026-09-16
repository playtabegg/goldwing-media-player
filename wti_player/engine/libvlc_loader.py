"""Find libvlc and import ``python-vlc`` against it.

The Player never assumes VLC is installed on the machine. It carries its own
copy, and this module is the only place that knows where to look:

1. ``vendor/vlc`` in the repo — what ``tools/fetch_vlc.py`` creates, and what
   a developer gets. Also the frozen build's ``_internal/vlc`` next to the EXE.
2. ``$WTI_PLAYER_VLC_HOME`` — an operator escape hatch.
3. A system VLC (Program Files, then the ``VideoLAN/VLC`` registry key), so a
   machine that already has VLC works without the vendored copy.

``python-vlc`` decides where to load the DLL from *at import time*, from the
process environment, so nothing may import ``vlc`` before :func:`load_vlc`
has run. Import this module instead of ``vlc`` anywhere in the app.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

#: Env var an operator can set to point at any VLC 3.x directory.
VLC_HOME_ENV = "WTI_PLAYER_VLC_HOME"

#: Files that must be present for a directory to count as a VLC runtime.
_REQUIRED = ("libvlc.dll", "libvlccore.dll", "plugins")

#: Plugins that mean a runtime carries a CSS descrambler. VideoLAN compiles
#: libdvdcss straight into these two — not as a separate DLL, so their mere
#: presence is the whole signal — and a runtime holding them is one this
#: program must not use, wherever it came from.
_FORBIDDEN_PLUGINS = ("libdvdread_plugin.dll", "libdvdnav_plugin.dll")

_loaded: ModuleType | None = None
_loaded_from: Path | None = None


class RuntimeRefused(RuntimeError):
    """A VLC runtime was found and is not one we are willing to use."""


class LibVlcNotFound(RuntimeError):
    """No usable VLC runtime on this machine.

    Carries the list of places that were tried, because the answer the user
    needs ("run tools/fetch_vlc.py") depends on which of them was empty.
    """

    def __init__(self, searched: list[Path]) -> None:
        self.searched = searched
        listing = "\n  ".join(str(path) for path in searched) or "(nowhere)"
        super().__init__(
            "Goldwing could not find its video engine (libvlc).\n"
            f"Looked in:\n  {listing}\n"
            "In a source checkout, run:  python tools/fetch_vlc.py"
        )


@dataclass(frozen=True)
class VlcRuntime:
    """A located VLC 3.x runtime directory."""

    home: Path

    @property
    def libvlc(self) -> Path:
        return self.home / "libvlc.dll"

    @property
    def plugins(self) -> Path:
        return self.home / "plugins"


def _is_runtime(path: Path) -> bool:
    return all((path / name).exists() for name in _REQUIRED)


def carries_descrambler(home: Path) -> bool:
    """Does this runtime hold VideoLAN's DVD plugins?

    Those plugins have libdvdcss compiled into them, so a runtime with either
    of them is a runtime that can break CSS. Ours is built without them; a
    VLC somebody installed from videolan.org has both.
    """
    plugins = home / "plugins"
    if not plugins.is_dir():
        return False
    for name in _FORBIDDEN_PLUGINS:
        try:
            if any(plugins.rglob(name)):
                return True
        except OSError:
            continue
    return False


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _frozen_root() -> Path | None:
    """Where PyInstaller unpacked us, if we are frozen."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return None


def _registry_vlc() -> Path | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:  # pragma: no cover - Windows only
        return None
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(
                    hive, r"SOFTWARE\VideoLAN\VLC", 0, winreg.KEY_READ | view
                ) as key:
                    install_dir, _ = winreg.QueryValueEx(key, "InstallDir")
            except OSError:
                continue
            if install_dir:
                return Path(install_dir)
    return None


def candidate_homes() -> list[Path]:
    """Every directory we would accept a VLC runtime from, best first."""
    candidates: list[Path] = []
    frozen = _frozen_root()
    if frozen is not None:
        candidates.append(frozen / "vlc")
        candidates.append(Path(sys.executable).parent / "vlc")
    candidates.append(_repo_root() / "vendor" / "vlc")

    override = os.environ.get(VLC_HOME_ENV)
    if override:
        candidates.insert(0, Path(override))

    if frozen is not None:
        # A built Player looks in exactly two places, both inside itself.
        # Everything below this line is for a source checkout.
        return _unique(candidates)

    if sys.platform == "win32":
        for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env_name)
            if base:
                candidates.append(Path(base) / "VideoLAN" / "VLC")
        registry = _registry_vlc()
        if registry is not None:
            candidates.append(registry)
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/VLC.app/Contents/MacOS/lib"))
    else:
        candidates.append(Path("/usr/lib/x86_64-linux-gnu"))

    return _unique(candidates)


def _unique(candidates: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def find_runtime() -> VlcRuntime:
    """Locate a VLC runtime we are willing to use, or raise.

    Two rules, and both are about the CSS ruling rather than about finding a
    library.

    **A built Player uses the runtime it shipped with, and nothing else.**
    The search below falls through to Program Files and the registry, which
    is a convenience for a source checkout. In a build it would mean that a
    damaged bundled runtime silently promotes the Player onto VideoLAN's own
    VLC — whose DVD plugins have libdvdcss compiled in. The product would
    then be shipping a lock-breaker, with nothing on screen to say so.

    **And any runtime carrying those plugins is refused**, wherever it came
    from. Belt as well as braces: the first rule depends on knowing we are
    frozen, and this one does not depend on anything.
    """
    searched = candidate_homes()
    refused: list[Path] = []
    for candidate in searched:
        if not _is_runtime(candidate):
            continue
        if carries_descrambler(candidate):
            refused.append(candidate)
            continue
        return VlcRuntime(candidate)

    if refused:
        listing = "\n  ".join(str(path) for path in refused)
        raise RuntimeRefused(
            "Goldwing found a video engine it will not use.\n"
            f"  {listing}\n"
            "That runtime carries VideoLAN's DVD plugins, which have a CSS "
            "descrambler compiled into them. Goldwing does not ship one and "
            "will not borrow one.\n"
            "Reinstalling Goldwing restores its own engine."
        )
    raise LibVlcNotFound(searched)


def load_vlc() -> ModuleType:
    """Import ``python-vlc`` bound to our runtime. Idempotent."""
    global _loaded, _loaded_from
    if _loaded is not None:
        return _loaded

    runtime = find_runtime()
    # python-vlc reads both of these during its own import.
    os.environ["PYTHON_VLC_LIB_PATH"] = str(runtime.libvlc)
    os.environ["PYTHON_VLC_MODULE_PATH"] = str(runtime.plugins)
    # libvlc.dll resolves libvlccore.dll from the DLL search path, which on
    # Python 3.8+ no longer includes PATH.
    if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(runtime.home))

    import vlc

    _loaded = vlc
    _loaded_from = runtime.home
    return vlc


def loaded_from() -> Path | None:
    """The runtime :func:`load_vlc` bound to, or ``None`` if it has not run."""
    return _loaded_from


def has_plugin(name: str) -> bool:
    """Is a VLC plugin present in the runtime we are bound to?

    The Player builds without the DVD plugins while we have no CSS-free ones,
    so it has to be able to say "this build cannot do DVDs" rather than open a
    disc and fail in a way nobody can read.
    """
    try:
        runtime = find_runtime()
    except LibVlcNotFound:
        return False
    return any(runtime.plugins.rglob(name))


def libvlc_version() -> str:
    """e.g. ``3.0.23 Vetinari``. Loads the runtime if needed."""
    vlc = load_vlc()
    raw = vlc.libvlc_get_version()
    return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
