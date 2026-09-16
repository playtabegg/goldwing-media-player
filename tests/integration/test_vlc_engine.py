"""The real engine against real discs.

These are the tests that would have caught every finding in the day-one
spike, so they run whenever a VLC runtime and the generated fixtures are
present, and skip with instructions when they are not.
"""

from __future__ import annotations

import time

import pytest

from wti_player.engine.base import MediaTarget, NavAction, PlaybackState

pytestmark = [pytest.mark.engine, pytest.mark.media]


def wait_for_playing(engine, seconds: float = 20.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if engine.state is PlaybackState.PLAYING:
            return True
        if engine.state is PlaybackState.ERROR:
            return False
        time.sleep(0.1)
    return False


def wait_until(condition, seconds: float = 15.0, step: float = 0.15) -> bool:
    """Wait for a thing to become true, rather than sleeping and hoping.

    A fixed sleep followed by an assertion is a test that passes on a fast
    machine and fails on a loaded one, and says nothing either way. How long
    libvlc takes to get a picture moving depends on the decoder, the disc and
    what else the machine is doing.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(step)
    return condition()


class TestBluRay:
    def test_opens_a_bdmv_folder_and_finds_its_titles(self, engine, feature_disc) -> None:
        engine.open(MediaTarget.blu_ray(feature_disc))
        assert wait_for_playing(engine)
        time.sleep(1.0)

        titles = engine.titles()
        assert len(titles) >= 2
        assert any(title.is_menu for title in titles)
        feature = engine.main_feature_title()
        assert feature is not None
        assert titles[feature].duration_ms > 10_000
        assert titles[feature].chapters == 3

    def test_chapters_come_back_where_the_disc_put_them(self, engine, feature_disc) -> None:
        engine.open(MediaTarget.blu_ray(feature_disc))
        assert wait_for_playing(engine)
        time.sleep(1.0)

        feature = engine.main_feature_title()
        marks = engine.chapters(feature)
        assert [round(mark / 1000) for mark in marks] == [0, 4, 8]

    def test_opens_an_iso(self, engine, generated_dir) -> None:
        image = generated_dir / "bd_feature.iso"
        if not image.is_file():
            pytest.skip("run: python tools/make_fixtures.py")

        engine.open(MediaTarget.blu_ray(image))
        assert wait_for_playing(engine)
        time.sleep(1.0)
        assert engine.titles()

    def test_a_menu_disc_reports_an_interactive_title(self, engine, menu_disc) -> None:
        engine.open(MediaTarget.blu_ray(menu_disc))
        assert wait_for_playing(engine)
        time.sleep(1.5)

        titles = engine.titles()
        assert any(title.is_menu and title.is_interactive for title in titles)

    def test_navigating_a_menu_does_not_throw(self, engine, menu_disc) -> None:
        engine.open(MediaTarget.blu_ray(menu_disc))
        assert wait_for_playing(engine)
        time.sleep(1.5)

        for action in (NavAction.DOWN, NavAction.UP, NavAction.RIGHT, NavAction.LEFT):
            engine.navigate(action)
            time.sleep(0.2)
        assert engine.state is PlaybackState.PLAYING

    def test_a_folder_that_is_not_a_disc_errors_rather_than_hanging(
        self, engine, data_disc
    ) -> None:
        engine.open(MediaTarget.blu_ray(data_disc))
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if engine.state in (PlaybackState.ERROR, PlaybackState.ENDED, PlaybackState.STOPPED):
                break
            time.sleep(0.1)
        assert engine.state is not PlaybackState.PLAYING


class TestErrorText:
    def test_a_missing_disc_is_explained_in_words_a_person_would_use(
        self, engine, tmp_path
    ) -> None:
        messages: list[str] = []
        engine.add_listener(
            lambda event: messages.append(event.message) if event.message else None
        )
        engine.open(MediaTarget.blu_ray(tmp_path / "not-here"))

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not messages:
            time.sleep(0.1)
        assert messages, "an unopenable disc must say something"
        assert "stack" not in messages[0].lower()
        assert messages[0][0].isupper()


class TestMainFeature:
    def test_first_play_is_not_mistaken_for_the_feature(self, engine, menu_disc) -> None:
        # libbluray reports First Play as a title carrying the menu clip's
        # length. On a disc whose menu is longer than its film — which every
        # test disc is — the naive "longest title" answer picks the menu.
        engine.open(MediaTarget.blu_ray(menu_disc))
        assert wait_for_playing(engine)
        time.sleep(1.5)

        titles = engine.titles()
        feature = engine.main_feature_title()
        assert feature is not None
        chosen = next(title for title in titles if title.number == feature)
        assert not chosen.is_menu
        assert not chosen.is_interactive


class TestDvd:
    """DVD playback with no DVD engine and no descrambler anywhere.

    The structure comes from our own IFO reader; the video is the VOB files,
    handed to libvlc as the single program stream they are. These tests run
    against the DVD-plugin-free plugin set, which is the point.
    """

    def test_a_dvd_title_plays_from_its_vob_files(self, engine, dvd_disc) -> None:
        from wti_player.formats import ifo

        disc = ifo.read(dvd_disc)
        title = disc.main_feature
        assert title is not None
        vobs = disc.vob_files(title)
        assert vobs

        engine.open(MediaTarget.dvd_title(vobs))
        assert wait_for_playing(engine)

        assert wait_until(lambda: engine.duration_ms > 5_000), engine.duration_ms
        assert wait_until(lambda: engine.position_ms > 0), "the clock never advanced"

    def test_seeking_to_a_chapter_lands_where_the_ifo_said(self, engine, dvd_disc) -> None:
        from wti_player.formats import ifo

        disc = ifo.read(dvd_disc)
        title = disc.main_feature
        engine.open(MediaTarget.dvd_title(disc.vob_files(title)))
        assert wait_for_playing(engine)
        time.sleep(1.5)

        second_chapter = title.chapters_ms[1]
        engine.seek(second_chapter)
        assert wait_until(
            lambda: abs(engine.position_ms - second_chapter) < 1500
        ), f"seeking to {second_chapter} landed at {engine.position_ms}"
