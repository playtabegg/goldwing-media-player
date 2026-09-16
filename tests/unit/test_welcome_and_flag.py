"""P7 (28 Aug 2026): the empty screen carries the promise.

The EARLY BUILD chip that sat on the top bar went on 1 Sep 2026, by
Chandler's word that this is 1.0.0. The test below is the guard that it
does not come back by accident.
"""

from __future__ import annotations

import pytest

from wti_player import strings, version

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QLabel

from wti_player.ui import views


def test_the_promise_is_one_sentence_about_ownership_and_one_about_autonomy() -> None:
    assert "outlive the company" in strings.WELCOME_PROMISE
    assert "account" in strings.WELCOME_PROMISE
    assert "on its own" in strings.WELCOME_PROMISE
    assert "\u2014" not in strings.WELCOME_PROMISE


def test_the_welcome_view_shows_it(qapp) -> None:
    view = views.WelcomeView()
    texts = [label.text() for label in view.findChildren(QLabel)]
    assert strings.WELCOME_TITLE in texts
    assert strings.WELCOME_PROMISE in texts


def test_nothing_on_the_top_bar_says_early_build(qapp) -> None:
    bar = views.TopBar()
    assert not hasattr(bar, "early")
    for label in bar.findChildren(QLabel):
        assert "early" not in label.text().lower(), label.text()


def test_the_flag_is_off_and_says_who_turned_it_off(qapp) -> None:
    assert version.EARLY_BUILD is False
