"""What happens when somebody actually uses the Player.

The unit tests next door check wiring: this title reaches that engine call.
These check the ten minutes after that — press Stop then Play, let a film run
out, press the menu key on a disc with no menu, double-click a README.

Every test here is a bug somebody found by driving the Player rather than by
reading it, which is the only way most of them could have been found. They
are grouped by what a person was trying to do at the time.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication

from wti_player import strings
from wti_player.engine.base import PlaybackState
from wti_player.engine.fake import FakeDisc, FakeEngine, simple_disc
from wti_player.inputs.actions import PlayerAction
from wti_player.inputs.keymap import KEY_T, action_for
from wti_player.optical.drives import DriveWatcher, FakeScanner, OpticalDrive
from wti_player.optical.reader import ImmediateReader
from wti_player.ui.main_window import MainWindow
from wti_player.ui.transport import Mode


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


class _NoGamepad:
    available = False

    def read(self):
        return None


def _pump(app) -> None:
    """Let the queued engine events land.

    The window takes every engine event across a queued connection,
    because libvlc raises them on its own threads. Nothing arrives
    until the loop turns, so a test that fakes an event has to turn it.
    """
    for _ in range(4):
        app.processEvents()


def _window(qt_app, engine, reader=None):
    watcher = DriveWatcher(FakeScanner([OpticalDrive(mount="E:\\", description="Drive")]))
    return MainWindow(
        engine,
        watcher=watcher,
        gamepad=_NoGamepad(),
        reader=reader or ImmediateReader(),
    )


@pytest.fixture
def window(qt_app):
    made = _window(qt_app, FakeEngine(simple_disc()))
    yield made
    made.close()


class TestTheTransport:
    def test_play_after_stop_starts_it_again(self, window, feature_disc) -> None:
        """The one that shipped: Stop, then Play, and nothing ever happens.

        ``libvlc_media_player_pause`` is a no-op on a stopped player, so the
        Play button was wired to a call that does nothing in the one state
        somebody presses it in.
        """
        window.open_path(feature_disc)
        window.do(PlayerAction.STOP)
        assert window.engine.state is PlaybackState.STOPPED

        window.do(PlayerAction.PLAY_PAUSE)

        assert window.engine.state is PlaybackState.PLAYING

    def test_play_after_the_film_ends_starts_it_again(self, window, feature_disc) -> None:
        """A finished title has been released, so resuming it is not enough."""
        window.open_path(feature_disc)
        opens = len(window.engine.opened)
        window.engine.finish()

        window.do(PlayerAction.PLAY_PAUSE)

        assert window.engine.state is PlaybackState.PLAYING
        assert len(window.engine.opened) == opens + 1

    def test_pause_still_pauses(self, window, feature_disc) -> None:
        """The fix must not turn the Pause button into a restart button."""
        window.open_path(feature_disc)
        window.do(PlayerAction.PLAY_PAUSE)
        assert window.engine.state is PlaybackState.PAUSED

        window.do(PlayerAction.PLAY_PAUSE)
        assert window.engine.state is PlaybackState.PLAYING

    def test_the_skip_label_matches_what_the_button_does(self) -> None:
        from wti_player.inputs.actions import SKIP_MS

        seconds = str(SKIP_MS // 1000)
        assert seconds in strings.SKIP_FORWARD
        assert seconds in strings.SKIP_BACK


class TestSomethingRunningOut:
    def test_the_end_of_a_title_is_said_out_loud(self, qt_app, window, feature_disc) -> None:
        """Before: black picture, dead Play button, and not a word."""
        window.open_path(feature_disc)
        window.banner.hide()

        window.engine.finish()
        _pump(qt_app)

        assert not window.banner.isHidden()

    def test_a_cd_goes_on_to_the_next_track(self, qt_app, tmp_path) -> None:
        disc = _audio_cd(tmp_path)
        engine = FakeEngine(FakeDisc())
        made = _window(qt_app, engine)
        try:
            made.open_path(disc)
            assert made._track == 0

            engine.finish()
            _pump(qt_app)

            assert made._track == 1
        finally:
            made.close()


class TestAnAudioCd:
    def test_the_track_buttons_are_on_screen(self, qt_app, tmp_path) -> None:
        """A CD has no chapters, and the skip buttons hid themselves for it.

        Which left the track list as the only way to reach track two, on the
        one kind of disc where skipping tracks is the whole interaction.
        """
        made = _window(qt_app, FakeEngine(FakeDisc()))
        try:
            made.open_path(_audio_cd(tmp_path))
            assert not made.transport._next.isHidden()
        finally:
            made.close()

    def test_the_next_track_key_moves_a_track(self, qt_app, tmp_path) -> None:
        made = _window(qt_app, FakeEngine(FakeDisc()))
        try:
            made.open_path(_audio_cd(tmp_path))
            made.do(PlayerAction.NEXT_CHAPTER)
            assert made._track == 1

            made.do(PlayerAction.PREVIOUS_CHAPTER)
            assert made._track == 0
        finally:
            made.close()

    def test_it_does_not_walk_off_the_end_of_the_disc(self, qt_app, tmp_path) -> None:
        made = _window(qt_app, FakeEngine(FakeDisc()))
        try:
            made.open_path(_audio_cd(tmp_path, tracks=2))
            for _ in range(6):
                made.do(PlayerAction.NEXT_CHAPTER)
            assert made._track == 1
        finally:
            made.close()


class TestADamagedDisc:
    def test_a_disc_the_player_refuses_is_not_then_opened(self, qt_app, broken_seek_disc) -> None:
        """It said "the Player will not open it" and then opened it.

        Which is a segfault, because the thing it refuses is the thing that
        takes libbluray down.
        """
        engine = FakeEngine(simple_disc())
        made = _window(qt_app, engine)
        try:
            made.open_path(broken_seek_disc)
            assert engine.opened == []
            assert made.stack.currentWidget() is made.welcome
        finally:
            made.close()

    def test_and_the_reason_stays_on_the_screen(self, qt_app, broken_seek_disc) -> None:
        made = _window(qt_app, FakeEngine(simple_disc()))
        try:
            made.open_path(broken_seek_disc)
            assert not made.banner.isHidden()
        finally:
            made.close()


class TestFullScreen:
    def test_a_folder_of_files_will_not_fill_the_screen(self, window, data_disc) -> None:
        """There is nothing to fill it with, and no control left to press."""
        window.open_path(data_disc)
        window.toggle_fullscreen()

        assert not window.isFullScreen()
        assert not window.banner.isHidden()

    def test_an_error_is_not_hidden_with_the_chrome(self, window, feature_disc) -> None:
        """Three seconds of not moving the mouse used to take the message."""
        window.open_path(feature_disc)
        window.report("Something went wrong.")
        window.showFullScreen()

        window._hide_chrome()

        assert not window.banner.isHidden()

    def test_a_key_reaches_the_side_panel(self) -> None:
        """Full screen hides the top bar, and that was the panel's only door."""
        assert action_for(KEY_T, in_menu=False) is PlayerAction.TOGGLE_PANEL


