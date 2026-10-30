"""An album's locker copy (WAVs beside a CUE) plays, track by track (found in the built 1.0.3, 30 Oct 2026).

Since 30 Aug such a copy was read as the album it is, then handed to the CD reader as if it were a disc in a
drive, which has no track N to give: "This disc could not be read", in 1.0.2 as in 1.0.3. Each track is its
own WAV, and that file is what plays.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wti_player.engine.base import MediaKind
from wti_player.optical.identify import album_copy_tracks

pytest.importorskip("PyQt6.QtWidgets")


def _album(tmp_path: Path) -> Path:
    root = tmp_path / "album"
    root.mkdir()
    (root / "album.cue").write_text('FILE "01.wav" WAVE\n  TRACK 01 AUDIO\n', encoding="utf-8")
    for n in (1, 2, 3):
        (root / f"{n:02d}.wav").write_bytes(b"RIFF" + b"\0" * 40)
    return root


class _NoPad:
    available = False

    def read(self):
        return None


def _window(qapp):
    from wti_player.engine.fake import FakeEngine, simple_disc
    from wti_player.optical.drives import DriveWatcher, FakeScanner
    from wti_player.optical.reader import ImmediateReader
    from wti_player.ui.main_window import MainWindow

    engine = FakeEngine(simple_disc())
    window = MainWindow(
        engine,
        watcher=DriveWatcher(FakeScanner([])),
        gamepad=_NoPad(),
        reader=ImmediateReader(),
        auto_play=False,
    )
    return window, engine


def test_the_tracks_of_a_copy_are_its_wavs_in_order(tmp_path: Path) -> None:
    root = _album(tmp_path)
    assert [p.name for p in album_copy_tracks(root)] == ["01.wav", "02.wav", "03.wav"]


def test_anything_else_has_no_copy_tracks(tmp_path: Path) -> None:
    loose = tmp_path / "loose"
    loose.mkdir()
    (loose / "a.wav").write_bytes(b"RIFF")
    assert album_copy_tracks(loose) == []
    assert album_copy_tracks(tmp_path / "missing") == []
    image = tmp_path / "disc.iso"
    image.write_bytes(b"\0" * 2048)
    assert album_copy_tracks(image) == []


def test_a_root_with_cd_tracks_is_a_disc_whatever_else_it_holds(tmp_path: Path) -> None:
    root = _album(tmp_path)
    (root / "Track01.cda").write_bytes(b"\0" * 44)
    assert album_copy_tracks(root) == []


def test_opening_a_copy_plays_its_first_wav_as_a_file(qapp, tmp_path: Path) -> None:
    root = _album(tmp_path)
    window, engine = _window(qapp)
    try:
        window.open_path(root)
        target = engine.opened[-1]
        assert target.kind is MediaKind.FILE
        assert Path(target.source).name == "01.wav"
    finally:
        window.close()


def test_choosing_a_track_and_running_out_both_play_the_right_wav(qapp, tmp_path: Path) -> None:
    root = _album(tmp_path)
    window, engine = _window(qapp)
    try:
        window.open_path(root)
        window.play_track(1)
        assert Path(engine.opened[-1].source).name == "02.wav"
        assert window._play_next_track()
        assert Path(engine.opened[-1].source).name == "03.wav"
        assert not window._play_next_track(), "there is no fourth track"
    finally:
        window.close()


def test_a_disc_in_a_drive_is_still_asked_for_by_track(qapp, tmp_path: Path) -> None:
    from wti_player.optical.identify import DiscKind, DiscProfile, TitleSummary

    window, engine = _window(qapp)
    try:
        drive = tmp_path / "drive"
        drive.mkdir()
        for n in (1, 2):
            (drive / f"Track{n:02d}.cda").write_bytes(b"\0" * 44)
        profile = DiscProfile(
            kind=DiscKind.AUDIO_CD,
            root=drive,
            label="CD",
            titles=(TitleSummary(number=0, name="Track01", duration_ms=0), TitleSummary(number=1, name="Track02", duration_ms=0)),
            main_feature=0,
        )
        window.profile = profile
        window.open_audio_cd(profile)
        assert engine.opened[-1].kind is MediaKind.AUDIO_CD
        assert engine.opened[-1].options == (":cdda-track=1",)
    finally:
        window.close()
