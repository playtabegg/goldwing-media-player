"""The window, driven by a fake engine and a fake drive.

Qt runs offscreen here, so these are ordinary fast tests: no video card, no
disc, no libvlc. What they pin down is the wiring — that inserting a disc
opens it, that the right panel comes up for the kind of disc it is, that a
title picked from the list is the title the engine is told to play, and that
nothing ever puts a traceback in front of a person.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication

from wti_player import strings
from wti_player.engine.base import EngineTitle, MediaKind, NavAction, PlaybackState
from wti_player.engine.fake import FakeEngine, simple_disc
from wti_player.inputs.actions import PlayerAction
from wti_player.optical.drives import DriveWatcher, FakeScanner, OpticalDrive
from wti_player.optical.reader import ImmediateReader
from wti_player.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qt_app():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture
def scanner():
    return FakeScanner([OpticalDrive(mount="E:\\", description="Disc drive (E:)")])


@pytest.fixture
def window(qt_app, scanner, monkeypatch):
    engine = FakeEngine(simple_disc())
    watcher = DriveWatcher(scanner)
    # Reading on the spot, so a test can assert straight after opening. The
    # Player itself reads on a worker; that seam is what makes this possible.
    made = MainWindow(
        engine, watcher=watcher, gamepad=_NoGamepad(), reader=ImmediateReader()
    )
    yield made
    made.close()


class _NoGamepad:
    available = False

    def read(self):
        return None


class TestOpening:
    def test_it_starts_on_the_welcome_panel(self, window) -> None:
        assert window.stack.currentWidget() is window.welcome
        assert not window.transport.isVisible()

    def test_a_blu_ray_folder_opens_into_the_player(self, window, menu_disc) -> None:
        window.open_path(menu_disc)

        assert window.stack.currentWidget() is window.player_page
        assert window.engine.opened
        assert window.engine.opened[-1].kind is MediaKind.BLU_RAY
        assert window.engine.window_handle is not None

    def test_a_data_disc_opens_into_the_browser(self, window, data_disc) -> None:
        window.open_path(data_disc)

        assert window.stack.currentWidget() is window.browser
        assert not window.engine.opened  # nothing to play, nothing opened

    def test_a_game_disc_opens_the_game_screen(self, window, game_disc) -> None:
        window.open_path(game_disc)
        assert window.stack.currentWidget() is window.game
        # The window itself is not shown in this suite; isHidden is the local flag.
        assert not window.game.menu_button.isHidden()
        assert not window.top_bar.home_button.isHidden()

    def test_someone_elses_game_does_not_offer_our_menu(self, window, tmp_path) -> None:
        (tmp_path / "autorun.inf").write_text("[autorun]\nopen=setup.exe\n", encoding="ascii")
        (tmp_path / "setup.exe").write_bytes(b"MZ")
        window.open_path(tmp_path)
        assert window.stack.currentWidget() is window.game
        assert window.game.menu_button.isHidden()
        assert "someone else" in window.game.body.text().lower()

    def test_home_from_a_disc_returns_to_the_welcome_screen(self, window, game_disc) -> None:
        window.open_path(game_disc)
        window.top_bar.go_home.emit()
        assert window.stack.currentWidget() is window.welcome
        assert window.top_bar.home_button.isHidden()

    def test_an_audio_cd_opens_the_track_list_and_starts_track_one(
        self, window, tmp_path
    ) -> None:
        for track in range(1, 4):
            (tmp_path / f"Track{track:02d}.cda").write_bytes(b"RIFF")
        window.open_path(tmp_path, label="MUSOPEN")

        assert window.stack.currentWidget() is window.audio_cd
        assert window.engine.opened[-1].kind is MediaKind.AUDIO_CD

    def test_an_empty_drive_stays_on_the_welcome_panel(self, window, tmp_path) -> None:
        window.open_path(tmp_path)
        assert window.stack.currentWidget() is window.welcome
        assert not window.engine.opened


class TestInsertion:
    def test_a_disc_going_in_opens_it(self, window, scanner, menu_disc, monkeypatch) -> None:
        opened: list = []
        monkeypatch.setattr(window, "open_path", lambda path, **kw: opened.append(path))

        scanner.insert("E:\\", label="WTI_MENU_TEST")
        window.poll_drives()

        assert opened == [menu_disc.__class__("E:\\")]

    def test_ejecting_the_disc_that_is_playing_returns_to_welcome(
        self, window, scanner, menu_disc
    ) -> None:
        window.open_path(menu_disc)
        assert window.stack.currentWidget() is window.player_page

        # The watcher reports an eject for the drive whose root is playing.
        window.profile = window.profile.__class__(
            kind=window.profile.kind, root=menu_disc.__class__("E:\\")
        )
        scanner.insert("E:\\")
        window.poll_drives()
        scanner.eject("E:\\")
        window.poll_drives()

        assert window.stack.currentWidget() is window.welcome

    def test_auto_play_can_be_turned_off(self, qt_app, scanner) -> None:
        engine = FakeEngine(simple_disc())
        made = MainWindow(
            engine,
            watcher=DriveWatcher(scanner),
            gamepad=_NoGamepad(),
            reader=ImmediateReader(),
            auto_play=False,
        )
        try:
            scanner.insert("E:\\", label="ANYTHING")
            made.poll_drives()
            assert not engine.opened
        finally:
            made.close()


class TestPlaying:
    def test_the_title_list_switches_to_the_engine_numbering(
        self, window, menu_disc
    ) -> None:
        window.open_path(menu_disc)
        window.engine.disc.titles = [
            EngineTitle(0, "Top Menu", 0, is_menu=True, is_interactive=True),
            EngineTitle(1, "Feature", 90_000, chapters=3),
        ]
        window._refresh_titles()

        rows = window.titles._list
        assert rows.count() == 2
        # The number stored against a row is the one select_title takes.
        assert rows.item(1).data(0x0100) == 1

    def test_playing_a_title_from_the_list_plays_that_title(
        self, window, menu_disc
    ) -> None:
        window.open_path(menu_disc)
        window.play_title(1)
        assert window.engine.current_title == 1

    def test_play_main_feature_asks_the_engine_which_one_that_is(
        self, window, menu_disc
    ) -> None:
        window.open_path(menu_disc)
        window.engine.main_feature_title = lambda: 1  # type: ignore[method-assign]
        window.play_main_feature()
        assert window.engine.current_title == 1

    def test_with_nothing_playable_it_says_so_rather_than_doing_nothing(
        self, window, menu_disc
    ) -> None:
        window.open_path(menu_disc)
        window.profile = window.profile.__class__(
            kind=window.profile.kind, root=window.profile.root
        )
        window.engine.main_feature_title = lambda: None  # type: ignore[method-assign]
        window.play_main_feature()
        assert not window.banner.isHidden()
        assert strings.NOTHING_TO_PLAY in window.banner._label.text()


class TestActions:
    def test_navigation_reaches_the_engine(self, window, menu_disc) -> None:
        window.open_path(menu_disc)
        window.do(PlayerAction.DOWN)
        window.do(PlayerAction.ACTIVATE)
        assert window.engine.navigations == [NavAction.DOWN, NavAction.ACTIVATE]

    def test_skipping_moves_the_position(self, window, menu_disc) -> None:
        window.open_path(menu_disc)
        window.engine.select_title(1)
        window.engine.seek(30_000)

        window.do(PlayerAction.SKIP_FORWARD)
        assert window.engine.position_ms == 40_000
        window.do(PlayerAction.SKIP_BACK)
        assert window.engine.position_ms == 30_000

    def test_next_chapter_goes_to_the_next_mark(self, window, menu_disc) -> None:
        window.open_path(menu_disc)
        window.engine.select_title(1)  # chapters at 0, 1/3, 2/3 of 90 minutes

        window.do(PlayerAction.NEXT_CHAPTER)
        assert window.engine.position_ms == window.engine.chapters()[1]

    def test_previous_chapter_returns_to_the_start_of_this_one_first(
        self, window, menu_disc
    ) -> None:
        window.open_path(menu_disc)
        window.engine.select_title(1)
        marks = window.engine.chapters()
        window.engine.seek(marks[1] + 30_000)

        window.do(PlayerAction.PREVIOUS_CHAPTER)
        assert window.engine.position_ms == marks[1]
        window.do(PlayerAction.PREVIOUS_CHAPTER)
        assert window.engine.position_ms == marks[0]

    def test_volume_is_clamped_at_both_ends(self, window) -> None:
        for _ in range(30):
            window.do(PlayerAction.VOLUME_UP)
        assert window.engine.volume == 100
        for _ in range(40):
            window.do(PlayerAction.VOLUME_DOWN)
        assert window.engine.volume == 0


class TestNeverATraceback:
    def test_an_engine_error_becomes_a_sentence(self, window) -> None:
        window._on_engine_event(_error_event("The disc is unreadable."))
        assert not window.banner.isHidden()
        assert window.banner._label.text() == "The disc is unreadable."

    def test_an_error_with_no_message_still_says_something_useful(self, window) -> None:
        window._on_engine_event(_error_event(""))
        assert strings.CANNOT_READ_DISC in window.banner._label.text()

    def test_a_disc_that_cannot_be_read_does_not_leave_a_half_open_player(
        self, window, tmp_path
    ) -> None:
        window.open_path(tmp_path / "not-a-thing")
        assert window.stack.currentWidget() is window.welcome
        assert not window.banner.isHidden()

    def test_a_blu_ray_with_a_damaged_index_is_refused_before_the_engine_sees_it(
        self, window, menu_disc, tmp_path
    ) -> None:
        import shutil

        broken = tmp_path / "broken"
        shutil.copytree(menu_disc, broken)
        clpi = broken / "BDMV" / "CLIPINF" / "00000.clpi"
        data = bytearray(clpi.read_bytes())
        cpi_start = int.from_bytes(data[16:20], "big")
        data[cpi_start : cpi_start + 4] = b"\x00\x00\x00\x00"
        clpi.write_bytes(bytes(data))

        window.open_path(broken)
        assert "seek index" in window.banner._label.text()


def _error_event(message: str):
    from wti_player.engine.base import EngineEvent

    return EngineEvent(state=PlaybackState.ERROR, message=message)
