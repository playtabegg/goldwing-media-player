"""P5 (28 Aug 2026): the disc's forced entry action is carried, not dropped.

``Navigator.show`` returns whatever the menu's activated-on-arrival button
does. ``menu._read`` computed it and threw it away; a disc whose root menu
jumps straight to a title arrived as a menu with a lit button and nothing
happening.
"""

from __future__ import annotations

import pytest

from wti_player.dvd import menu as menu_reader
from wti_player.dvd import navigator as nav


@pytest.fixture
def menu_dvd(generated_dir):
    path = generated_dir / "dvd_menu_disc"
    if not (path / "VIDEO_TS" / "VTS_01_0.VOB").is_file():
        pytest.skip("run: python tools/make_fixtures.py")
    return path


def test_a_menu_with_no_forced_button_carries_no_entry_action(menu_dvd) -> None:
    found = menu_reader.read(menu_dvd)
    assert found is not None
    assert found.entry_action is None


def test_the_navigator_knows_its_title_set(menu_dvd) -> None:
    found = menu_reader.read(menu_dvd, title_set=1)
    assert found is not None
    assert found.navigator.title_set == 1


def test_a_forced_button_is_reported_as_the_entry_action() -> None:
    from tests.unit.test_dvd_navigator import PLAY_TITLE_2, two_button_menu

    forced = two_button_menu(activated=2)
    navigator = nav.Navigator()
    action = navigator.show(forced)
    assert action.kind == nav.PLAY_TITLE
    assert action.title == 2
    assert PLAY_TITLE_2  # the button that fired
