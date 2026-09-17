"""The stable release version has one source, and its binaries carry a build stamp."""

from __future__ import annotations

import re
from pathlib import Path

from wti_player import strings, version


def test_the_player_ships_as_a_stable_version() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", version.VERSION)


def test_the_early_build_label_is_off_by_chandlers_word() -> None:
    assert version.EARLY_BUILD is False
    assert version.display_version() == version.VERSION


def test_pyproject_reads_the_version_from_the_module() -> None:
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "' not in text.split("[project.optional-dependencies]")[0]
    assert 'dynamic = ["version"]' in text
    assert 'attr = "wti_player.version.VERSION"' in text


def test_a_source_checkout_says_so() -> None:
    assert version.build_stamp() == (version.BUILD_STAMP or "source checkout")
    if not version.BUILD_STAMP:
        assert version.build_stamp() == "source checkout"


def test_the_about_box_names_the_build() -> None:
    assert "Build " in strings.about_text()
    assert version.build_stamp() in strings.about_text()


def test_the_version_block_carries_the_stamp(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, "tools")
    import build_exe

    path = build_exe.write_version_info(tmp_path / "version_info.txt", stamp="abc123456 2026-09-01")
    text = path.read_text(encoding="utf-8")
    assert "build abc123456 2026-09-01" in text
    assert f"FileVersion', u'{version.VERSION}'" in text
    numbers = (*(int(part) for part in version.VERSION.split('.')), 0)
    assert f"filevers={numbers}" in text


def test_the_stamp_module_is_written_and_ignored(tmp_path: Path, monkeypatch) -> None:
    import sys

    sys.path.insert(0, "tools")
    import build_exe

    monkeypatch.setattr(build_exe, "REPO", tmp_path)
    (tmp_path / "wti_player").mkdir()
    path = build_exe.write_build_stamp("abc123456 2026-09-01")
    assert path.read_text(encoding="utf-8").strip().endswith("BUILD_STAMP = 'abc123456 2026-09-01'")
    assert "wti_player/_build_stamp.py" in Path(".gitignore").read_text(encoding="utf-8")


def test_the_stamp_names_a_commit_and_a_day() -> None:
    import sys

    sys.path.insert(0, "tools")
    import build_exe

    stamp = build_exe.build_stamp_text()
    assert re.fullmatch(r"([0-9a-f]{9}\+?|unknown) \d{4}-\d{2}-\d{2}", stamp), stamp
