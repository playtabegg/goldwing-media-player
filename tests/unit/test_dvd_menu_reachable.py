"""The DVD menu, reached the way a person reaches it.

Every other test in this suite calls `show_dvd_menu()` directly, and all of
them passed while the feature was unreachable: `TOP_MENU` is a member of the
navigation action set, so the branch that opened a menu sat below a branch
that always matched first, and nothing could call it.

So these tests start from the input — a key, a button, a menu item — and
assert on what happens. A test that reaches past the routing is a test that
cannot find a routing bug.
"""

from __future__ import annotations

import pytest

from wti_player.dvd.navigator import Action
from wti_player.engine.base import PlaybackState
from wti_player.engine.fake import FakeEngine, simple_disc
from wti_player.inputs.actions import PlayerAction
from wti_player.inputs.keymap import action_for
from wti_player.optical.drives import DriveWatcher, FakeScanner, OpticalDrive
from wti_player.optical.reader import ImmediateReader
from wti_player.ui.main_window import MainWindow
from wti_player.ui.transport import Mode

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent


@pytest.fixture
def menu_dvd(generated_dir):
    path = generated_dir / "dvd_menu_disc"
    if not (path / "VIDEO_TS" / "VTS_01_0.VOB").is_file():
        pytest.skip("run: python tools/make_fixtures.py")
    return path


@pytest.fixture
def window(qapp, menu_dvd):
    made = MainWindow(
        FakeEngine(simple_disc()),
        watcher=DriveWatcher(FakeScanner([OpticalDrive(mount="E:\\", description="Drive")])),
        gamepad=_NoPad(),
        reader=ImmediateReader(),
        auto_play=False,
    )
    made.open_path(menu_dvd)
    yield made
    made.close()


class _NoPad:
    available = False

    def read(self):
        return None


def press(window, key: int) -> None:
    """A real key event, through the real handler."""
    window.keyPressEvent(
        QKeyEvent(
            QKeyEvent.Type.KeyPress,
            key,
            Qt.KeyboardModifier.NoModifier,
        )
    )


class TestGettingIntoOne:
    def test_the_disc_reads_as_a_dvd_with_a_menu(self, window):
        assert window.profile is not None
        assert window.profile.has_menu

    def test_the_m_key_opens_it(self, window):
        press(window, Qt.Key.Key_M)
        assert window._dvd_menu is not None, "the menu key did nothing"

    def test_the_action_opens_it(self, window):
        window.do(PlayerAction.TOP_MENU)
        assert window._dvd_menu is not None

    def test_the_popup_key_opens_it_too(self, window):
        window.do(PlayerAction.POPUP_MENU)
        assert window._dvd_menu is not None

    def test_the_transport_button_opens_it(self, window):
        window.transport.top_menu.emit()
        assert window._dvd_menu is not None

    def test_the_title_list_button_opens_it(self, window):
        window.titles.open_menu.emit()
        assert window._dvd_menu is not None

    def test_the_keymap_really_maps_m_to_the_menu(self):
        """If this changes, every test above still passes and nothing works."""
        assert action_for(int(Qt.Key.Key_M), in_menu=False) is PlayerAction.TOP_MENU

    def test_the_transport_shows_its_menu_face(self, window):
        window.do(PlayerAction.TOP_MENU)
        assert window.transport._mode is Mode.MENU

    def test_the_surface_is_what_is_on_screen(self, window):
        window.do(PlayerAction.TOP_MENU)
        assert window.stack.currentWidget() is window.menu_surface


class TestMovingAround:
    def test_the_arrows_move_the_highlight(self, window):
        window.do(PlayerAction.TOP_MENU)
        before = window._dvd_menu.menu.navigator.selected
        press(window, Qt.Key.Key_Down)
        assert window._dvd_menu.menu.navigator.selected != before

    def test_the_pointer_moves_it_too(self, window):
        window.do(PlayerAction.TOP_MENU)
        window.menu_surface.cursor_moved.emit(300, 350)
        assert window._dvd_menu.menu.navigator.selected == 2