class TestOpeningThings:
    def test_a_file_on_a_data_disc_does_not_throw_the_disc_away(
        self, window, data_disc, monkeypatch
    ) -> None:
        """Double-clicking a README used to end at the welcome screen."""
        window.open_path(data_disc)
        page = window.stack.currentWidget()
        opened: list[str] = []
        monkeypatch.setattr(
            "wti_player.ui.main_window.QDesktopServices.openUrl",
            lambda url: opened.append(url.toLocalFile()) or True,
        )

        readme = next(path for path in data_disc.rglob("*") if path.is_file())
        window.open_from_browser(readme)

        assert window.stack.currentWidget() is page
        assert opened and opened[0].endswith(readme.name)

    def test_opening_the_disc_already_playing_does_not_restart_it(
        self, window, feature_disc
    ) -> None:
        window.open_path(feature_disc)
        opens = len(window.engine.opened)

        window.open_path(feature_disc)

        assert len(window.engine.opened) == opens

    def test_the_welcome_screen_drops_a_read_still_in_flight(self, qt_app) -> None:
        """Otherwise the disc somebody just ejected comes back on its own."""
        reader = ImmediateReader()
        made = _window(qt_app, FakeEngine(simple_disc()), reader=reader)
        try:
            made.eject()
            assert reader.cancelled
        finally:
            made.close()


class TestADvd:
    def test_the_menu_key_on_a_disc_with_no_menu_says_so(self, qt_app, dvd_disc) -> None:
        """And does not say the disc is damaged, because it is not."""
        made = _window(qt_app, FakeEngine(simple_disc()))
        try:
            made.open_path(dvd_disc)
            if made.profile.has_menu:
                pytest.skip("the fixture disc has a menu")
            made.banner.hide()

            made.do(PlayerAction.TOP_MENU)

            assert made._dvd_menu is None
            assert not made.banner.isHidden()
        finally:
            made.close()

    def test_a_stop_after_an_hour_is_not_called_copy_protection(
        self, qt_app, dvd_disc
    ) -> None:
        """Asking "where is the film now" made Stop look like a scrambled disc."""
        engine = FakeEngine(simple_disc())
        made = _window(qt_app, engine)
        try:
            made.open_path(dvd_disc)
            made._playing_started = True
            made.do(PlayerAction.STOP)

            assert not made._looks_like_css()
        finally:
            made.close()


class TestMenuPreview:
    def test_preview_mode_is_not_a_menu_by_itself(self, window, feature_disc) -> None:
        """It kept the bar in its menu face for good, disc swaps included."""
        window.preview_mode = True
        window.open_path(feature_disc)

        assert not window.preview_mode
        assert window.transport.mode is not Mode.MENU


def _audio_cd(root, tracks: int = 4):
    """A folder that identifies as an audio CD: Windows' own CDFS view."""
    disc = root / "cd"
    disc.mkdir(parents=True, exist_ok=True)
    for number in range(1, tracks + 1):
        (disc / f"Track{number:02d}.cda").write_bytes(b"\x00" * 44)
    return disc
