"""An album's locker copy (WAVs beside a CUE) reads as the album it is."""

from __future__ import annotations

import json
from pathlib import Path

from wti_player.optical.identify import DiscKind, identify


def _album(tmp_path: Path, with_meta: bool) -> Path:
    root = tmp_path / "album"
    root.mkdir()
    (root / "album.cue").write_text('FILE "01.wav" WAVE\n  TRACK 01 AUDIO\n', encoding="utf-8")
    for n in (1, 2, 3):
        (root / f"{n:02d}.wav").write_bytes(b"RIFF" + b"\0" * 40)
    if with_meta:
        (root / ".wti_meta.json").write_text(
            json.dumps({"title": "Songs", "kind": "music", "made_by": "We The Indies"}), encoding="utf-8"
        )
    return root


def test_a_cue_beside_wavs_is_an_audio_cd(tmp_path: Path) -> None:
    profile = identify(_album(tmp_path, with_meta=False))
    assert profile.kind == DiscKind.AUDIO_CD
    assert profile.playable
    assert [t.name for t in profile.titles] == ["01", "02", "03"]


def test_a_folder_of_wavs_without_a_cue_is_still_data(tmp_path: Path) -> None:
    root = tmp_path / "loose"
    root.mkdir()
    (root / "a.wav").write_bytes(b"RIFF")
    assert identify(root).kind != DiscKind.AUDIO_CD


def test_the_copy_carries_its_document(tmp_path: Path) -> None:
    profile = identify(_album(tmp_path, with_meta=True))
    assert profile.kind == DiscKind.AUDIO_CD
    assert profile.meta is not None