class TestGettingOut:
    def test_the_menu_key_again_leaves(self, window):
        window.do(PlayerAction.TOP_MENU)
        press(window, Qt.Key.Key_M)
        assert window._dvd_menu is None

    def test_escape_leaves(self, window):
        window.do(PlayerAction.TOP_MENU)
        window.do(PlayerAction.LEAVE_FULLSCREEN)
        assert window._dvd_menu is None

    def test_escape_in_full_screen_leaves_both(self, window):
        """One press used to take the menu and leave a chrome-less window."""
        window.toggle_fullscreen()
        window.do(PlayerAction.TOP_MENU)
        window.do(PlayerAction.LEAVE_FULLSCREEN)
        assert window._dvd_menu is None
        assert not window.isFullScreen()

    def test_leaving_gives_the_player_page_back(self, window):
        window.do(PlayerAction.TOP_MENU)
        window.leave_dvd_menu()
        assert window.stack.currentWidget() is window.player_page
        assert window.transport._mode is Mode.PLAYBACK


class TestPressingAButton:
    def test_play_starts_a_title_that_exists(self, window):
        """A DVD's titles are 1-based. Off by one here plays nothing."""
        window.do(PlayerAction.TOP_MENU)
        window._carry_out(Action(kind="play-title", title=1))
        assert window._dvd_menu is None
        assert window.engine.opened, "nothing was opened"
        assert not window.banner.message(), "a button that works must not report a problem"

    def test_a_title_that_does_not_exist_says_so_and_stops(self, window):
        window.do(PlayerAction.TOP_MENU)
        window._carry_out(Action(kind="play-title", title=97))
        assert window.banner.message()

    def test_a_failed_play_does_not_arm_a_seek(self, window):
        """A stale seek makes the NEXT thing somebody plays start partway in."""
        window.do(PlayerAction.TOP_MENU)
        window._carry_out(Action(kind="play-chapter", title=97, chapter=4))
        assert window._pending_seek_ms == 0

    def test_a_command_we_do_not_follow_is_said_out_loud(self, window):
        window.do(PlayerAction.TOP_MENU)
        window._carry_out(Action(kind="unsupported", reason="SetSTN"))
        assert "SetSTN" in window.banner.message()

    def test_resume_leaves_the_menu(self, window):
        window.do(PlayerAction.TOP_MENU)
        window._carry_out(Action(kind="resume"))
        assert window._dvd_menu is None


class TestASubmenu:
    def test_it_does_not_forget_where_the_film_was(self, window):
        """The first menu remembers. A menu over a menu must not overwrite it."""
        window.play_title(1)
        window.engine._position = 2_700_000
        window.do(PlayerAction.TOP_MENU)
        assert window._resume_ms == 2_700_000

        window._carry_out(Action(kind="show-menu", menu="root"))
        assert window._resume_ms == 2_700_000, "the submenu clobbered the resume point"

    def test_it_does_not_leave_the_old_session_running(self, window):
        window.do(PlayerAction.TOP_MENU)
        first = window._dvd_menu
        window._carry_out(Action(kind="show-menu", menu="root"))
        assert first is not window._dvd_menu
        assert not first.active, "the first menu was left holding the engine"


class TestWhenSomethingGoesWrong:
    def test_a_disc_pulled_out_is_not_called_encrypted(self, window, tmp_path):
        """It used to tell people their own disc was copy-protected."""
        from wti_player.engine.base import EngineEvent
        from wti_player.optical.identify import DiscKind, DiscProfile

        window.profile = DiscProfile(kind=DiscKind.DVD_VIDEO, root=tmp_path / "gone")
        window.engine._position = 60_000
        assert not window._looks_like_css()

        window._on_engine_event(EngineEvent(state=PlaybackState.ERROR, message="It is gone."))
        said = window.banner.message()
        assert "It is gone." in said, said
        assert "encrypted" not in said.lower()

    def test_a_disc_that_never_played_still_reads_as_encryption(self, window, menu_dvd):
        from wti_player.optical.identify import DiscKind, DiscProfile

        window.profile = DiscProfile(kind=DiscKind.DVD_VIDEO, root=menu_dvd)
        window.engine._position = 0
        assert window._looks_like_css()

    def test_closing_stops_every_timer(self, window):
        window.close()
        for name in ("_drive_timer", "_tick", "_chrome_timer", "_pad_timer"):
            timer = getattr(window, name, None)
            if timer is not None:
                assert not timer.isActive(), f"{name} outlived the engine"
