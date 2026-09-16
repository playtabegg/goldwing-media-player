"""W2: the shelf on the empty screen, and a game row opening its own menu."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wti_player import shelf, strings

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QLabel

from wti_player.ui import views


def copy_of(root: Path, kind: str, title: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".wti_meta.json").write_text(
        json.dumps({"schema": 1, "kind": kind, "title": title, "author": "A Studio", "id": "x", "version": "1.0.0", "made_by": "We the Indies"}),
        encoding="utf-8",
    )
    return root


def test_the_empty_shelf_says_so(qapp) -> None:
    view = views.WelcomeView()
    texts = [label.text() for label in view.findChildren(QLabel)]
    # Section headings are the program's one uppercase.
    assert strings.SHELF_TITLE.upper() in texts
    assert strings.SHELF_EMPTY in texts


def test_rows_appear_for_copies_and_a_click_names_the_root(qapp, tmp_path: Path) -> None:
    entries = shelf.scan([copy_of(tmp_path / "film", "movie", "Sally, Irene and Mary"), copy_of(tmp_path / "game", "game", "Foxtail")])
    view = views.WelcomeView()
    view.set_shelf(entries)
    rows = view.findChildren(views._ShelfRow)
    assert [r._title for r in rows] == ["Sally, Irene and Mary", "Foxtail"]
    opened: list[str] = []
    view.open_shelf_entry.connect(opened.append)
    rows[1]._signal.emit(rows[1]._root)
    assert opened == [str(tmp_path / "game")]
    # The empty note has left the layout (its widget is deleted on the next tick).
    assert view._shelf.count() == 2
    assert all(isinstance(view._shelf.itemAt(i).widget(), views._ShelfRow) for i in range(2))


def test_add_to_shelf_explains_itself(qapp) -> None:
    from PyQt6.QtWidgets import QPushButton

    view = views.WelcomeView()
    buttons = [b for b in view.findChildren(QPushButton) if b.text() == strings.ADD_TO_SHELF]
    assert buttons
    assert buttons[0].toolTip() == strings.ADD_TO_SHELF_TIP


def test_the_strings_keep_the_house_voice() -> None:
    for text in (strings.SHELF_TITLE, strings.SHELF_EMPTY, strings.ADD_TO_SHELF, strings.ADD_TO_SHELF_TIP, strings.OPEN_GAME_MENU, strings.GAME_MENU_OPENED, strings.GAME_MENU_MISSING, strings.NOT_A_COPY):
        assert "—" not in text
        assert "account" not in text.lower()
