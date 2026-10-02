"""1.0.3, the polish pass: what a customer hits first.

Each test holds one item of the audit of 8 Sep 2026 that still stood in
1.0.2: the window fits the screen, Eject ejects, a disc that cannot be read
is not called an empty drive, one of our own discs is never called a locked
commercial DVD, a download nobody is waiting for is removed, and the About
box says where the source is.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from wti_player import strings
from wti_player.engine.fake import FakeEngine, simple_disc
from wti_player.optical import drives as drives_module
from wti_player.optical import meta as disc_meta
from wti_player.optical.drives import DriveWatcher, FakeScanner, OpticalDrive, unreadable_error
from wti_player.optical.identify import DiscKind, DiscProfile
from wti_player.optical.reader import ImmediateReader
from wti_player.ui import fit
from wti_player.ui.main_window import MainWindow
from wti_player.ui.prefs import MemoryPreferences
from wti_player.update import ui as update_ui

MOUNT = "Q:\\"


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


class _NoGamepad:
    available = False

    def read(self):
        return None


class _StuckScanner(FakeScanner):
    """A drive whose tray will not open by itself."""

    def eject_media(self, mount: str) -> bool:
        return False


def _window(scanner: FakeScanner) -> MainWindow:
    watcher = DriveWatcher(scanner)
    watcher.poll()
    return MainWindow(FakeEngine(simple_disc()), watcher=watcher, gamepad=_NoGamepad(), reader=ImmediateReader(), prefs=MemoryPreferences())


def _disc_in_drive() -> FakeScanner:
    return FakeScanner([OpticalDrive(mount=MOUNT, description="Disc drive (Q:)", has_media=True, label="FILM")])


class TestTheWindowFitsTheScreen:
    def test_a_large_screen_gets_the_design_size(self) -> None:
        assert fit.fit_size(1920, 1040) == (1180, 720)

    def test_a_scaled_laptop_gets_a_window_that_is_all_on_the_screen(self) -> None:
        # 1366 x 768 at 125 percent, less the taskbar.
        width, height = fit.fit_size(1093, 574)
        assert width <= 1093 - fit.FRAME_WIDTH and height <= 574 - fit.FRAME_HEIGHT

    def test_a_screen_that_reports_nothing_leaves_the_size_alone(self) -> None:
        assert fit.fit_size(0, 0) == (1180, 720)


class TestEjectOpensTheDrive:
    def test_a_disc_from_a_drive_is_ejected_and_the_person_is_told(self, qt_app) -> None:
        scanner = _disc_in_drive()
        window = _window(scanner)
        try:
            window.profile = DiscProfile(kind=DiscKind.DVD_VIDEO, root=Path(MOUNT))
            window.eject()
            assert scanner.scan()[0].has_media is False
            assert strings.EJECTED in window.banner._label.text()
        finally:
            window.close()

    def test_a_drive_that_will_not_open_names_its_own_button(self, qt_app) -> None:
        window = _window(_StuckScanner([OpticalDrive(mount=MOUNT, has_media=True)]))
        try:
            window.profile = DiscProfile(kind=DiscKind.DVD_VIDEO, root=Path(MOUNT))
            window.eject()
            assert strings.EJECT_BY_HAND in window.banner._label.text()
        finally:
            window.close()

    def test_a_folder_has_no_tray_and_no_drive_is_touched(self, qt_app, tmp_path: Path) -> None:
        scanner = _disc_in_drive()
        window = _window(scanner)
        try:
            window.profile = DiscProfile(kind=DiscKind.DVD_VIDEO, root=tmp_path)
            window.eject()
            assert scanner.scan()[0].has_media is True
        finally:
            window.close()

    def test_a_scanner_that_cannot_eject_says_no_and_does_not_raise(self) -> None:
        class Bare:
            def scan(self) -> list[OpticalDrive]:
                return [OpticalDrive(mount=MOUNT, has_media=True)]

        assert DriveWatcher(Bare()).eject(MOUNT) is False

    def test_the_real_ejector_refuses_anything_that_is_not_a_drive_letter(self) -> None:
        assert drives_module._eject_windows("") is False
        assert drives_module._eject_windows("/mnt/disc") is False


class TestADiscThatCannotBeRead:
    def test_only_not_ready_is_an_empty_tray(self) -> None:
        assert unreadable_error(21) is False  # ERROR_NOT_READY: nothing in the drive
        assert unreadable_error(0) is False  # no error recorded is no evidence of a disc
        assert unreadable_error(1005) is True  # ERROR_UNRECOGNIZED_VOLUME
        assert unreadable_error(23) is True  # ERROR_CRC

    def test_the_drive_says_so_and_not_empty(self) -> None:
        drive = OpticalDrive(mount=MOUNT, description="Disc drive (Q:)", unreadable=True)
        assert drive.describe() == "Disc drive (Q:) · a disc that cannot be read"
        assert OpticalDrive(mount=MOUNT, description="Disc drive (Q:)").describe() == "Disc drive (Q:) · empty"


class TestOurOwnDiscIsNeverCalledLocked:
    def test_a_dvd_with_our_document_is_not_copy_protection(self, qt_app, tmp_path: Path) -> None:
        window = _window(FakeScanner())
        try:
            window._playing_started = False
            window.profile = DiscProfile(kind=DiscKind.DVD_VIDEO, root=tmp_path)
            assert window._looks_like_css() is True
            window.profile = DiscProfile(kind=DiscKind.DVD_VIDEO, root=tmp_path, meta=disc_meta.DiscMeta(title="Nosferatu", made_by="We the Indies"))
            assert window._looks_like_css() is False
        finally:
            window.close()

    def test_the_damaged_disc_words_say_what_to_try(self) -> None:
        assert "soft cloth" in strings.DAMAGED_INDEX


class TestADownloadNobodyWaitsFor:
    def test_its_folder_is_removed(self) -> None:
        folder = Path(tempfile.mkdtemp(prefix="wti-player-update-"))
        installer = folder / "GoldwingMediaPlayer-Setup.exe"
        installer.write_bytes(b"MZ")
        update_ui._discard(installer)
        assert not folder.exists()

    def test_nothing_else_is_ever_removed(self, tmp_path: Path) -> None:
        keep = tmp_path / "film.iso"
        keep.write_bytes(b"x")
        update_ui._discard(keep)
        update_ui._discard("The update could not be downloaded.")
        update_ui._discard(None)
        assert keep.exists()


class TestTheAboutBox:
    def test_it_says_where_the_source_is(self) -> None:
        text = strings.about_text()
        assert "github.com/playtabegg/goldwing-media-player" in text
        assert "<b>licences</b> folder" in text


class TestTheDownloadSaysHowFarAndCanBeStopped:
    class _Response:
        def __init__(self, body: bytes, length: str | None) -> None:
            self._body = body
            self._at = 0
            self.headers = {"Content-Length": length} if length is not None else {}

        def geturl(self) -> str:
            return "https://github.com/playtabegg/goldwing-media-player/releases/download/v1.0.3/setup.exe"

        def read(self, size: int) -> bytes:
            piece = self._body[self._at : self._at + size]
            self._at += len(piece)
            return piece

        def __enter__(self):
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    URL = "https://github.com/playtabegg/goldwing-media-player/releases/download/v1.0.3/setup.exe"

    def _serve(self, monkeypatch, body: bytes, length: str | None = None) -> None:
        from wti_player.update import feed

        monkeypatch.setattr(feed.urllib.request, "urlopen", lambda *_a, **_k: self._Response(body, length))

    def test_the_whole_body_arrives_in_pieces_and_each_piece_is_counted(self, monkeypatch) -> None:
        from wti_player.update import feed

        body = b"x" * (feed.CHUNK_BYTES * 2 + 5)
        self._serve(monkeypatch, body, str(len(body)))
        seen: list[tuple[int, int]] = []
        assert feed.fetch_bytes(self.URL, len(body), progress=lambda done, total: seen.append((done, total))) == body
        assert [done for done, _ in seen] == [feed.CHUNK_BYTES, feed.CHUNK_BYTES * 2, len(body)]
        assert {total for _, total in seen} == {len(body)}

    def test_stop_ends_the_read_at_the_next_piece(self, monkeypatch) -> None:
        from wti_player.update import feed

        self._serve(monkeypatch, b"x" * (feed.CHUNK_BYTES * 4))
        seen: list[int] = []
        with pytest.raises(feed.Stopped):
            feed.fetch_bytes(self.URL, feed.CHUNK_BYTES * 4, progress=lambda done, _t: seen.append(done), stop=lambda: len(seen) >= 2)
        assert len(seen) == 2

    def test_more_than_the_cap_is_still_refused_and_a_length_that_is_nonsense_is_nothing(self, monkeypatch) -> None:
        from wti_player.update import feed

        self._serve(monkeypatch, b"x" * 20, "plenty")
        seen: list[tuple[int, int]] = []
        with pytest.raises(feed.FeedProblem, match="more than Goldwing will read"):
            feed.fetch_bytes(self.URL, 10, progress=lambda done, total: seen.append((done, total)))
        assert seen == [(11, 0)]

    def test_the_words_count_megabytes(self) -> None:
        mb = 1024 * 1024
        assert strings.update_progress(12 * mb, 38 * mb) == "Downloading the new Goldwing: 12 of 38 MB"
        assert strings.update_progress(3 * mb, 0) == "Downloading the new Goldwing: 3 MB"

    def test_cancel_on_the_banner_stops_the_download_and_says_so(self, qt_app) -> None:
        window = _window(FakeScanner())
        try:
            window.check_for_updates(check=lambda: None)
            assert window._update_check is not None
            window._update_check.cancel()
            window._update_check.busy = True
            before = window._update_check._generation
            window._cancel_update()
            assert window._update_check._generation == before + 1
            assert window._update_check.busy is False
            assert window.banner._label.text() == strings.UPDATE_STOPPED
        finally:
            window.close()


class TestTheDiagnosticsLogIsReachableFromHelp:
    def test_the_help_menu_starts_the_log_and_keeps_it_on(self, qt_app, monkeypatch, tmp_path: Path) -> None:
        from wti_player import app

        started: list[Path] = []
        monkeypatch.setattr(app, "log_path", lambda: tmp_path / "Player" / "player.log")
        monkeypatch.setattr(app, "start_logging", lambda path: (started.append(path), True)[1])
        window = _window(FakeScanner())
        try:
            window.log_action.trigger()
            assert started == [tmp_path / "Player" / "player.log"]
            assert window.log_action.isChecked() and not window.log_action.isEnabled()
            assert window.banner._label.text() == strings.LOG_ON
        finally:
            window.close()

    def test_a_log_that_cannot_be_written_says_so_and_unticks(self, qt_app, monkeypatch, tmp_path: Path) -> None:
        from wti_player import app

        monkeypatch.setattr(app, "log_path", lambda: tmp_path / "player.log")
        monkeypatch.setattr(app, "start_logging", lambda _path: False)
        window = _window(FakeScanner())
        try:
            window.log_action.trigger()
            assert not window.log_action.isChecked() and window.log_action.isEnabled()
            assert window.banner._label.text() == strings.LOG_FAILED
        finally:
            window.close()

    def test_the_folder_is_made_and_opened(self, qt_app, monkeypatch, tmp_path: Path) -> None:
        from wti_player import app
        from wti_player.ui import main_window as window_module

        opened: list[str] = []
        monkeypatch.setattr(app, "log_path", lambda: tmp_path / "WeTheIndies" / "Player" / "player.log")
        monkeypatch.setattr(window_module.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True)
        window = _window(FakeScanner())
        try:
            window.open_diagnostics_folder()
            assert (tmp_path / "WeTheIndies" / "Player").is_dir()
            assert Path(opened[0]) == tmp_path / "WeTheIndies" / "Player"
        finally:
            window.close()

    def test_the_words_no_longer_send_anyone_to_a_command_line(self) -> None:
        assert "--log" not in strings.UNEXPECTED_PROBLEM
        assert "Help menu" in strings.UNEXPECTED_PROBLEM


class TestTheDriveCheckIsOffTheInterfaceThread:
    def test_a_scan_and_what_changed_are_two_steps(self) -> None:
        scanner = FakeScanner([OpticalDrive(mount=MOUNT, has_media=False)])
        watcher = DriveWatcher(scanner)
        assert watcher.slow is False  # a scanner a test drives answers at once
        assert DriveWatcher().slow is True  # the real one asks the machine
        assert [e.kind.value for e in watcher.apply(watcher.scan())] == ["appeared"]
        scanner.insert(MOUNT, label="FILM")
        scanned = watcher.scan()
        assert watcher.find(MOUNT).has_media is False  # a scan alone changes nothing the window reads
        assert [e.kind.value for e in watcher.apply(scanned)] == ["inserted"]
        assert watcher.poll() == []

    def test_a_slow_scan_runs_on_a_worker_and_one_at_a_time(self, qt_app) -> None:
        import threading

        from PyQt6.QtCore import QThreadPool

        gate = threading.Event()
        threads: list[int] = []

        class SlowWatcher(DriveWatcher):
            slow = True

            def scan(self) -> list[OpticalDrive]:
                threads.append(threading.get_ident())
                gate.wait(5)
                return [OpticalDrive(mount=MOUNT, description="Disc drive (Q:)", has_media=False)]

        watcher = SlowWatcher(FakeScanner())
        window = MainWindow(FakeEngine(simple_disc()), watcher=watcher, gamepad=_NoGamepad(), reader=ImmediateReader(), prefs=MemoryPreferences())
        try:
            window._drive_timer.stop()
            # The window's own first check, made as it opened, is let through and finished.
            gate.set()
            QThreadPool.globalInstance().waitForDone(5000)
            qt_app.processEvents()
            gate.clear()
            threads.clear()
            window.poll_drives()
            window.poll_drives()  # the first is still asking: this one is skipped, not queued
            gate.set()
            QThreadPool.globalInstance().waitForDone(5000)
            qt_app.processEvents()
            assert len(threads) == 1 and threads[0] != threading.get_ident()
            assert watcher.find(MOUNT) is not None
            assert window._scanning_drives is False
        finally:
            gate.set()
            window.close()


class TestWhatADiscOfOursCarries:
    """Only what the disc HAS is said: a service its maker left off is not mentioned at all."""

    def _disc(self, tmp_path: Path, game: dict, *, edition: bool = False) -> Path:
        import json

        root = tmp_path / "disc"
        root.mkdir(parents=True)
        document = {"schema": 1, "kind": "game", "title": "Foxtale", "author": "Playtable", "id": "foxtale", "version": "1.0.0", "made_by": "We the Indies", "game": game}
        (root / ".wti_meta.json").write_text(json.dumps(document), encoding="utf-8")
        return root

    def test_the_document_is_read_and_an_older_disc_says_nothing_about_cloud_saves(self, tmp_path: Path) -> None:
        base = {"launch_options": [], "has_mod_tool": False, "has_bonus": False, "mac_build": False, "linux_build": False, "online_updates": True, "menu_language": "English"}
        old = disc_meta.read(self._disc(tmp_path, base))
        assert old is not None and old.game is not None
        assert old.game.cloud_saves is None and old.game.soundtrack is None
        new = disc_meta.read(self._disc(tmp_path / "b", {**base, "cloud_saves": True, "soundtrack_cd": {"title": "Low Tide", "tracks": 12}}))
        assert new is not None and new.game is not None
        assert new.game.cloud_saves is True
        assert new.game.soundtrack == disc_meta.SoundtrackCd(title="Low Tide", tracks=12)
        # Anything but a real true or false is "the disc does not say".
        odd = disc_meta.read(self._disc(tmp_path / "c", {**base, "cloud_saves": "yes", "soundtrack_cd": "a CD"}))
        assert odd is not None and odd.game is not None
        assert odd.game.cloud_saves is None and odd.game.soundtrack is None

    def test_the_lines_say_what_the_disc_has_and_never_what_it_lacks(self) -> None:
        none = strings.game_carries(online_updates=False, cloud_saves=False, soundtrack=None, has_key=False)
        assert none == []
        updates_only = strings.game_carries(online_updates=True, cloud_saves=False, soundtrack=None, has_key=False)
        assert updates_only == [strings.DISC_GETS_UPDATES]
        assert all("off" not in line.lower() and "Cloud" not in line for line in updates_only)
        everything = strings.game_carries(online_updates=True, cloud_saves=True, soundtrack=("Low Tide", 12), has_key=True)
        assert everything == [strings.DISC_GETS_UPDATES, strings.DISC_HAS_CLOUD_SAVES, "A soundtrack CD comes in the same case: Low Tide, 12 tracks.", strings.KEY_ON_LABEL]
        # Cloud saves rides with updates: a disc that says it without updates is not believed.
        assert strings.game_carries(online_updates=False, cloud_saves=True, soundtrack=None, has_key=False) == []
        # A disc from before the field says nothing about Cloud saves.
        assert strings.game_carries(online_updates=True, cloud_saves=None, soundtrack=None, has_key=False) == [strings.DISC_GETS_UPDATES]

    def test_a_soundtrack_cd_with_no_name_or_count_still_reads_as_a_sentence(self) -> None:
        assert strings.soundtrack_line("", 0) == "A soundtrack CD comes in the same case."
        assert strings.soundtrack_line("Low Tide", 1) == "A soundtrack CD comes in the same case: Low Tide, 1 track."

    def test_the_key_line_is_not_a_lock_and_names_the_page(self) -> None:
        assert "not a lock" in strings.KEY_ON_LABEL and "wetheindies.com/editions" in strings.KEY_ON_LABEL

    def test_the_game_view_shows_them_and_hides_the_block_when_there_is_nothing(self, qt_app, tmp_path: Path) -> None:
        from wti_player.ui.views import GameView

        base = {"launch_options": [], "has_mod_tool": False, "has_bonus": False, "mac_build": False, "linux_build": False, "menu_language": "English"}
        view = GameView()
        root = self._disc(tmp_path, {**base, "online_updates": True, "cloud_saves": True, "soundtrack_cd": {"title": "Low Tide", "tracks": 2}})
        view.show_disc(DiscProfile(kind=DiscKind.GAME_DISC, root=root, ours=True, meta=disc_meta.read(root)))
        assert not view.carries.isHidden()
        assert view.carries.text().split("\n") == [strings.DISC_GETS_UPDATES, strings.DISC_HAS_CLOUD_SAVES, "A soundtrack CD comes in the same case: Low Tide, 2 tracks."]
        plain = self._disc(tmp_path / "plain", {**base, "online_updates": False, "cloud_saves": False})
        view.show_disc(DiscProfile(kind=DiscKind.GAME_DISC, root=plain, ours=True, meta=disc_meta.read(plain)))
        assert view.carries.isHidden() and view.carries.text() == ""
        # A game from someone else is told nothing of ours.
        view.show_disc(DiscProfile(kind=DiscKind.GAME_DISC, root=root, ours=False, meta=disc_meta.read(root)))
        assert view.carries.isHidden()
