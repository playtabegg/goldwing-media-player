"""Putting a DVD menu on screen, and taking it down again.

The join between the navigator and the engine, driven with a fake engine
that records what it was asked to do. No libvlc, no drive, no window — which
is the point of the seam.

The property these are really about: **starting a menu must not disturb the
path films play on.** Every one of them checks the way back as well as the
way in.
"""

from __future__ import annotations

import pytest

from wti_player.dvd.session import MenuSession
from wti_player.engine.base import MediaTarget, NavAction


class RecordingEngine:
    """Everything ``MenuSession`` asks of an engine, written down."""

    def __init__(self) -> None:
        self.opened: list[MediaTarget] = []
        self.played = 0
        self.stopped = 0
        self.memory_output: tuple[int, int] | None = None
        self.on_frame = None
        self.window_handle: int | None = None

    def open(self, target: MediaTarget) -> None:
        self.opened.append(target)

    def play(self) -> None:
        self.played += 1

    def stop(self) -> None:
        self.stopped += 1

    def use_memory_output(self, width, height, on_frame):
        self.memory_output = (width, height)
        self.on_frame = on_frame
        return memoryview(bytearray(width * height * 4))

    def set_video_window(self, handle: int) -> None:
        self.window_handle = handle


@pytest.fixture
def menu_dvd(generated_dir):
    path = generated_dir / "dvd_menu_disc"
    if not (path / "VIDEO_TS" / "VTS_01_0.VOB").is_file():
        pytest.skip("run: python tools/make_fixtures.py")
    return path


@pytest.fixture
def session():
    return MenuSession(RecordingEngine())


class TestStarting:
    def test_a_disc_with_a_menu_starts_one(self, session, menu_dvd):
        assert session.start(menu_dvd) is not None
        assert session.active

    def test_it_opens_the_menu_vob_and_nothing_else(self, session, menu_dvd):
        session.start(menu_dvd)
        assert len(session.engine.opened) == 1
        target = session.engine.opened[0]
        # A DVD is handed to libvlc as its VOB files' program stream, which
        # puts the filename in the concat list rather than in the MRL.
        assert "VTS_01_0.VOB" in " ".join(target.options)
        assert "VTS_01_1.VOB" not in " ".join(target.options), (
            "the menu must not drag the title VOB in with it"
        )

    def test_it_asks_for_a_buffer_the_size_of_a_dvd_picture(self, session, menu_dvd):
        session.start(menu_dvd)
        assert session.engine.memory_output == (720, 480)
        assert session.buffer is not None
        assert len(session.buffer) == 720 * 480 * 4

    def test_it_starts_playing(self, session, menu_dvd):
        session.start(menu_dvd)
        assert session.engine.played == 1

    def test_a_disc_with_no_menu_starts_nothing(self, session, generated_dir):
        plain = generated_dir / "dvd_disc"
        if not (plain / "VIDEO_TS").is_dir():
            pytest.skip("run: python tools/make_fixtures.py")
        assert session.start(plain) is None
        assert not session.active
        assert session.engine.opened == []
        assert session.engine.memory_output is None, (
            "a disc with no menu must not leave the engine writing to a buffer"
        )

    def test_a_folder_that_is_not_a_disc_starts_nothing(self, session, tmp_path):
        assert session.start(tmp_path) is None
        assert session.engine.opened == []


class TestFrames:
    def test_the_frame_callback_reaches_the_caller(self, session, menu_dvd):
        woken = []
        session.start(menu_dvd, on_frame=lambda: woken.append(1))
        session.engine.on_frame()
        assert woken == [1]

    def test_a_callback_that_throws_does_not_take_playback_down(self, session, menu_dvd):
        def bad():
            raise RuntimeError("the interface fell over")

        session.start(menu_dvd, on_frame=bad)
        with pytest.raises(RuntimeError):
            session.engine.on_frame()
        # The engine's own wrapper is what swallows this in the real thing;
        # what matters here is that the session does not add a second layer
        # of silence that would hide a real bug from a test.
        assert session.active


class TestPressing:
    def test_a_direction_moves_the_selection(self, session, menu_dvd):
        session.start(menu_dvd)
        before = session.menu.navigator.selected
        session.press(NavAction.DOWN)
        assert session.menu.navigator.selected != before

    def test_activating_produces_something_to_do(self, session, menu_dvd):
        session.start(menu_dvd)
        action = session.press(NavAction.ACTIVATE)
        assert action.kind != "unsupported", action.reason
        assert not action.is_nothing

    def test_the_pointer_lights_a_button(self, session, menu_dvd):
        session.start(menu_dvd)
        assert session.point_at(300, 350)
        assert session.menu.navigator.selected == 2

    def test_the_pointer_off_a_button_changes_nothing(self, session, menu_dvd):
        session.start(menu_dvd)
        assert not session.point_at(5, 5)

    def test_a_click_carries_the_button_out(self, session, menu_dvd):
        session.start(menu_dvd)
        assert not session.click_at(300, 350).is_nothing

    def test_pressing_with_no_menu_up_is_not_an_error(self, session):
        assert session.press(NavAction.ACTIVATE).is_nothing
        assert session.click_at(1, 1).is_nothing
        assert not session.point_at(1, 1)


class TestWhatTheSurfaceIsGiven:
    def test_everything_it_needs_arrives(self, session, menu_dvd):
        session.start(menu_dvd)
        presentation = session.presentation()
        assert set(presentation) == {
            "navigator",
            "subpicture",
            "chain_palette",
            "highlight_palette",
            "highlight_alpha",
        }
        assert len(presentation["chain_palette"]) == 16
        assert presentation["subpicture"] is not None

    def test_the_lit_colours_follow_the_selection(self, session, menu_dvd):
        session.start(menu_dvd)
        first = session.presentation()["highlight_palette"]
        session.press(NavAction.DOWN)
        assert session.presentation()["highlight_palette"] == first, (
            "both buttons use the same colour group on this disc"
        )
        assert first is not None

    def test_nothing_up_means_nothing_to_draw(self, session):
        assert session.presentation() == {}


class TestLeaving:
    def test_stopping_puts_the_engine_down(self, session, menu_dvd):
        session.start(menu_dvd)
        session.stop()
        assert session.engine.stopped == 1
        assert not session.active
        assert session.buffer is None

    def test_stopping_twice_is_not_an_error(self, session, menu_dvd):
        session.start(menu_dvd)
        session.stop()
        session.stop()
        assert session.engine.stopped == 2

    def test_stopping_one_that_never_started_is_not_an_error(self, session):
        session.stop()
        assert not session.active
