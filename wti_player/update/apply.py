"""Hand the verified installer to Windows and get out of its way.

The installer is Inno. It is started detached with the feed's silent
arguments, after this process has released its single-instance mutex, so
Inno does not find the Player running. Then the Player quits; the installer
relaunches the new one.

This module never decides to run anything. It is called from a button whose
label says what it does, after the download verified twice.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ..version import MUTEX_NAME

_mutex_handle: int | None = None
ERROR_ALREADY_EXISTS = 183


def hold_mutex(name: str = MUTEX_NAME) -> bool:
    """Create the named mutex Inno's ``AppMutex`` looks for. Returns True if
    this is the first Player, False if one is already running. No-op off
    Windows."""
    global _mutex_handle
    if sys.platform != "win32":
        return True
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    handle = kernel32.CreateMutexW(None, False, name)
    already = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
    _mutex_handle = handle or None
    return not already


def release_mutex() -> None:
    global _mutex_handle
    if _mutex_handle is None or sys.platform != "win32":
        _mutex_handle = None
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle(_mutex_handle)
    _mutex_handle = None


def _ps_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def installer_command(installer: Path, args: tuple[str, ...], wait_for_pid: int) -> list[str]:
    """A detached PowerShell that waits for this Player to exit, then starts
    Setup. Inno copies over Player.exe, so Setup must not begin while the
    file is mapped; and the Player cannot wait for itself."""
    from .verify import powershell_path

    arg_list = ", ".join(_ps_quote(arg) for arg in args) or "''"
    script = (
        f"Wait-Process -Id {int(wait_for_pid)} -ErrorAction SilentlyContinue; "
        f"Start-Process -FilePath {_ps_quote(str(installer))} -ArgumentList @({arg_list})"
    )
    return [str(powershell_path()), "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script]


def launch_installer(installer: Path, args: tuple[str, ...], wait_for_pid: int | None = None) -> None:
    """Hand Setup to a detached waiter and release the mutex. Raises OSError
    if Windows would not start it."""
    release_mutex()
    flags = 0
    if sys.platform == "win32":
        # Windows PowerShell silently skips its command under DETACHED_PROCESS.
        # A hidden console runs the waiter without showing a terminal window.
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    command = installer_command(installer, args, os.getpid() if wait_for_pid is None else wait_for_pid)
    environment = {k: v for k, v in os.environ.items() if k.casefold() != 'psmodulepath'}
    # Setup's relaunch must start a fresh frozen application, not inherit the
    # outgoing PyInstaller application's process state.
    environment['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    subprocess.Popen(
        command,
        close_fds=True,
        creationflags=flags,
        cwd=str(installer.parent),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
