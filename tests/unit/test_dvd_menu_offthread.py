"""P3 + P4 (28 Aug 2026): the menu is read off the interface's thread, and a
dead submenu does not strand the screen.

Pressing M used to call ``menu_reader.read`` on the GUI thread: 3.9 s frozen
on a warm cache, about 18 s off a drive. Now ``show_dvd_menu`` hands the read
to the reader's ``run`` and ``_menu_read`` puts the menu up when it lands;
a stale answer (the user left, ejected, or asked again) is dropped.
"""

from __future__ import annotations

import pytest

from wti_player.dvd.navigator import Action
from wti_player.engine.fake import FakeEngine, simple_disc
from wti_player.inputs.actions import PlayerAction
from wti_player.optical.drives import DriveWatcher, FakeScanner, OpticalDrive
from wti_player.optical.reader import ImmediateReader
from wti_player.ui.main_window import MainWindow
from wti_player.ui.transport import Mode

pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture
def menu_dvd(generated_dir):
    path = generated_dir / "dvd_menu_disc"
    if not (path / "VIDEO_TS" / "VTS_01_0.VOB").is_file():
        pytest.skip("run: python tools/make_fixtures.py")
    return path


class _NoPad:
    available = False

    def read(self):
        return None


class HeldReader(ImmediateReader):
    """Identifies discs on the spot, but holds ``run`` work until released."""

    def __init__(self) -> None:
        super().__init__()
        self.held: list[tuple[str, object, object]] = []

    def run(self, label, work, done) -> None:
        self.cancelled = False
        self.held.append((label, work, done))

    def release(self, index: int = -1) -> None:
        _label, work, done = self.held.pop(index)
        done(work())


def make_window(qapp, menu_dvd, reader):
    made = MainWindow(
        FakeEngine(simple_disc()),
        watcher=DriveWatcher(FakeScanner([OpticalDrive(mount="E:\\", description="Drive")])),
        gamepad=_NoPad(),
        reader=reader,
        auto_play=False,
    )
    made.open_path(menu_dvd)
    return made


class TestOffTheThread:
    def test_the_menu_is_read_through_the_reader_and_the_transport_says_so(self, qapp, menu_dvd):
        reader = HeldReader()
        window = make_window(qapp, menu_dvd, reader)
        try:
            window.do(PlayerAction.TOP_MENU)
            assert window._dvd_menu is None, "the menu came up before the read finished"
            assert window.transport._mode is Mode.READING
            assert reader.held and reader.held[0][0] == "dvd menu"
            reader.release()
            assert window._dvd_menu is not None
            assert window.transport._mode is Mode.MENU
            assert window.stack.currentWidget() is window.menu_surface
        finally:
            window.close()

    def test_a_read_that_lands_after_the_viewer_left_is_dropped(self, qapp, menu_dvd):
        reader = HeldReader()
        window = make_window(qapp, menu_dvd, reader)
        try:
            window.do(PlayerAction.TOP_MENU)
            window.leave_dvd_menu(resume=False)
            reader.release()  # the stale answer arrives now
            assert window._dvd_menu is None
            assert window.stack.currentWidget() is not window.menu_surface
        finally:
            window.close()

    def test_asking_twice_keeps_only_the_second_answer(self, qapp, menu_dvd):
        reader = HeldReader()
        window = make_window(qapp, menu_dvd, reader)
        try:
            window.do(PlayerAction.TOP_MENU)
            window.do(PlayerAction.TOP_MENU)
            assert len(reader.held) == 2
            reader.release(0)  # the first, now stale
            assert window._dvd_menu is None
            reader.release(0)  # the second
            assert window._dvd_menu is not None
        finally:
            window.close()

    def test_ejecting_cancels_the_read(self, qapp, menu_dvd):
        reader = HeldReader()
        window = make_window(qapp, menu_dvd, reader)
        try:
            window.do(PlayerAction.TOP_MENU)
            window.eject()
            assert reader.cancelled
        finally:
            window.close()

    def test_a_disc_with_no_menu_says_so_and_puts_the_transport_back(self, qapp, menu_dvd):
        reader = HeldReader()
        window = make_window(qapp, menu_dvd, reader)
        try:
            window.do(PlayerAction.TOP_MENU)
            _label, _work, done = reader.held.pop()
            done(None)  # the reader found nothing
            assert window._dvd_menu is None
            assert window.transport._mode is Mode.PLAYBACK
        finally:
            window.close()


