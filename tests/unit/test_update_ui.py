"""U2: Help > Check for a new Player runs off-thread, ends in one sentence,
offers a verified newer build, and is dropped when the window closes."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import QApplication

from wti_player import strings
from wti_player.engine.fake import FakeEngine, simple_disc
from wti_player.optical.drives import DriveWatcher, FakeScanner, OpticalDrive
from wti_player.optical.reader import ImmediateReader
from wti_player.ui.main_window import MainWindow
from wti_player.update.check import Outcome
from wti_player.update.feed import Release
from wti_player.update.ui import UpdateCheck


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


class _NoGamepad:
    available = False

    def read(self):
        return None


@pytest.fixture
def window(qt_app):
    engine = FakeEngine(simple_disc())
    watcher = DriveWatcher(FakeScanner([OpticalDrive(mount="E:\\", description="Disc drive (E:)")]))
    made = MainWindow(engine, watcher=watcher, gamepad=_NoGamepad(), reader=ImmediateReader())
    yield made
    made.close()


def settle(qt_app, check: UpdateCheck, tries: int = 200) -> None:
    QThreadPool.globalInstance().waitForDone(5000)
    for _ in range(tries):
        qt_app.processEvents()
        if not check.busy:
            return
    raise AssertionError("the check never delivered")


RELEASE = Release(
    version="9.9.9",
    url="https://github.com/playtabegg/goldwing-media-player/releases/download/v9.9.9/WeTheIndiesPlayer-Setup-9.9.9.exe",
    sha256="0" * 64,
    size=1,
    signature="x",
    installer="inno",
    args=("/VERYSILENT",),
    notes_url="https://github.com/playtabegg/goldwing-media-player/releases/tag/v9.9.9",
)


class TestTheMenuItem:
    def test_it_is_in_the_help_menu_and_nothing_imports_the_update_package_before_a_click(self, window) -> None:
        import sys

        titles = [
            action.text()
            for top in window.menuBar().actions()
            if top.menu() is not None
            for action in top.menu().actions()
        ]
        assert strings.UPDATE_MENU in titles
        assert window._update_check is None
        assert sys  # the lazy import itself is pinned by test_no_network_by_default

    def test_a_check_ends_in_one_sentence_on_the_banner(self, qt_app, window) -> None:
        said: list[str] = []
        window.report = lambda message, **kw: said.append(message)  # type: ignore[method-assign]
        window.check_for_updates(check=lambda: Outcome("You have the newest GoldWing, 1.0.0."))
        assert window._update_check is not None
        settle(qt_app, window._update_check)
        assert said == [strings.UPDATE_CHECKING, "You have the newest GoldWing, 1.0.0."]
        assert window._update_box is None

    def test_a_newer_build_is_offered_with_the_two_buttons(self, qt_app, window) -> None:
        window.check_for_updates(check=lambda: Outcome("Player 9.9.9 is out. You have 1.0.0.", RELEASE))
        settle(qt_app, window._update_check)
        box = window._update_box
        assert box is not None
        labels = [button.text() for button in box.buttons()]
        assert strings.UPDATE_GET in labels
        assert strings.UPDATE_NOT_NOW in labels
        assert strings.UPDATE_NOTES in labels
        assert "9.9.9" in box.text() and "1.0.0" in box.text()
        box.close()

    def test_a_second_click_while_one_runs_is_ignored(self, qt_app, window) -> None:
        import threading

        gate = threading.Event()
        calls = []

        def slow() -> Outcome:
            calls.append(1)
            gate.wait(5)
            return Outcome("first.")

        said: list[str] = []
        window.report = lambda message, **kw: said.append(message)  # type: ignore[method-assign]
        window.check_for_updates(check=slow)
        window.check_for_updates(check=lambda: Outcome("second."))
        gate.set()
        settle(qt_app, window._update_check)
        assert calls == [1]
        assert said[-1] == "first."

    def test_a_check_that_raises_is_still_one_sentence(self, qt_app, window) -> None:
        def boom() -> Outcome:
            raise RuntimeError("socket exploded")

        said: list[str] = []
        window.report = lambda message, **kw: said.append(message)  # type: ignore[method-assign]
        window.check_for_updates(check=boom)
        settle(qt_app, window._update_check)
        assert said[-1] == strings.UPDATE_UNEXPECTED

    def test_closing_the_window_drops_the_answer(self, qt_app, window) -> None:
        import threading

        gate = threading.Event()
        delivered = []

        def slow() -> Outcome:
            gate.wait(5)
            return Outcome("late.")

        window.check_for_updates(check=slow)
        check = window._update_check
        original = window.report
        window.report = lambda message, **kw: delivered.append(message)  # type: ignore[method-assign]
        window.close()
        gate.set()
        QThreadPool.globalInstance().waitForDone(5000)
        for _ in range(50):
            qt_app.processEvents()
        window.report = original  # type: ignore[method-assign]
        assert "late." not in delivered
        assert check is not None and not check.busy


class TestTheChecker:
    def test_is_stateless_between_runs(self, qt_app) -> None:
        check = UpdateCheck()
        seen: list[str] = []
        check.start(lambda o: seen.append(o.sentence), check=lambda: Outcome("one."))
        settle(qt_app, check)
        check.start(lambda o: seen.append(o.sentence), check=lambda: Outcome("two."))
        settle(qt_app, check)
        assert seen == ["one.", "two."]
        assert not hasattr(check, "last_checked")


class TestTheInstallPath:
    """Both chains, both required: a download that fails Authenticode is
    never launched, and one that passes is handed to the waiter."""

    def _drive(self, qt_app, monkeypatch, ours: bool):
        from pathlib import Path

        from wti_player.update import ui as ui_mod

        launched: list[tuple[Path, tuple[str, ...]]] = []
        said: list[str] = []
        monkeypatch.setattr(ui_mod, "is_ours", lambda path: ours)
        monkeypatch.setattr(ui_mod, "launch_installer", lambda path, args: launched.append((path, args)))
        monkeypatch.setattr(ui_mod, "trusted_keys", lambda: [])

        def fake_download(release, folder, pubs):
            path = folder / "wti-player-setup.exe"
            path.write_bytes(b"MZ")
            return path

        monkeypatch.setattr(ui_mod, "download_installer", fake_download)
        check = UpdateCheck()
        check.install(RELEASE, said.append)
        settle(qt_app, check)
        return launched, said

    def test_a_download_that_is_not_ours_is_never_launched(self, qt_app, monkeypatch) -> None:
        launched, said = self._drive(qt_app, monkeypatch, ours=False)
        assert launched == []
        assert said == [strings.UPDATE_NOT_OURS]

    def test_a_download_that_is_ours_is_handed_to_the_installer_with_the_feed_args(self, qt_app, monkeypatch) -> None:
        launched, said = self._drive(qt_app, monkeypatch, ours=True)
        assert len(launched) == 1
        assert launched[0][0].name == "wti-player-setup.exe"
        assert launched[0][1] == RELEASE.args
        assert said == [strings.UPDATE_INSTALLING]

    def test_a_failed_download_leaves_no_folder_behind(self, qt_app, monkeypatch, tmp_path) -> None:
        import tempfile

        from wti_player.update import ui as ui_mod
        from wti_player.update.download import DownloadProblem

        made: list[str] = []
        real = tempfile.mkdtemp

        def mkdtemp(prefix=""):
            folder = real(prefix=prefix, dir=str(tmp_path))
            made.append(folder)
            return folder

        monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp)
        monkeypatch.setattr(ui_mod, "trusted_keys", lambda: [])

        def failing(release, folder, pubs):
            (folder / "half.exe").write_bytes(b"MZ")
            raise DownloadProblem("The download does not match the release\'s checksum.")

        monkeypatch.setattr(ui_mod, "download_installer", failing)
        said: list[str] = []
        check = UpdateCheck()
        check.install(RELEASE, said.append)
        settle(qt_app, check)
        assert said == ["The download does not match the release\'s checksum."]
        assert made and not any(__import__("os").path.exists(folder) for folder in made)
