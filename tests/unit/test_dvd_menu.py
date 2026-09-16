"""Reading a DVD's menu off the disc: all seven pieces, together.

The parts each have their own tests. These are about the join — that a
folder goes in and a menu that can be drawn and pressed comes out, and that
a disc which is missing any one of the four things a menu is made of degrades
to "no menu" rather than to an exception.
"""

from __future__ import annotations

import pytest

from tests.fixtures.authoring import spu as author
from tests.fixtures.authoring import videots
from wti_player.dvd import menu
from wti_player.engine.base import NavAction
from wti_player.formats import dvd_nav


@pytest.fixture
def menu_dvd(generated_dir):
    path = generated_dir / "dvd_menu_disc"
    if not (path / "VIDEO_TS" / "VTS_01_0.VOB").is_file():
        pytest.skip("run: python tools/make_fixtures.py")
    return path


class TestReadingOne:
    def test_a_disc_with_a_menu_gives_one(self, menu_dvd):
        found = menu.read(menu_dvd)
        assert found is not None
        assert found.kind == "root"
        assert found.name == "Main menu"

    def test_it_has_the_buttons_the_disc_declares(self, menu_dvd):
        found = menu.read(menu_dvd)
        real = [button for button in found.navigator.highlight.buttons if button.is_real]
        assert len(real) == 2

    def test_it_has_the_picture_the_buttons_are_drawn_in(self, menu_dvd):
        found = menu.read(menu_dvd)
        assert found.drawable
        assert found.subpicture.width == 360
        assert found.subpicture.height == 140

    def test_it_has_the_sixteen_colours_the_chain_carries(self, menu_dvd):
        found = menu.read(menu_dvd)
        assert len(found.palette) == 16
        assert len(set(found.palette)) > 1, "a palette of one colour is not a palette"

    def test_a_particular_menu_can_be_asked_for(self, menu_dvd):
        assert menu.read(menu_dvd, kind="title") is not None
        assert menu.read(menu_dvd, kind="audio") is None

    def test_it_names_the_vob_the_engine_has_to_open(self, menu_dvd):
        found = menu.read(menu_dvd)
        assert found.vob.name == "VTS_01_0.VOB"
        assert found.vob.is_file()


class TestPressingIt:
    def test_something_is_lit_to_begin_with(self, menu_dvd):
        found = menu.read(menu_dvd)
        assert found.navigator.active
        assert found.navigator.selected == 1

    def test_down_moves_the_selection(self, menu_dvd):
        found = menu.read(menu_dvd)
        found.navigator.move("down")
        assert found.navigator.selected == 2

    def test_the_pointer_finds_a_button(self, menu_dvd):
        found = menu.read(menu_dvd)
        assert found.navigator.point_at(300, 350)
        assert found.navigator.selected == 2

    def test_a_press_becomes_something_the_player_can_do(self, menu_dvd):
        found = menu.read(menu_dvd)
        action = found.navigator.press(NavAction.ACTIVATE)
        assert action.kind != "unsupported", action.reason
        assert not action.is_nothing

    def test_the_lit_colours_come_out_of_the_chain_palette(self, menu_dvd):
        found = menu.read(menu_dvd)
        lit = found.colours(lit=True)
        assert lit is not None
        assert len(lit) == 4
        # Four RGBA tuples, and at least one of them visible — otherwise the
        # highlight is there and nobody can see it.
        assert all(len(colour) == 4 for colour in lit)
        assert any(colour[3] > 0 for colour in lit)


