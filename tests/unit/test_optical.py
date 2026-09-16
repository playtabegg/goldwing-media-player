"""Drive detection, insertion, and working out what a disc is."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from wti_player.optical.drives import (
    DriveEventKind,
    DriveWatcher,
    FakeScanner,
    OpticalDrive,
)
from wti_player.optical.identify import DiscKind, identify


class TestDriveWatcher:
    def test_the_first_poll_reports_the_drives_and_any_disc_in_them(self) -> None:
        scanner = FakeScanner(
            [
                OpticalDrive(mount="D:\\", description="Disc drive (D:)"),
                OpticalDrive(
                    mount="E:\\", description="Disc drive (E:)", has_media=True, label="SHOOTY"
                ),
            ]
        )
        events = DriveWatcher(scanner).poll()

        assert [event.kind for event in events] == [
            DriveEventKind.APPEARED,
            DriveEventKind.APPEARED,
            DriveEventKind.INSERTED,
        ]
        assert events[2].drive.label == "SHOOTY"

    def test_insertion_and_ejection(self) -> None:
        scanner = FakeScanner([OpticalDrive(mount="E:\\")])
        watcher = DriveWatcher(scanner)
        watcher.poll()

        scanner.insert("E:\\", label="WTI_MENU_TEST")
        events = watcher.poll()
        assert [event.kind for event in events] == [DriveEventKind.INSERTED]
        assert watcher.find("E:\\").label == "WTI_MENU_TEST"

        scanner.eject("E:\\")
        assert [event.kind for event in watcher.poll()] == [DriveEventKind.EJECTED]

    def test_a_quiet_poll_reports_nothing(self) -> None:
        scanner = FakeScanner([OpticalDrive(mount="E:\\", has_media=True, label="A")])
        watcher = DriveWatcher(scanner)
        watcher.poll()
        assert watcher.poll() == []

    def test_a_disc_swapped_between_polls_is_seen_as_a_swap(self) -> None:
        scanner = FakeScanner([OpticalDrive(mount="E:\\", has_media=True, label="FIRST")])
        watcher = DriveWatcher(scanner)
        watcher.poll()

        scanner.insert("E:\\", label="SECOND")
        assert [event.kind for event in watcher.poll()] == [
            DriveEventKind.EJECTED,
            DriveEventKind.INSERTED,
        ]

    def test_a_usb_drive_unplugged_is_removed(self) -> None:
        scanner = FakeScanner([OpticalDrive(mount="E:\\")])
        watcher = DriveWatcher(scanner)
        watcher.poll()
        scanner._drives.clear()
        assert [event.kind for event in watcher.poll()] == [DriveEventKind.REMOVED]

    def test_a_drive_describes_itself_for_a_person(self) -> None:
        empty = OpticalDrive(mount="E:\\", description="BD-ROM Drive (E:)")
        loaded = OpticalDrive(mount="E:\\", description="BD-ROM Drive (E:)", has_media=True)
        # A middle dot, never an em-dash: the one house rule on every string.
        assert empty.describe() == "BD-ROM Drive (E:) · empty"
        assert loaded.describe() == "BD-ROM Drive (E:) · untitled disc"
        assert empty.device_path == r"\\.\E:"
        assert empty.letter == "E"


class TestIdentify:
    def test_a_blu_ray(self, menu_disc) -> None:
        profile = identify(menu_disc, label="WTI_MENU_TEST")

        assert profile.kind is DiscKind.BLU_RAY
        assert profile.playable
        assert profile.has_menu
        assert not profile.needs_bdj
        assert not profile.problem
        assert len(profile.titles) == 2
        assert profile.main_feature == 1
        assert profile.titles[1].chapters == 3

    def test_a_data_disc(self, data_disc) -> None:
        profile = identify(data_disc)

        assert profile.kind is DiscKind.DATA
        assert profile.browsable
        assert profile.file_count >= 4

    def test_a_game_disc_is_told_apart_from_plain_data(self, game_disc) -> None:
        profile = identify(game_disc)

        assert profile.kind is DiscKind.GAME_DISC
        assert profile.ours
        assert profile.label.startswith("Shooty Shooty")
        assert profile.display_name == "Shooty Shooty"

    def test_someone_elses_autorun_is_a_game_but_not_ours(self, tmp_path) -> None:
        (tmp_path / "autorun.inf").write_text("[autorun]\nopen=setup.exe\n", encoding="ascii")
        (tmp_path / "setup.exe").write_bytes(b"MZ")
        profile = identify(tmp_path)
        assert profile.kind is DiscKind.GAME_DISC
        assert not profile.ours

    def test_an_empty_drive(self, tmp_path) -> None:
        assert identify(tmp_path).kind is DiscKind.EMPTY

    def test_a_path_that_is_not_there(self, tmp_path) -> None:
        profile = identify(tmp_path / "nope")
        assert profile.kind is DiscKind.UNREADABLE
        assert profile.problem

    def test_an_audio_cd(self, tmp_path) -> None:
        for track in range(1, 4):
            (tmp_path / f"Track{track:02d}.cda").write_bytes(b"RIFF" + b"\x00" * 40)
        profile = identify(tmp_path, label="MUSOPEN")

        assert profile.kind is DiscKind.AUDIO_CD
        assert profile.playable
        assert [title.name for title in profile.titles] == ["Track01", "Track02", "Track03"]

    def test_a_dvd(self, dvd_disc) -> None:
        profile = identify(dvd_disc, label="MY_DVD")

        assert profile.kind is DiscKind.DVD_VIDEO
        assert profile.playable
        assert not profile.problem
        assert len(profile.titles) == 1
        assert profile.titles[0].chapters == 3
        assert profile.main_feature == 1
        # A DVD's menus need a navigator the Player does not have. Claiming
        # otherwise would put a button on screen that does nothing.
        assert not profile.has_menu

    def test_a_dvd_missing_its_index_says_what_is_wrong(self, tmp_path) -> None:
        video_ts = tmp_path / "VIDEO_TS"
        video_ts.mkdir()
        (video_ts / "VTS_01_1.VOB").write_bytes(b"\x00" * 100)

        profile = identify(tmp_path)
        assert profile.kind is DiscKind.DVD_VIDEO
        assert "VIDEO_TS.IFO" in profile.problem

    def test_a_dvd_whose_tables_are_damaged_does_not_throw(self, tmp_path) -> None:
        # The shape a scratched disc arrives in: the magic reads, the tables
        # do not. That has to be a sentence, not a struct error.
        video_ts = tmp_path / "VIDEO_TS"
        video_ts.mkdir()
        (video_ts / "VIDEO_TS.IFO").write_bytes(b"DVDVIDEO-VMG" + b"\x00" * 100)

        profile = identify(tmp_path)
        assert profile.kind is DiscKind.DVD_VIDEO
        assert profile.problem
        assert profile.problem[0].isupper()

    def test_pointing_straight_at_a_video_ts_folder_works(self, dvd_disc) -> None:
        assert identify(dvd_disc / "VIDEO_TS").kind is DiscKind.DVD_VIDEO

    def test_a_blu_ray_with_a_damaged_seek_index_is_refused_not_played(
        self, menu_disc, tmp_path
    ) -> None:
        # libbluray crashes on this rather than complaining, so the Player
        # has to be the one that notices. Blank the clip's CPI length.
        import shutil

        broken = tmp_path / "broken"
        shutil.copytree(menu_disc, broken)
        clpi_path = broken / "BDMV" / "CLIPINF" / "00000.clpi"
        data = bytearray(clpi_path.read_bytes())
        cpi_start = int.from_bytes(data[16:20], "big")
        data[cpi_start : cpi_start + 4] = b"\x00\x00\x00\x00"
        clpi_path.write_bytes(bytes(data))

        profile = identify(broken)
        assert profile.kind is DiscKind.BLU_RAY
        assert "seek index" in profile.problem
        assert profile.problem.endswith(".")


@pytest.mark.media
class TestIdentifyAnImage:
    """An .iso is peeked. Guessing Blu-ray was how game discs got that label."""

    def _image(self, tmp_path, *markers: bytes, name: str = "disc.iso"):
        data = bytearray(32 * 2048)
        pvd = 16 * 2048
        data[pvd + 1 : pvd + 6] = b"CD001"
        data[pvd + 40 : pvd + 48] = b"RUTTED  "
        cursor = 17 * 2048
        for marker in markers:
            data[cursor : cursor + len(marker)] = marker
            cursor += len(marker) + 8
        path = tmp_path / name
        path.write_bytes(data)
        return path

    def test_an_iso_with_autorun_is_a_game_disc(self, tmp_path) -> None:
        path = self._image(tmp_path, b"AUTORUN.INF", b"MENU.EXE")
        profile = identify(path)
        assert profile.kind is DiscKind.GAME_DISC
        assert profile.ours
        assert profile.browsable
        assert not profile.playable
        assert "we the indies" in " ".join(profile.notes).lower()
        assert "video disc" not in " ".join(profile.notes).lower()
        assert "blu-ray" not in " ".join(profile.notes).lower()

    def test_an_iso_with_only_autorun_is_someone_elses_game(self, tmp_path) -> None:
        path = self._image(tmp_path, b"AUTORUN.INF")
        profile = identify(path)
        assert profile.kind is DiscKind.GAME_DISC
        assert not profile.ours
        assert "someone else" in " ".join(profile.notes).lower()

    def test_an_iso_with_video_ts_is_a_dvd(self, tmp_path) -> None:
        profile = identify(self._image(tmp_path, b"VIDEO_TS"))
        assert profile.kind is DiscKind.DVD_VIDEO
        assert profile.playable

    def test_an_iso_with_bdmv_is_a_blu_ray(self, tmp_path) -> None:
        profile = identify(self._image(tmp_path, b"BDMV", b"index.bdmv"))
        assert profile.kind is DiscKind.BLU_RAY

    def test_an_empty_iso_is_not_a_blu_ray(self, tmp_path) -> None:
        profile = identify(self._image(tmp_path))
        assert profile.kind is DiscKind.DATA
        assert not profile.playable

    def test_rutted_from_rialto_15_is_a_game_disc(self) -> None:
        configured = os.environ.get("WTI_TEST_RUTTED_ISO")
        if not configured:
            pytest.skip("Set WTI_TEST_RUTTED_ISO to an existing Rialto 1.5 test disc")
        path = Path(configured)
        if not path.is_file():
            pytest.skip("Rialto 1.5 output is not on this machine")
        profile = identify(path)
        assert profile.kind is DiscKind.GAME_DISC
        assert profile.ours
        assert profile.display_name.lower().startswith("rutted")


class TestIdentifyNeedsMedia:
    def test_an_iso_is_left_for_the_engine_to_open(self, generated_dir) -> None:
        image = generated_dir / "bd_menu.iso"
        if not image.is_file():
            pytest.skip("run: python tools/make_fixtures.py")
        profile = identify(image)
        assert profile.kind is DiscKind.BLU_RAY
        assert profile.notes


class TestReadingWithoutFreezing:
    """An optical drive takes its time; the window has to keep painting."""

    def test_the_immediate_reader_answers_on_the_spot(self, menu_disc) -> None:
        from wti_player.optical.reader import ImmediateReader

        answers: list = []
        ImmediateReader().read(menu_disc, "LABEL", answers.append)

        assert len(answers) == 1
        assert answers[0].kind is DiscKind.BLU_RAY
        assert answers[0].label == "LABEL"

    def test_a_data_disc_walk_is_bounded(self, tmp_path) -> None:
        # A disc with a great many files must not hold the answer up. The
        # count becomes approximate; the disc still opens.
        import time

        from wti_player.optical import identify as identify_module

        for index in range(600):
            folder = tmp_path / f"dir{index // 50}"
            folder.mkdir(exist_ok=True)
            (folder / f"file{index}.bin").write_bytes(b"x" * 16)

        started = time.monotonic()
        profile = identify(tmp_path)
        elapsed = time.monotonic() - started

        assert profile.kind is DiscKind.DATA
        assert profile.file_count > 0
        assert elapsed < identify_module._MAX_WALK_SECONDS + 2


class TestNamingMediaSafely:
    def test_a_comma_in_a_folder_name_does_not_split_the_file_list(
        self, tmp_path
    ) -> None:
        # A DVD title's files are given to the engine as one comma-separated
        # list. Films have commas in their names.
        from wti_player.engine.base import MediaTarget

        folder = tmp_path / "Sally, Irene and Mary (1925)"
        folder.mkdir()
        vobs = []
        for number in (1, 2):
            path = folder / f"VTS_01_{number}.VOB"
            path.write_bytes(b"")
            vobs.append(path)

        option = MediaTarget.dvd_title(vobs).options[0]
        assert option.count(",") == 1, "one separator, not three"
        assert "%2C" in option, "the name's own comma has to be escaped"
