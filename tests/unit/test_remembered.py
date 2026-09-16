"""P2 (29 Aug 2026): what the Player remembers, what it drops, and what it
offers on a disc it will not play.

Window shape and volume come back next run; the last folders and images
opened by hand are one click away; a drive letter is never remembered; a
folder or image dropped on the window opens; the encrypted dialog offers
Eject; the preview panel can read its folder again.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QMimeData, QUrl
from PyQt6.QtWidgets import QApplication, QMessageBox

from wti_player import strings
from wti_player.engine.fake import FakeEngine, simple_disc
from wti_player.optical.drives import DriveWatcher, FakeScanner, OpticalDrive
from wti_player.optical.reader import ImmediateReader
from wti_player.ui.main_window import MainWindow
from wti_player.ui.prefs import MAX_RECENT, MemoryPreferences, is_rememberable, remember


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


class _NoGamepad:
    available = False

    def read(self):
        return None


def make_window(prefs: MemoryPreferences) -> MainWindow:
    watcher = DriveWatcher(FakeScanner([OpticalDrive(mount="E:\\", description="Disc drive (E:)")]))
    return MainWindow(
        FakeEngine(simple_disc()),
        watcher=watcher,
        gamepad=_NoGamepad(),
        reader=ImmediateReader(),
        prefs=prefs,
    )


class TestTheRecentList:
    def test_a_folder_or_image_goes_to_the_front_once_and_a_drive_never(self, tmp_path: Path) -> None:
        folder = tmp_path / "disc"
        folder.mkdir()
        image = tmp_path / "film.iso"
        image.write_bytes(b"x")
        recent = remember([], folder)
        recent = remember(recent, image)
        recent = remember(recent, folder)
        assert recent == [folder, image]
        assert remember(recent, Path("E:\\")) == recent
        assert not is_rememberable(Path("D:\\"))
        assert not is_rememberable(tmp_path / "notes.txt")

    def test_the_list_is_capped(self, tmp_path: Path) -> None:
        recent: list[Path] = []
        for i in range(MAX_RECENT + 3):
            folder = tmp_path / f"d{i}"
            folder.mkdir()
            recent = remember(recent, folder)
        assert len(recent) == MAX_RECENT
        assert recent[0] == tmp_path / f"d{MAX_RECENT + 2}"

    def test_opening_by_hand_is_remembered_and_the_menu_offers_it(self, qt_app, data_disc: Path) -> None:
        prefs = MemoryPreferences()
        window = make_window(prefs)
        try:
            folder = data_disc
            window.open_path(folder)
            assert prefs.recent() == [folder]
            assert prefs.synced >= 1
            window._fill_recent_menu()
            labels = [a.text() for a in window.recent_menu.actions()]
            assert str(folder) in labels
            assert strings.CLEAR_RECENT in labels
            window._forget_recent()
            assert prefs.recent() == []
            assert [a.text() for a in window.recent_menu.actions()] == [strings.RECENT_EMPTY]
        finally:
            window.close()

    def test_a_drive_going_in_is_not_remembered(self, qt_app) -> None:
        prefs = MemoryPreferences()
        window = make_window(prefs)
        try:
            window.open_path(Path("E:\\"))
            assert prefs.recent() == []
        finally:
            window.close()

    def test_an_empty_folder_is_not_remembered_and_nothing_on_a_drive_is(self, qt_app, tmp_path: Path) -> None:
        prefs = MemoryPreferences()
        window = make_window(prefs)
        try:
            empty = tmp_path / "empty"
            empty.mkdir()
            window.open_path(empty)
            assert prefs.recent() == []
            assert remember([], Path("E:\\BDMV"), drive_roots={"E:\\"}) == []
            assert remember([], Path("e:/films/x.iso"), drive_roots={"E:\\"}) == []
        finally:
            window.close()


class TestRememberedShapeAndVolume:
    def test_volume_and_geometry_come_back(self, qt_app, monkeypatch) -> None:
        prefs = MemoryPreferences()
        first = make_window(prefs)
        first.resize(700, 500)
        first._set_volume(37)
        first.close()
        assert prefs.volume() == 37
        saved = prefs.geometry()
        assert saved

        # The offscreen screen is smaller than the window's own minimum, so
        # the shape cannot be read back off the widget here; what is pinned
        # is that the saved blob is the one handed to restoreGeometry, after
        # the UI exists.
        restored: list[bytes] = []

        def record(self_window, blob) -> bool:
            assert hasattr(self_window, "transport"), "restored before the UI was built"
            restored.append(bytes(blob))
            return True

        monkeypatch.setattr(MainWindow, "restoreGeometry", record)
        second = make_window(prefs)
        try:
            assert second._volume == 37
            assert restored == [saved]
        finally:
            second.close()

    def test_a_missing_memory_leaves_the_defaults(self, qt_app) -> None:
        window = make_window(MemoryPreferences())
        try:
            assert window._volume == 100
            assert window.engine.volume == 100
            assert window.transport._volume_button.accessibleName() == "Mute"
            assert window.width() == 1180
        finally:
            window.close()

    def test_saved_mute_can_be_identified_and_unmuted(self, qt_app) -> None:
        prefs = MemoryPreferences()
        prefs.set_volume(0)
        window = make_window(prefs)
        try:
            assert window.engine.volume == 0
            assert window.transport._volume_button.accessibleName() == "Unmute"
            window.transport._volume_button.click()
            assert window.engine.volume == 100
            assert window.transport._volume_button.accessibleName() == "Mute"
        finally:
            window.close()


class _FakeDropEvent:
    """What the window reads off a drag or drop: the mime data and an answer."""

    def __init__(self, mime: QMimeData) -> None:
        self._mime = mime
        self.accepted: bool | None = None

    def mimeData(self) -> QMimeData:
        return self._mime

    def acceptProposedAction(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.accepted = False


class TestDragAndDrop:
    def _mime(self, path: Path) -> QMimeData:
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        return mime

    def test_a_dropped_folder_opens(self, qt_app, tmp_path: Path, monkeypatch) -> None:
        window = make_window(MemoryPreferences())
        try:
            opened: list[Path] = []
            monkeypatch.setattr(window, "open_path", lambda path, **kw: opened.append(path))
            folder = tmp_path / "dropped"
            folder.mkdir()
            mime = self._mime(folder)
            enter = _FakeDropEvent(mime)
            window.dragEnterEvent(enter)  # type: ignore[arg-type]
            assert enter.accepted is True
            drop = _FakeDropEvent(mime)
            window.dropEvent(drop)  # type: ignore[arg-type]
            assert drop.accepted is True
            assert opened == [folder]
            assert window.acceptDrops()
        finally:
            window.close()

    def test_a_dropped_text_file_is_refused(self, qt_app, tmp_path: Path, monkeypatch) -> None:
        window = make_window(MemoryPreferences())
        try:
            opened: list[Path] = []
            monkeypatch.setattr(window, "open_path", lambda path, **kw: opened.append(path))
            note = tmp_path / "notes.txt"
            note.write_text("hi")
            mime = self._mime(note)
            enter = _FakeDropEvent(mime)
            window.dragEnterEvent(enter)  # type: ignore[arg-type]
            assert enter.accepted is False
            drop = _FakeDropEvent(mime)
            window.dropEvent(drop)  # type: ignore[arg-type]
            assert opened == []
        finally:
            window.close()


class TestTheEncryptedDialog:
    def test_it_offers_eject_and_eject_does_what_it_says(self, qt_app, monkeypatch) -> None:
        window = make_window(MemoryPreferences())
        try:
            ejected: list[bool] = []
            monkeypatch.setattr(window, "eject", lambda: ejected.append(True))
            boxes: list[QMessageBox] = []

            def fake_exec(self_box: QMessageBox) -> int:
                boxes.append(self_box)
                eject = next((b for b in self_box.buttons() if b.text() == strings.EJECT), None)
                # QMessageBox records the clicked button through its own slot; stand in for it.
                self_box._clicked = eject  # type: ignore[attr-defined]
                return 0

            monkeypatch.setattr(QMessageBox, "exec", fake_exec)
            monkeypatch.setattr(QMessageBox, "clickedButton", lambda self_box: getattr(self_box, "_clicked", None))
            window.explain("This DVD is encrypted", strings.PROTECTED_DVD, offer_eject=True)
            assert [b.text() for b in boxes[0].buttons()].count(strings.EJECT) == 1
            assert ejected == [True]

            window.explain("Something else", "body")
            assert strings.EJECT not in [b.text() for b in boxes[1].buttons()]
        finally:
            window.close()


class TestThePreviewReload:
    def test_reload_reads_the_folder_again(self, qt_app, tmp_path: Path, monkeypatch) -> None:
        from wti_player.ui import preview as preview_mod

        calls: list[Path] = []

        class Report:
            healthy = True
            problems: ClassVar[list[str]] = []
            lines: ClassVar[list] = []

            def as_text(self) -> str:
                return ""

        monkeypatch.setattr(preview_mod, "inspect_bdmv", lambda folder: calls.append(folder) or Report())
        panel = preview_mod.PreviewPanel()
        assert not panel.reload_button.isEnabled()
        assert panel.reload() is None
        panel.show_folder(tmp_path)
        assert panel.reload_button.isEnabled()
        panel.reload()
        assert calls == [tmp_path, tmp_path]


class TestWhatIsWrittenToDisk:
    def test_the_real_store_holds_exactly_three_keys_and_nothing_identifying(self, qt_app, tmp_path: Path) -> None:
        from PyQt6.QtCore import QSettings

        from wti_player.ui.prefs import QtPreferences

        prefs = QtPreferences()
        prefs.set_geometry(b"\x01\x02")
        prefs.set_volume(55)
        prefs.set_recent([tmp_path / "a", tmp_path / "b.iso"])
        prefs.set_shelf([tmp_path / "shelf"])
        prefs.sync()
        settings = QSettings(QtPreferences.ORGANISATION, QtPreferences.APPLICATION)
        # Four keys since the shelf (30 Aug 2026): the window, the volume, the
        # recent list and the shelf roots. The two path lists are the user's own
        # folders, chosen by them, and nothing else identifying is written: no
        # account, no name, no disc history beyond what they opened. GOLD-4
        # (11 Sep 2026): this assertion had not been told about the shelf and
        # was red for ten days, taking CI down with it.
        assert sorted(settings.allKeys()) == ["recent/paths", "shelf/roots", "sound/volume", "window/geometry"]
        for key in settings.allKeys():
            assert key.split("/")[0] in {"recent", "shelf", "sound", "window"}, key
        again = QtPreferences()
        assert again.volume() == 55
        assert again.geometry() == b"\x01\x02"
        assert again.recent() == [tmp_path / "a", tmp_path / "b.iso"]
        assert again.shelf() == [tmp_path / "shelf"]
