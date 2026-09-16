"""Keyboard and gamepad, reduced to actions.

Both are pure functions of what was pressed, so both are tested without a
window, a controller, or a disc.
"""

from __future__ import annotations

from wti_player.inputs.actions import PlayerAction
from wti_player.inputs.gamepad import (
    BUTTON_A,
    BUTTON_B,
    DPAD_DOWN,
    DPAD_LEFT,
    REPEAT_DELAY_MS,
    REPEAT_RATE_MS,
    START,
    STICK_DEADZONE,
    PadState,
    XInputReader,
)
from wti_player.inputs.keymap import (
    KEY_DOWN,
    KEY_LEFT,
    KEY_RETURN,
    KEY_RIGHT,
    KEY_SPACE,
    KEY_UP,
    action_for,
)


class TestKeymap:
    def test_arrows_move_the_highlight_inside_a_menu(self) -> None:
        assert action_for(KEY_UP, in_menu=True) is PlayerAction.UP
        assert action_for(KEY_DOWN, in_menu=True) is PlayerAction.DOWN
        assert action_for(KEY_LEFT, in_menu=True) is PlayerAction.LEFT
        assert action_for(KEY_RIGHT, in_menu=True) is PlayerAction.RIGHT

    def test_arrows_seek_and_change_volume_outside_one(self) -> None:
        # Left and right seeking during a film, and moving a highlight in a
        # menu, is what every disc player does. Getting it backwards is the
        # difference between a menu that works and one that feels broken.
        assert action_for(KEY_LEFT, in_menu=False) is PlayerAction.SKIP_BACK
        assert action_for(KEY_RIGHT, in_menu=False) is PlayerAction.SKIP_FORWARD
        assert action_for(KEY_UP, in_menu=False) is PlayerAction.VOLUME_UP
        assert action_for(KEY_DOWN, in_menu=False) is PlayerAction.VOLUME_DOWN

    def test_enter_and_space_mean_the_same_thing_everywhere(self) -> None:
        assert action_for(KEY_RETURN, in_menu=True) is PlayerAction.ACTIVATE
        assert action_for(KEY_RETURN, in_menu=False) is PlayerAction.ACTIVATE
        assert action_for(KEY_SPACE, in_menu=True) is PlayerAction.PLAY_PAUSE

    def test_an_unmapped_key_is_nothing(self) -> None:
        assert action_for(0x5A, in_menu=True) is None


class TestGamepad:
    def test_a_button_fires_once_when_pressed(self) -> None:
        reader = XInputReader()
        assert reader.poll(PadState(buttons=BUTTON_A), 0) == [PlayerAction.ACTIVATE]
        assert reader.poll(PadState(buttons=BUTTON_A), 16) == []
        assert reader.poll(PadState(buttons=BUTTON_A), 32) == []

    def test_releasing_and_pressing_again_fires_again(self) -> None:
        reader = XInputReader()
        reader.poll(PadState(buttons=BUTTON_A), 0)
        reader.poll(PadState(), 16)
        assert reader.poll(PadState(buttons=BUTTON_A), 32) == [PlayerAction.ACTIVATE]

    def test_a_held_direction_repeats_after_a_delay(self) -> None:
        reader = XInputReader()
        assert reader.poll(PadState(buttons=DPAD_DOWN), 0) == [PlayerAction.DOWN]
        assert reader.poll(PadState(buttons=DPAD_DOWN), REPEAT_DELAY_MS - 50) == []
        assert reader.poll(PadState(buttons=DPAD_DOWN), REPEAT_DELAY_MS) == [PlayerAction.DOWN]
        assert reader.poll(PadState(buttons=DPAD_DOWN), REPEAT_DELAY_MS + 10) == []
        assert reader.poll(
            PadState(buttons=DPAD_DOWN), REPEAT_DELAY_MS + REPEAT_RATE_MS
        ) == [PlayerAction.DOWN]

    def test_a_held_action_button_never_repeats(self) -> None:
        reader = XInputReader()
        reader.poll(PadState(buttons=BUTTON_A), 0)
        assert reader.poll(PadState(buttons=BUTTON_A), 5000) == []

    def test_the_left_stick_works_as_a_d_pad(self) -> None:
        reader = XInputReader()
        assert reader.poll(PadState(stick_x=-STICK_DEADZONE - 1), 0) == [PlayerAction.LEFT]

    def test_a_stick_inside_the_dead_zone_is_still(self) -> None:
        reader = XInputReader()
        assert reader.poll(PadState(stick_x=STICK_DEADZONE - 1, stick_y=100), 0) == []

    def test_the_face_buttons_reach_the_menu(self) -> None:
        reader = XInputReader()
        fired = reader.poll(PadState(buttons=BUTTON_B | START), 0)
        assert PlayerAction.TOP_MENU in fired
        assert PlayerAction.PLAY_PAUSE in fired

    def test_unplugging_forgets_what_was_held(self) -> None:
        reader = XInputReader()
        reader.poll(PadState(buttons=DPAD_LEFT), 0)
        reader.release_all()
        assert reader.poll(PadState(buttons=DPAD_LEFT), 10) == [PlayerAction.LEFT]