class TestNoDeadSubmenu:
    def test_the_title_set_reaches_the_navigator(self, qapp, menu_dvd):
        window = make_window(qapp, menu_dvd, ImmediateReader())
        try:
            window.show_dvd_menu(title_set=1)
            assert window._dvd_menu is not None
            assert window._dvd_menu.menu.navigator.title_set == 1
        finally:
            window.close()

    def test_a_menu_button_naming_a_title_set_passes_it_on(self, qapp, menu_dvd, monkeypatch):
        window = make_window(qapp, menu_dvd, ImmediateReader())
        seen: dict[str, object] = {}
        real = window.show_dvd_menu

        def spy(*, kind="", title_set=None):
            seen["kind"] = kind
            seen["title_set"] = title_set
            return real(kind=kind, title_set=title_set)

        monkeypatch.setattr(window, "show_dvd_menu", spy)
        try:
            window._carry_out(Action(kind="show-menu", menu="root", title_set=1))
            assert seen == {"kind": "root", "title_set": 1}
        finally:
            window.close()

    def test_leaving_restores_the_player_page_even_with_no_session(self, qapp, menu_dvd):
        window = make_window(qapp, menu_dvd, ImmediateReader())
        try:
            window.do(PlayerAction.TOP_MENU)
            assert window.stack.currentWidget() is window.menu_surface
            # The dead-submenu shape: the session is gone, the surface is not.
            window._dvd_menu.stop()
            window._dvd_menu = None
            window.leave_dvd_menu(resume=False)
            assert window.stack.currentWidget() is window.player_page
            assert window.transport._mode is Mode.PLAYBACK
        finally:
            window.close()

    def test_leaving_when_nothing_is_up_changes_nothing(self, qapp, menu_dvd):
        window = make_window(qapp, menu_dvd, ImmediateReader())
        try:
            before = window.stack.currentWidget()
            window.leave_dvd_menu(resume=False)
            assert window.stack.currentWidget() is before
        finally:
            window.close()


class TestAMenuThatForcesAMenu:
    def test_is_declined_rather_than_looped(self, qapp, menu_dvd, monkeypatch):
        from wti_player.dvd import menu as menu_reader

        real = menu_reader.read

        def forcing(root, *, title_set=1, kind=""):
            found = real(root, title_set=title_set, kind=kind)
            if found is None:
                return None
            return menu_reader.DiscMenu(
                navigator=found.navigator,
                subpicture=found.subpicture,
                palette=found.palette,
                kind=found.kind,
                vob=found.vob,
                first_sector=found.first_sector,
                entry_action=Action(kind="show-menu", menu="root"),
            )

        monkeypatch.setattr(menu_reader, "read", forcing)
        window = make_window(qapp, menu_dvd, ImmediateReader())
        try:
            window.do(PlayerAction.TOP_MENU)  # would recurse forever without the guard
            assert window._dvd_menu is not None
            assert window.stack.currentWidget() is window.menu_surface
        finally:
            window.close()

    def test_the_old_menu_stays_up_until_the_new_one_is_read(self, qapp, menu_dvd):
        reader = HeldReader()
        window = make_window(qapp, menu_dvd, reader)
        try:
            window.do(PlayerAction.TOP_MENU)
            reader.release()
            first = window._dvd_menu
            assert first is not None
            window.show_dvd_menu(kind="root")  # a second menu, read held
            assert window._dvd_menu is first, "the first menu was torn down before the second was read"
            reader.release()
            assert window._dvd_menu is not None and window._dvd_menu is not first
        finally:
            window.close()
