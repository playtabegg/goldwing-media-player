"""The engine seam: how media is named, and what the fake engine promises."""

from __future__ import annotations

from pathlib import Path

import pytest

from wti_player.engine.base import MediaKind, MediaTarget, NavAction, PlaybackState
from wti_player.engine.fake import FakeEngine, simple_disc


class TestMediaTarget:
    def test_a_blu_ray_folder_gets_the_bluray_scheme(self, tmp_path: Path) -> None:
        # The finding that cost the most to learn: with a plain file:// URI a
        # BDMV folder does not play at all.
        (tmp_path / "BDMV").mkdir()
        target = MediaTarget.blu_ray(tmp_path)

        assert target.kind is MediaKind.BLU_RAY
        assert target.mrl.startswith("bluray:///")
        assert "file://" not in target.mrl
        assert target.source == tmp_path

    def test_a_space_in_the_path_survives(self, tmp_path: Path) -> None:
        folder = tmp_path / "INDIEFORGE MEGAWORKS"
        folder.mkdir()
        assert "%20" in MediaTarget.blu_ray(folder).mrl

    def test_a_dvd_image_gets_the_dvd_scheme(self, tmp_path: Path) -> None:
        image = tmp_path / "film.iso"
        image.write_bytes(b"")
        target = MediaTarget.dvd(image)
        assert target.kind is MediaKind.DVD_VIDEO
        assert target.mrl.startswith("dvd:///")
        assert "file://" not in target.mrl

    def test_an_image_is_named_the_same_way_as_a_folder(self, tmp_path: Path) -> None:
        image = tmp_path / "disc.iso"
        image.write_bytes(b"")
        assert MediaTarget.blu_ray(image).mrl.startswith("bluray:///")

    def test_a_dvd_title_is_named_by_the_files_its_video_lives_in(
        self, tmp_path: Path
    ) -> None:
        # No dvd:// MRL, and so no DVD engine, and so no descrambler: the
        # structure came from our own reader and this is only video.
        vobs = []
        for number in (1, 2):
            path = tmp_path / f"VTS_01_{number}.VOB"
            path.write_bytes(b"")
            vobs.append(path)
        target = MediaTarget.dvd_title(vobs)

        assert target.kind is MediaKind.DVD_VIDEO
        assert target.mrl == "concat://"
        assert len(target.options) == 1
        assert target.options[0].startswith(":concat-list=")
        assert target.options[0].count(",") == 1
        assert "VTS_01_1.VOB" in target.options[0]

    def test_a_dvd_title_with_no_files_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least one VOB"):
            MediaTarget.dvd_title([])

    def test_an_audio_cd_by_drive_and_by_track(self) -> None:
        whole = MediaTarget.audio_cd("E:\\")
        assert whole.kind is MediaKind.AUDIO_CD
        assert whole.mrl == "cdda:///E:/"
        track = MediaTarget.audio_cd("E:\\", track=4)
        assert track.mrl == "cdda:///E:/"
        assert track.options == (":cdda-track=5",)

    def test_an_ordinary_file(self, tmp_path: Path) -> None:
        path = tmp_path / "clip.mkv"
        path.write_bytes(b"")
        target = MediaTarget.file(path)
        assert target.kind is MediaKind.FILE
        assert target.mrl.startswith("file:///")


class TestFakeEngine:
    def test_opening_a_disc_starts_playing(self, tmp_path: Path) -> None:
        engine = FakeEngine(simple_disc())
        seen: list[PlaybackState] = []
        engine.add_listener(lambda event: seen.append(event.state))

        engine.open(MediaTarget.blu_ray(tmp_path))

        assert seen == [PlaybackState.OPENING, PlaybackState.PLAYING]
        assert engine.state is PlaybackState.PLAYING

    def test_a_disc_that_cannot_be_read_reports_an_error_with_words(
        self, tmp_path: Path
    ) -> None:
        disc = simple_disc()
        disc.open_error = "This disc could not be read."
        engine = FakeEngine(disc)
        messages: list[str] = []
        engine.add_listener(lambda event: messages.append(event.message))

        engine.open(MediaTarget.blu_ray(tmp_path))

        assert engine.state is PlaybackState.ERROR
        assert messages == ["This disc could not be read."]

    def test_menu_navigation_wraps_and_activation_follows_the_button(
        self, tmp_path: Path
    ) -> None:
        engine = FakeEngine(simple_disc())
        engine.open(MediaTarget.blu_ray(tmp_path))

        assert engine.selected_button == 0
        engine.navigate(NavAction.DOWN)
        assert engine.selected_button == 1
        engine.navigate(NavAction.DOWN)
        assert engine.selected_button == 0  # a menu is a ring
        engine.navigate(NavAction.UP)
        assert engine.selected_button == 1

        engine.navigate(NavAction.ACTIVATE)
        assert engine.current_title == 1

    def test_the_top_menu_action_goes_to_the_menu_title(self, tmp_path: Path) -> None:
        engine = FakeEngine(simple_disc())
        engine.open(MediaTarget.blu_ray(tmp_path))
        engine.select_title(1)

        engine.navigate(NavAction.TOP_MENU)
        assert engine.current_title == 0

    def test_playing_to_the_end_ends(self, tmp_path: Path) -> None:
        engine = FakeEngine(simple_disc(duration_ms=5000))
        engine.open(MediaTarget.blu_ray(tmp_path))
        engine.select_title(1)

        engine.advance(4000)
        assert engine.state is PlaybackState.PLAYING
        engine.advance(2000)
        assert engine.state is PlaybackState.ENDED
        assert engine.position_ms == 5000

    def test_pause_and_resume(self, tmp_path: Path) -> None:
        engine = FakeEngine(simple_disc())
        engine.open(MediaTarget.blu_ray(tmp_path))
        engine.select_title(1)

        engine.toggle_pause()
        assert engine.state is PlaybackState.PAUSED
        engine.advance(1000)
        assert engine.position_ms == 0  # paused time does not move
        engine.toggle_pause()
        assert engine.state is PlaybackState.PLAYING

    def test_seeking_is_clamped_to_the_title(self, tmp_path: Path) -> None:
        engine = FakeEngine(simple_disc(duration_ms=5000))
        engine.open(MediaTarget.blu_ray(tmp_path))
        engine.select_title(1)

        engine.seek(-1000)
        assert engine.position_ms == 0
        engine.seek(999_999)
        assert engine.position_ms == 5000

    def test_chapters_move_the_position(self, tmp_path: Path) -> None:
        engine = FakeEngine(simple_disc(duration_ms=9000))
        engine.open(MediaTarget.blu_ray(tmp_path))
        engine.select_title(1)

        assert engine.chapters() == [0, 3000, 6000]
        engine.select_chapter(2)
        assert engine.position_ms == 6000
        engine.select_chapter(99)  # out of range does nothing
        assert engine.position_ms == 6000
