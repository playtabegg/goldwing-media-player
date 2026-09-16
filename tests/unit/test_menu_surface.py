"""Drawing a DVD menu, offscreen.

The interesting property is not that pixels appear — it is that the highlight
moves by re-colouring one rectangle rather than redrawing the whole menu.
Getting that wrong is what makes DVD menus feel slow in a software player.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication

from tests.fixtures.authoring import spu as enc
from tests.fixtures.authoring import videots as vt
from wti_player.dvd.navigator import Navigator
from wti_player.formats import dvd_nav, dvd_spu
from wti_player.ui.menu_surface import MenuSurface

#: A greyscale-ish chain palette: transparent, white, blue, grey.
CHAIN_PALETTE = [0x108080, 0xEB8080, 0x51EF5A, 0x808080] + [0] * 12


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def two_button_menu():
    rows = [[0] * 720 for _ in range(480)]
    for left, top in ((160, 180), (160, 260)):
        for y in range(top, top + 50):
            for x in range(left, left + 400):
                edge = x < left + 3 or y < top + 3 or x >= left + 397 or y >= top + 47
                rows[y][x] = 1 if edge else 2
    picture = dvd_spu.decode(
        enc.build_subpicture(
            enc.SpuSpec(0, 0, rows, palette=(0, 1, 2, 3), alpha=(0, 0xF, 0x8, 0xF))
        )
    )
    buttons = (
        vt.ButtonSpec(160, 180, 560, 230, down=2),
        vt.ButtonSpec(160, 260, 560, 310, up=1),
    )
    highlight = dvd_nav.parse_nav_sector(
        vt.build_nav_pack(
            sector=0, start_pts=0, end_pts=1, vobu_sectors=1, buttons=buttons
        )
    ).highlight
    return picture, Navigator(highlight)


@pytest.fixture
def surface(qt_app):
    picture, navigator = two_button_menu()
    made = MenuSurface()
    made.resize(720, 480)
    made.show_menu(
        navigator,
        picture,
        CHAIN_PALETTE,
        highlight_palette=(0, 1, 3, 3),
        highlight_alpha=(0, 0xF, 0xF, 0xF),
    )
    return made


class TestDrawing:
    def test_the_menu_becomes_an_image(self, surface) -> None:
        base = surface._base_overlay()
        assert base is not None
        assert base.width() == 720
        assert base.height() == 480

    def test_only_the_lit_button_is_redrawn(self, surface) -> None:
        # The disc only ever means for one rectangle to change.
        lit = surface._lit_button_overlay(surface.navigator.selected_button)
        assert lit is not None
        image, x, y = lit
        assert (x, y) == (160, 180)
        assert image.width() == 400
        assert image.height() == 50

    def test_the_highlight_moves_with_the_selection(self, surface) -> None:
        first = surface._lit_button_overlay(surface.navigator.selected_button)
        surface.navigator.move("down")
        second = surface._lit_button_overlay(surface.navigator.selected_button)

        assert first[2] == 180
        assert second[2] == 260

    def test_the_lit_and_unlit_colours_actually_differ(self, surface) -> None:
        base = surface._base_overlay()
        lit_image, x, y = surface._lit_button_overlay(
            surface.navigator.selected_button
        )
        # Same pixel, once in the menu's ordinary colours and once lit.
        ordinary = base.pixelColor(300, 205).getRgb()
        highlighted = lit_image.pixelColor(300 - x, 205 - y).getRgb()
        assert ordinary != highlighted

    def test_a_blank_subpicture_draws_nothing(self, qt_app) -> None:
        blank = dvd_spu.decode(
            enc.build_subpicture(enc.SpuSpec(0, 0, [[0] * 40 for _ in range(10)]))
        )
        made = MenuSurface()
        made.show_menu(Navigator(), blank, CHAIN_PALETTE)
        assert made._base_overlay() is None

    def test_with_no_menu_there_is_nothing_to_draw(self, qt_app) -> None:
        made = MenuSurface()
        assert made._base_overlay() is None
        made.clear_menu()
        assert made._base_overlay() is None


class TestCaching:
    def test_the_menu_is_only_composed_once(self, surface) -> None:
        assert surface._base_overlay() is surface._base_overlay()

    def test_each_button_is_only_composed_once(self, surface) -> None:
        button = surface.navigator.selected_button
        assert surface._lit_button_overlay(button) is surface._lit_button_overlay(button)

    def test_a_new_menu_throws_the_old_one_away(self, surface) -> None:
        first = surface._base_overlay()
        picture, navigator = two_button_menu()
        surface.show_menu(navigator, picture, CHAIN_PALETTE)
        assert surface._base_overlay() is not first


class TestTheMouse:
    def test_a_click_arrives_in_the_disc_s_own_coordinates(self, qt_app) -> None:
        # The widget can be any size; the disc's buttons are always in 720x480.
        made = MenuSurface()
        made.resize(1440, 960)
        assert made._to_disc(720, 480) == (360, 240)
        assert made._to_disc(0, 0) == (0, 0)

    def test_a_click_outside_the_picture_is_not_a_click_on_it(self, qt_app) -> None:
        made = MenuSurface()
        made.resize(1440, 480)  # wider than 3:2, so there are black bars
        assert made._to_disc(5, 240) is None