class TestDiscsThatAreMissingSomething:
    """Each of these is a real way a disc goes wrong. None may raise."""

    def test_a_disc_with_no_menu_tables(self, generated_dir):
        plain = generated_dir / "dvd_disc"
        if not (plain / "VIDEO_TS").is_dir():
            pytest.skip("run: python tools/make_fixtures.py")
        assert menu.read(plain) is None

    def test_a_folder_that_is_not_a_disc(self, tmp_path):
        assert menu.read(tmp_path) is None

    def test_a_path_that_is_not_there(self, tmp_path):
        assert menu.read(tmp_path / "nowhere") is None

    def test_tables_that_point_at_a_vob_that_is_not_there(self, menu_dvd, tmp_path):
        import shutil

        copy = tmp_path / "disc"
        shutil.copytree(menu_dvd, copy)
        (copy / "VIDEO_TS" / "VTS_01_0.VOB").unlink()
        assert menu.read(copy) is None

    def test_a_menu_vob_with_no_buttons_in_it(self, menu_dvd, tmp_path):
        import shutil

        copy = tmp_path / "disc"
        shutil.copytree(menu_dvd, copy)
        vob = copy / "VIDEO_TS" / "VTS_01_0.VOB"
        # A NAV pack with no highlight is what a *title* VOB carries.
        blank = videots.build_nav_pack(
            sector=0, start_pts=0, end_pts=90_000, vobu_sectors=4
        )
        vob.write_bytes(blank + vob.read_bytes()[2048:])
        assert menu.read(copy) is None

    def test_a_menu_with_buttons_but_no_picture_is_still_a_menu(self, tmp_path):
        """Invisible buttons, but a remote still works. Better than nothing."""
        disc = tmp_path / "disc"
        chain = videots.TitleSpec(cells=(videots.CellSpec(4000, 0, 3),))
        nav = videots.build_nav_pack(
            sector=0,
            start_pts=0,
            end_pts=4 * 90_000,
            vobu_sectors=4,
            buttons=(
                videots.ButtonSpec(x_start=10, y_start=10, x_end=200, y_end=60),
            ),
        )
        vob = tmp_path / "menu.vob"
        vob.write_bytes(nav + author.sector_with(b""))
        title_vob = tmp_path / "title.vob"
        title_vob.write_bytes(b"\x00" * 2048 * 4)

        videots.write_video_ts(
            disc, title_vob,
            title=videots.TitleSpec(cells=(videots.CellSpec(1000, 0, 3),)),
            menus={"root": chain}, menu_vob=vob,
        )
        found = menu.read(disc)
        assert found is not None
        assert not found.drawable
        assert found.navigator.active


class TestTheInspector:
    def test_it_says_what_a_good_disc_has(self, menu_dvd):
        report = "\n".join(menu.describe(menu_dvd))
        assert "menu chain" in report
        assert "with a palette" in report
        assert "button(s)" in report
        assert "subpicture 360x140" in report
        assert "NO " not in report

    def test_it_says_what_a_plain_disc_does_not_have(self, generated_dir):
        plain = generated_dir / "dvd_disc"
        if not (plain / "VIDEO_TS").is_dir():
            pytest.skip("run: python tools/make_fixtures.py")
        assert menu.describe(plain) == ["No menu tables on this disc."]

    def test_it_never_raises_on_rubbish(self, tmp_path):
        (tmp_path / "VIDEO_TS").mkdir()
        (tmp_path / "VIDEO_TS" / "VTS_01_0.IFO").write_bytes(b"not an IFO" * 100)
        assert menu.describe(tmp_path)  # says something, rather than throwing


class TestTheColourTable:
    """``btn_coli``: the four palette indices a lit button uses."""

    def test_the_nibbles_come_out_in_slot_order(self):
        # 0x0F00_FF00: palette e2=0 e1=f p=0 bg=0, alpha e2=f e1=f p=0 bg=0
        one = dvd_nav._colour_set(0x0F00_FF00, 0x0E00_FF00)
        assert one.selected_palette == (0, 0, 0x0F, 0)
        assert one.selected_alpha == (0, 0, 0x0F, 0x0F)
        assert one.is_set

    def test_a_group_a_disc_left_empty_is_not_used(self):
        assert not dvd_nav._colour_set(0, 0).is_set

    def test_a_button_picks_its_own_group(self, menu_dvd):
        found = menu.read(menu_dvd)
        highlight = found.navigator.highlight
        assert highlight.colours_for(highlight.button(1)) is not None

    def test_no_button_means_no_colours(self, menu_dvd):
        found = menu.read(menu_dvd)
        assert found.navigator.highlight.colours_for(None) is None
