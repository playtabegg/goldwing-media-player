"""A18 (28 Aug 2026): the Player opens no socket unless a person clicks
Help > Check for a new Player. Two proofs: a static one over the source,
and a live one that builds the window with sockets forbidden.
"""

from __future__ import annotations

import os
import re
import socket
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "wti_player"
NETWORK_IMPORTS = re.compile(r"^\s*(import|from)\s+(urllib|http\.client|socket|ssl|requests|httpx)\b", re.M)

#: The only files allowed to import a network module.
ALLOWED = {
    PACKAGE / "update" / "feed.py",
}


class TestStatically:
    def test_only_the_feed_module_imports_a_network_library(self) -> None:
        offenders = []
        for path in PACKAGE.rglob("*.py"):
            if path in ALLOWED:
                continue
            if NETWORK_IMPORTS.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(PACKAGE)))
        assert offenders == []

    def test_the_update_package_is_imported_only_from_the_help_handler(self) -> None:
        offenders = []
        for path in PACKAGE.rglob("*.py"):
            if path.is_relative_to(PACKAGE / "update"):
                continue
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"^(\s*)from \.\.?update(\.[a-z_]+)? import", text, re.M):
                indent = match.group(1)
                # A module-level import (no indent) would load it at startup.
                if indent == "":
                    offenders.append(f"{path.relative_to(PACKAGE)}: top-level import of the update package")
        assert offenders == []

    def test_nothing_in_the_package_schedules_a_check(self) -> None:
        # Outside the update package, nothing names the check at all; inside
        # it, only check.py defines it and ui.py binds it for the worker.
        outside = "\n".join(
            p.read_text(encoding="utf-8")
            for p in PACKAGE.rglob("*.py")
            if not p.is_relative_to(PACKAGE / "update")
        )
        assert "check_for_update(" not in outside
        assert "check_for_update" not in outside.replace("check_for_updates", "")
        assert "QTimer" not in (PACKAGE / "update" / "ui.py").read_text(encoding="utf-8")


class TestLive:
    def test_building_the_window_opens_no_socket(self, monkeypatch) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        pytest.importorskip("PyQt6.QtWidgets")
        from PyQt6.QtWidgets import QApplication

        def forbidden(*args, **kwargs):
            raise AssertionError("a socket was opened during startup")

        monkeypatch.setattr(socket, "socket", forbidden)
        monkeypatch.setattr(socket, "create_connection", forbidden)

        from wti_player.engine.fake import FakeEngine, simple_disc
        from wti_player.optical.drives import DriveWatcher, FakeScanner, OpticalDrive
        from wti_player.optical.reader import ImmediateReader
        from wti_player.ui.main_window import MainWindow

        class _NoGamepad:
            available = False

            def read(self):
                return None

        # Other tests in this process import the update package on purpose;
        # forget it here so a startup import would show up as a fresh entry.
        for name in [m for m in sys.modules if m.startswith("wti_player.update")]:
            monkeypatch.delitem(sys.modules, name)

        QApplication.instance() or QApplication([])
        watcher = DriveWatcher(FakeScanner([OpticalDrive(mount="E:\\", description="Disc drive (E:)")]))
        window = MainWindow(FakeEngine(simple_disc()), watcher=watcher, gamepad=_NoGamepad(), reader=ImmediateReader())
        try:
            window.show()
            for _ in range(20):
                QApplication.instance().processEvents()
            assert "wti_player.update.feed" not in sys.modules
            assert window._update_check is None
        finally:
            window.close()
