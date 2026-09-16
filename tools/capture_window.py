"""Photograph the Player's own window, overlay and all.

``libvlc_video_take_snapshot`` returns the video plane and nothing above it,
so a Blu-ray menu snapshotted that way is the background with no buttons on
it. That is what the spike hit and what anybody checking a menu will hit
again, so the way round it lives here rather than in somebody's shell
history.

The way round it is Windows' own ``PrintWindow`` with ``PW_RENDERFULLCONTENT``,
which asks the compositor for what is actually on screen — including a
Direct3D surface a screen grab of the desktop would also catch, but without
needing the window to be in front of anything.

    python tools/capture_window.py <disc> <out.png> [--seconds 12] [--down 1]

Nothing here ships.
"""

from __future__ import annotations

import argparse
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Ask the compositor for the window's real contents, not a WM_PRINT repaint.
PW_RENDERFULLCONTENT = 0x00000002


def find_window(title_fragment: str) -> int:
    """The first top-level window whose title contains ``title_fragment``."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(handle, _param):
        length = user32.GetWindowTextLengthW(handle)
        if length:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(handle, buffer, length + 1)
            if title_fragment.lower() in buffer.value.lower():
                found.append(handle)
                return False
        return True

    user32.EnumWindows(each, 0)
    return found[0] if found else 0


def capture(handle: int, out: Path) -> bool:
    """PrintWindow the given HWND into ``out``. False if it produced nothing."""
    from PyQt6.QtGui import QGuiApplication

    application = QGuiApplication.instance() or QGuiApplication([])
    assert application

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    rect = wintypes.RECT()
    user32.GetWindowRect(handle, ctypes.byref(rect))
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return False

    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return False
    # Qt's own grabWindow goes through the same compositor path and saves
    # writing a DIB by hand.
    pixmap = screen.grabWindow(handle)
    if pixmap.isNull():
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    return bool(pixmap.save(str(out)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Photograph the Player's window.")
    parser.add_argument("disc")
    parser.add_argument("out", type=Path)
    parser.add_argument("--seconds", type=float, default=14.0, help="how long to let it settle")
    parser.add_argument("--down", type=int, default=0, help="presses of Down before the shot")
    parser.add_argument("--title", default="Goldwing Media Player")
    args = parser.parse_args(argv)

    exe = REPO / "dist" / "Player" / "Player.exe"
    command = (
        [str(exe), args.disc]
        if exe.is_file()
        else [sys.executable, str(REPO / "Player.pyw"), args.disc]
    )
    print("  launching", command[0])
    process = subprocess.Popen(command)
    try:
        handle = 0
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline and not handle:
            time.sleep(0.5)
            handle = find_window(args.title)
        if not handle:
            print("  the Player's window never appeared")
            return 1
        print(f"  window {handle:#x}, settling for {args.seconds:.0f}s")
        time.sleep(args.seconds)

        if args.down:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.SetForegroundWindow(handle)
            time.sleep(0.5)
            for _ in range(args.down):
                user32.keybd_event(0x28, 0, 0, 0)   # VK_DOWN
                user32.keybd_event(0x28, 0, 2, 0)
                time.sleep(0.6)
            time.sleep(1.0)

        if not capture(handle, args.out):
            print("  the window would not photograph")
            return 1
        print(f"  {args.out}  ({args.out.stat().st_size:,} bytes)")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    sys.exit(main())
