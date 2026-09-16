"""Pressing buttons on a DVD menu, with no disc, no window and no codec.

The navigator takes a menu as data and gives back what the player should do,
which makes a DVD's whole navigation layer testable in milliseconds.
"""

from __future__ import annotations

from tests.fixtures.authoring import videots as vt
from wti_player.dvd import navigator as nav
from wti_player.engine.base import NavAction
from wti_player.formats import dvd_nav


def command(*byte_values: int) -> bytes:
    return bytes(byte_values).ljust(8, b"\x00")


PLAY_TITLE_1 = command(0x30, 0x02, 0, 0, 0, 1)
PLAY_TITLE_2 = command(0x30, 0x02, 0, 0, 0, 2)
RESUME = command(0x20, 0x01, 0, 0, 0, 0, 0, 0x10)
ROOT_MENU = command(0x30, 0x06, 0x00, 0x00, 0x00, 0x43)
NOT_UNDERSTOOD = command(0xE0, 0xFF, 0xFF, 0xFF)


def menu(*buttons: vt.ButtonSpec, selected: int = 1, activated: int = 0):
    sector = vt.build_nav_pack(
        sector=0,
        start_pts=0,
        end_pts=90_000,
        vobu_sectors=8,
        buttons=buttons,
        selected=selected,
    )
    highlight = dvd_nav.parse_nav_sector(sector).highlight
    if activated:
        highlight = dvd_nav.Highlight(
            start_pts=highlight.start_pts,
            end_pts=highlight.end_pts,
            selected_button=highlight.selected_button,
            activated_button=activated,
            buttons=highlight.buttons,
        )
    return highlight


def two_button_menu(**kwargs):
    return menu(
        vt.ButtonSpec(100, 100, 400, 150, down=2, command=PLAY_TITLE_1),
        vt.ButtonSpec(100, 200, 400, 250, up=1, command=PLAY_TITLE_2),
        **kwargs,
    )


class TestWhatIsLit:
    def test_the_disc_says_which_button_starts_lit(self) -> None:
        navigator = nav.Navigator(two_button_menu(selected=2))
        assert navigator.selected == 2
        assert navigator.active

    def test_a_disc_that_names_no_button_lights_the_first_real_one(self) -> None:
        navigator = nav.Navigator(two_button_menu(selected=0))
        assert navigator.selected == 1

    def test_with_no_menu_nothing_is_lit(self) -> None:
        navigator = nav.Navigator()
        assert not navigator.active
        assert navigator.selected == dvd_nav.NO_BUTTON
        assert navigator.press(NavAction.DOWN).is_nothing


class TestMoving:
    def test_down_and_up_follow_the_disc_s_own_links(self) -> None:
        navigator = nav.Navigator(two_button_menu())

        assert navigator.press(NavAction.DOWN).is_nothing
        assert navigator.selected == 2
        assert navigator.press(NavAction.UP).is_nothing
        assert navigator.selected == 1

    def test_the_edges_are_walls_not_wraps(self) -> None:
        # Discs author menus this way. Wrapping would look like a bug to
        # anyone who has used a DVD player.
        navigator = nav.Navigator(two_button_menu())

        navigator.press(NavAction.UP)
        assert navigator.selected == 1
        navigator.press(NavAction.DOWN)
        navigator.press(NavAction.DOWN)
        assert navigator.selected == 2

    def test_a_direction_with_no_neighbour_does_nothing(self) -> None:
        navigator = nav.Navigator(two_button_menu())
        assert navigator.press(NavAction.LEFT).is_nothing
        assert navigator.selected == 1

    def test_the_highlighted_button_is_kept_in_the_disc_s_register_scaled(self) -> None:
        from wti_player.formats import dvd_vm as vm

        navigator = nav.Navigator(two_button_menu())
        navigator.press(NavAction.DOWN)
        assert navigator.registers.system[vm.SPRM_HIGHLIGHTED_BUTTON] == 2 * vm.SPRM_BUTTON_SCALE  # the spec's button * 1024


class TestActivating:
    def test_pressing_a_button_plays_what_it_says(self) -> None:
        navigator = nav.Navigator(two_button_menu())

        action = navigator.press(NavAction.ACTIVATE)
        assert action.kind == nav.PLAY_TITLE
        assert action.title == 1

        navigator.press(NavAction.DOWN)
        assert navigator.press(NavAction.ACTIVATE).title == 2

    def test_a_chapter_button(self) -> None:
        navigator = nav.Navigator(
            menu(
                vt.ButtonSpec(
                    0, 0, 10, 10, command=command(0x30, 0x05, 0x00, 0x07, 0x00, 0x02)
                )
            )
        )
        action = navigator.press(NavAction.ACTIVATE)
        assert action.kind == nav.PLAY_CHAPTER
        assert (action.title, action.chapter) == (2, 7)

    def test_a_button_that_goes_back_to_the_root_menu(self) -> None:
        navigator = nav.Navigator(menu(vt.ButtonSpec(0, 0, 10, 10, command=ROOT_MENU)))
        action = navigator.press(NavAction.ACTIVATE)
        assert action.kind == nav.SHOW_MENU
        assert action.menu == "root"

    def test_a_resume_button(self) -> None:
        navigator = nav.Navigator(menu(vt.ButtonSpec(0, 0, 10, 10, command=RESUME)))
        assert navigator.press(NavAction.ACTIVATE).kind == nav.RESUME

    def test_an_auto_action_button_fires_on_arrival(self) -> None:
        navigator = nav.Navigator(
            menu(
                vt.ButtonSpec(0, 0, 10, 10, down=2, command=PLAY_TITLE_1),
                vt.ButtonSpec(0, 20, 10, 30, up=1, auto_action=True, command=PLAY_TITLE_2),
            )
        )
        action = navigator.press(NavAction.DOWN)
        assert action.kind == nav.PLAY_TITLE
        assert action.title == 2

    def test_a_menu_whose_default_button_acts_immediately(self) -> None:
        navigator = nav.Navigator()
        action = navigator.show(two_button_menu(activated=2))
        assert action.kind == nav.PLAY_TITLE
        assert action.title == 2


class TestTheMouse:
    def test_hovering_moves_the_highlight(self) -> None:
        navigator = nav.Navigator(two_button_menu())

        assert navigator.point_at(200, 220)
        assert navigator.selected == 2
        assert not navigator.point_at(200, 220)  # already there
        assert not navigator.point_at(5, 5)  # nothing there

    def test_clicking_presses_what_is_under_the_cursor(self) -> None:
        navigator = nav.Navigator(two_button_menu())

        action = navigator.click_at(200, 220)
        assert action.kind == nav.PLAY_TITLE
        assert action.title == 2
        assert navigator.click_at(5, 5).is_nothing


class TestRefusingToGuess:
    def test_an_instruction_we_do_not_follow_is_said_out_loud(self) -> None:
        navigator = nav.Navigator(
            menu(vt.ButtonSpec(0, 0, 10, 10, command=NOT_UNDERSTOOD))
        )
        action = navigator.press(NavAction.ACTIVATE)

        assert action.kind == nav.UNSUPPORTED
        assert action.reason
        assert action.reason[0].isupper()
        assert action.reason.endswith(".")
        assert "stack" not in action.reason.lower()

    def test_a_do_nothing_button_does_nothing(self) -> None:
        navigator = nav.Navigator(menu(vt.ButtonSpec(0, 0, 10, 10)))
        assert navigator.press(NavAction.ACTIVATE).is_nothing
