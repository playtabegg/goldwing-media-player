"""Start the Player.

Two jobs beyond making a window: find the engine and say something useful if
it is not there, and make sure a crash in Qt's own callbacks reaches a person
as a sentence rather than a traceback on a console nobody is looking at.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

from . import strings
from .engine.libvlc_loader import LibVlcNotFound, RuntimeRefused
from .version import APP_NAME, VERSION


def log_path() -> Path:
    """Where the engine writes its diagnostics. Local, and never sent anywhere."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "WeTheIndies" / "Player" / "player.log"


def start_logging(path: Path) -> bool:
    """Send everything the process says to ``path``, including libvlc.

    libvlc writes its diagnostics to standard error and cannot be told to do
    anything else — every file-logging switch it has is either a VLC 2.x
    spelling it rejects or one it accepts and ignores. So the file end of the
    pipe is moved instead: file descriptor 2 is pointed at the log, which
    catches libvlc, Python, and Qt in one place and in order.

    A windowed build has no console, so without this those messages go
    nowhere at all. Returns False if the log could not be opened, because a
    diagnostic switch that cannot write is worth saying so about.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", buffering=1, encoding="utf-8", errors="replace")
    except OSError as error:
        print(f"cannot write {path}: {error}", file=sys.stderr)
        return False

    handle.write(f"\n--- {APP_NAME} {VERSION} ---\n")
    handle.flush()
    try:
        os.dup2(handle.fileno(), 2)
    except OSError:
        # No real stderr to replace, which happens under some launchers.
        pass
    sys.stderr = handle
    return True


def _install_excepthook(window: object | None = None) -> None:
    """Turn an unexpected exception into a sentence and a log line."""

    def hook(kind: type[BaseException], value: BaseException, tb: object) -> None:
        details = "".join(traceback.format_exception(kind, value, tb))  # type: ignore[arg-type]
        try:
            path = log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(details + "\n")
        except OSError:
            pass
        reporter = getattr(window, "report", None)
        if callable(reporter):
            reporter(strings.UNEXPECTED_PROBLEM)
        else:
            print(strings.UNEXPECTED_PROBLEM, file=sys.stderr)

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wti-player", description=f"{APP_NAME} {VERSION}")
    parser.add_argument("target", nargs="?", type=Path, help="a disc folder, image, or drive")
    parser.add_argument(
        "--no-hardware-decoding",
        action="store_true",
        help="decode in software: slower, but a fallback when video is wrong",
    )
    parser.add_argument(
        "--no-auto-play",
        action="store_true",
        help="do not start a disc the moment it goes in",
    )
    parser.add_argument("--log", action="store_true", help="write engine diagnostics to a file")
    args = parser.parse_args(argv)

    logging_to = None
    if args.log:
        logging_to = log_path()
        if start_logging(logging_to):
            print(f"Diagnostics are going to {logging_to}")
        else:
            logging_to = None

    from PyQt6.QtWidgets import QApplication, QMessageBox

    from .engine.vlc_engine import EngineError, VlcEngine
    from .ui.main_window import MainWindow
    from .ui.theme import STYLESHEET, load_fonts, window_icon

    application = QApplication(sys.argv[:1])
    application.setApplicationName(APP_NAME)
    application.setApplicationVersion(VERSION)
    application.setWindowIcon(window_icon())
    # The named mutex the installer looks for, so an upgrade never replaces
    # a running Player's files under it. A second Player is still allowed
    # to open: the mutex is a flag for Setup, not a lock on people.
    from .update.apply import hold_mutex

    hold_mutex()
    # Before the stylesheet, which names both families: a face registered
    # after a widget is styled is a face that widget will not use.
    fonts = load_fonts()
    application.setStyleSheet(STYLESHEET)
    _install_excepthook()

    try:
        engine = VlcEngine(
            hardware_decoding=not args.no_hardware_decoding,
            log_file=logging_to,
        )
    except (LibVlcNotFound, RuntimeRefused, EngineError) as exc:
        QMessageBox.critical(None, APP_NAME, str(exc))
        return 1
    except Exception as exc:
        # A windowed build has no console. Anything that gets out of here
        # unhandled is a Player that starts, shows nobody anything, and
        # exits — which is the worst way for software to fail, because
        # there is nothing to report and nothing to try.
        QMessageBox.critical(None, APP_NAME, strings.engine_would_not_start(exc))
        return 1

    window = MainWindow(engine, auto_play=not args.no_auto_play)
    _install_excepthook(window)
    window.show()
    if not fonts.complete:
        # Not worth a dialog — the Player works, it just looks like Windows.
        print(fonts.describe(), file=sys.stderr)

    if args.target is not None:
        window.open_path(args.target)

    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
