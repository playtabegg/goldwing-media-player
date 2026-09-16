"""W2 (30 Aug 2026): the shelf of local copies, and a game's own menu by path.

A local copy is a folder laid out like the disc. The shelf reads each one's
own document, sorts films, albums, games; a game row opens ``menu\\menu.exe``
from its own folder and nothing else; a folder with no document is not a
copy and the shelf says so.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wti_player import shelf
from wti_player.ui.prefs import MemoryPreferences


def copy_of(root: Path, kind: str, title: str, *, author: str = "A Studio", menu: bool = False, edition: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    document = {
        "schema": 1,
        "kind": kind,
        "title": title,
        "author": author,
        "id": title.lower().replace(" ", "-"),
        "version": "1.0.0",
        "made_by": "We the Indies",
    }
    (root / ".wti_meta.json").write_text(json.dumps(document), encoding="utf-8")
    (root / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0jpeg")
    if menu:
        (root / "menu").mkdir(exist_ok=True)
        (root / "menu" / "menu.exe").write_bytes(b"MZ")
        (root / "menu" / "menu_config.json").write_text("{}", encoding="utf-8")
    if edition:
        (root / ".wti_edition.json").write_text(
            json.dumps({"schema": 1, "title": title, "edition": "standard", "number": 7, "issued": "2026-09-19"}),
            encoding="utf-8",
        )
    return root


class TestReadEntry:
    def test_a_film_an_album_and_a_game_read_as_themselves(self, tmp_path: Path) -> None:
        film = shelf.read_entry(copy_of(tmp_path / "film", "movie", "Sally, Irene and Mary"))
        album = shelf.read_entry(copy_of(tmp_path / "album", "music", "Night Songs"))
        game = shelf.read_entry(copy_of(tmp_path / "game", "game", "Foxtail", menu=True))
        assert film is not None and film.kind == "film" and film.kind_label == "Film"
        assert album is not None and album.kind == "album"
        assert game is not None and game.kind == "game" and game.has_menu
        assert film.cover is not None and film.cover.name == "cover.jpg"
        assert "A Studio" in film.describe()

    def test_a_folder_with_no_document_is_not_a_copy(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / "readme.txt").write_text("hello", encoding="utf-8")
        assert shelf.read_entry(plain) is None
        assert shelf.read_entry(tmp_path / "gone") is None

    def test_the_edition_line_rides_along_when_the_copy_came_from_a_numbered_disc(self, tmp_path: Path) -> None:
        entry = shelf.read_entry(copy_of(tmp_path / "numbered", "game", "Foxtail", edition=True))
        assert entry is not None
        assert "7" in entry.edition_line
        assert entry.signed is False  # unsigned record: shown, never trusted


class TestScan:
    def test_films_then_albums_then_games_by_title_and_no_duplicates(self, tmp_path: Path) -> None:
        roots = [
            copy_of(tmp_path / "g2", "game", "Zebra Run", menu=True),
            copy_of(tmp_path / "a1", "music", "Night Songs"),
            copy_of(tmp_path / "f1", "movie", "Sally, Irene and Mary"),
            copy_of(tmp_path / "g1", "game", "Foxtail", menu=True),
            tmp_path / "gone",
        ]
        roots.append(Path(str(roots[0]).upper()))
        entries = shelf.scan(roots)
        assert [e.kind for e in entries] == ["film", "album", "game", "game"]
        assert [e.title for e in entries][-2:] == ["Foxtail", "Zebra Run"]
        assert len(entries) == 4

    def test_add_and_remove_roots_keep_one_of_each(self, tmp_path: Path) -> None:
        a = tmp_path / "a"
        roots = shelf.add_root([], a)
        roots = shelf.add_root(roots, Path(str(a).upper()))
        assert len(roots) == 1
        roots = shelf.add_root(roots, tmp_path / "b")
        assert [p.name for p in roots] == ["A", "b"] or [p.name.lower() for p in roots] == ["a", "b"]
        assert shelf.remove_root(roots, a) == [tmp_path / "b"]

    def test_the_preferences_keep_the_shelf(self, tmp_path: Path) -> None:
        prefs = MemoryPreferences()
        prefs.set_shelf([tmp_path / "one", tmp_path / "two"])
        assert prefs.shelf() == [tmp_path / "one", tmp_path / "two"]


class TestGameMenu:
    def test_opens_menu_exe_from_its_own_folder_and_nothing_else(self, tmp_path: Path) -> None:
        root = copy_of(tmp_path / "game", "game", "Foxtail", menu=True)
        (root / "setup.exe").write_bytes(b"MZ")
        calls: list[tuple[list[str], str]] = []

        def popen(args, cwd=None, **_kw):
            calls.append((list(args), str(cwd)))
            return object()

        started = shelf.open_game_menu(root, popen=popen)
        assert started == (root / "menu" / "menu.exe").resolve()
        assert calls == [([str(started)], str(started.parent))]

    def test_a_copy_with_no_menu_says_so_and_starts_nothing(self, tmp_path: Path) -> None:
        root = copy_of(tmp_path / "game", "game", "Foxtail")
        calls: list[object] = []
        with pytest.raises(shelf.MenuMissing):
            shelf.open_game_menu(root, popen=lambda *a, **k: calls.append(a))
        assert calls == []
        assert shelf.menu_executable(root) is None

    def test_the_menu_must_be_inside_the_copy(self, tmp_path: Path) -> None:
        # A menu folder that is a file, or points outside, is not a menu.
        root = tmp_path / "odd"
        root.mkdir()
        (root / "menu").write_bytes(b"not a folder")
        assert shelf.menu_executable(root) is None
