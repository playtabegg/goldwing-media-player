"""Record the Player playing a disc: a short MP4 of its window and a still from the middle of it.

    python tools/capture_clip.py <disc> <out stem> [--seconds 15] [--settle 8] [--feature]

Launches the release EXE (``dist/Player/Player.exe``) on the disc and brings its window to the front. With
``--feature`` it chooses Play > Play main feature from the keyboard (Alt+P, Enter), so a Blu-ray goes past its menu to
the film. Once the picture has settled it records the window's rectangle with ffmpeg's Desktop Duplication grabber
(``ddagrab``), which sees the video surface that a window capture (``tools/capture_window.py``) photographs as black,
then keeps a still from the middle of the clip: ``<out stem>.mp4`` and ``<out stem>.png``.

The window must be on the primary monitor with nothing on top of it while it records. Nothing here ships.
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
sys.path.insert(0, str(REPO))

from tools.capture_window import find_window  # noqa: E402

VK_MENU = 0x12
VK_RETURN = 0x0D
KEY_P = 0x50
KEYEVENTF_KEYUP = 0x0002
DWMWA_EXTENDED_FRAME_BOUNDS = 9
SW_RESTORE = 9


def _key(code: int) -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.keybd_event(code, 0, 0, 0)
    user32.keybd_event(code, 0, KEYEVENTF_KEYUP, 0)


def play_main_feature(handle: int) -> None:
    """Play > Play main feature, by keyboard."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetForegroundWindow(handle)
    time.sleep(0.4)
    user32.keybd_event(VK_MENU, 0, 0, 0)
    _key(KEY_P)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.6)
    _key(VK_RETURN)


def window_rect(handle: int) -> tuple[int, int, int, int]:
    """The window's visible rectangle in physical pixels, without the invisible resize border."""
    rect = wintypes.RECT()
    dwm = ctypes.WinDLL("dwmapi")
    if dwm.DwmGetWindowAttribute(handle, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)) != 0:
        ctypes.WinDLL("user32").GetWindowRect(handle, ctypes.byref(rect))
    width = (rect.right - rect.left) // 2 * 2
    height = (rect.bottom - rect.top) // 2 * 2
    return rect.left, rect.top, width, height


def record(rect: tuple[int, int, int, int], out: Path, seconds: float) -> None:
    left, top, width, height = rect
    source = (
        f"ddagrab=output_idx=0:framerate=30:draw_mouse=0:offset_x={max(0, left)}:offset_y={max(0, top)}"
        f":video_size={width}x{height},hwdownload,format=bgra"
    )
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", source, "-t", str(seconds),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            str(out),
        ],
        check=True,
    )


def still(clip: Path, at: float, out: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at:.2f}", "-i", str(clip), "-frames:v", "1", str(out)],
        check=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record the Player's window playing a disc.")
    parser.add_argument("disc")
    parser.add_argument("out", type=Path, help="output path without extension")
    parser.add_argument("--seconds", type=float, default=15.0)
    parser.add_argument("--settle", type=float, default=8.0, help="seconds to wait before recording")
    parser.add_argument("--feature", action="store_true", help="choose Play main feature first")
    parser.add_argument("--title", default="GoldWing Media Player")
    parser.add_argument("--exe", type=Path, default=REPO / "dist" / "Player" / "Player.exe")
    args = parser.parse_args(argv)

    # Physical pixels, so the rectangle matches what Desktop Duplication sees on a scaled display.
    ctypes.windll.user32.SetProcessDPIAware()
    if not args.exe.is_file():
        print(f"  no release EXE at {args.exe}")
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen([str(args.exe), args.disc])
    try:
        handle = 0
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline and not handle:
            time.sleep(0.5)
            handle = find_window(args.title)
        if not handle:
            print("  the Player's window never appeared")
            return 1
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.ShowWindow(handle, SW_RESTORE)
        user32.SetForegroundWindow(handle)
        time.sleep(2.0)
        if args.feature:
            play_main_feature(handle)
        time.sleep(args.settle)
        user32.SetForegroundWindow(handle)
        clip = args.out.with_suffix(".mp4")
        record(window_rect(handle), clip, args.seconds)
        picture = args.out.with_suffix(".png")
        still(clip, args.seconds / 2, picture)
        print(f"  {clip} ({clip.stat().st_size:,} bytes), {picture}")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    sys.exit(main())
