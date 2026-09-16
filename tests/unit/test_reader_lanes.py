"""Review, 28 Aug 2026: a disc read starting must not drop a menu read in flight."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6.QtCore")

from PyQt6.QtCore import QThreadPool

from wti_player.optical.reader import ThreadedReader


def _drain(qapp) -> None:
    QThreadPool.globalInstance().waitForDone(5000)
    for _ in range(20):
        qapp.processEvents()


def test_a_menu_read_survives_a_disc_read_started_after_it(qapp, tmp_path) -> None:
    reader = ThreadedReader()
    delivered: list[tuple[str, object]] = []
    reader.run("dvd menu", lambda: "THE MENU", lambda answer: delivered.append(("menu", answer)))
    reader.read(tmp_path, "DISC", lambda profile: delivered.append(("disc", profile.label)))
    _drain(qapp)
    kinds = sorted(kind for kind, _ in delivered)
    assert kinds == ["disc", "menu"], delivered
    assert ("menu", "THE MENU") in delivered


def test_a_second_menu_read_still_replaces_the_first(qapp) -> None:
    reader = ThreadedReader()
    delivered: list[object] = []
    reader.run("one", lambda: "first", delivered.append)
    reader.run("two", lambda: "second", delivered.append)
    _drain(qapp)
    assert delivered == ["second"]


def test_cancel_forgets_both_lanes(qapp, tmp_path) -> None:
    reader = ThreadedReader()
    delivered: list[object] = []
    reader.run("menu", lambda: "menu", delivered.append)
    reader.read(tmp_path, "DISC", lambda profile: delivered.append(profile.label))
    reader.cancel()
    _drain(qapp)
    assert delivered == []
