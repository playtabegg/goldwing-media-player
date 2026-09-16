"""Which key does what.

Kept as data, and kept away from Qt: the map is keyed by Qt's key codes but
resolving one is a dictionary lookup, so the whole keyboard can be tested
without a window on screen.
"""

from __future__ import annotations

from .actions import PlayerAction

# Qt.Key values, written out so this module does not import PyQt6 at all.
KEY_LEFT = 0x01000012
KEY_UP = 0x01000013
KEY_RIGHT = 0x01000014
KEY_DOWN = 0x01000015
KEY_RETURN = 0x01000004
KEY_ENTER = 0x01000005
KEY_SPACE = 0x20
KEY_ESCAPE = 0x01000000
KEY_F = 0x46
KEY_M = 0x4D
KEY_E = 0x45
KEY_S = 0x53
KEY_P = 0x50
KEY_N = 0x4E
KEY_B = 0x42
KEY_T = 0x54
KEY_PLUS = 0x2B
KEY_EQUAL = 0x3D
KEY_MINUS = 0x2D
KEY_PAGE_UP = 0x01000016
KEY_PAGE_DOWN = 0x01000017
KEY_MEDIA_PLAY = 0x01000080
KEY_MEDIA_STOP = 0x01000081

KEYMAP: dict[int, PlayerAction] = {
    KEY_UP: PlayerAction.UP,
    KEY_DOWN: PlayerAction.DOWN,
    KEY_LEFT: PlayerAction.LEFT,
    KEY_RIGHT: PlayerAction.RIGHT,
    KEY_RETURN: PlayerAction.ACTIVATE,
    KEY_ENTER: PlayerAction.ACTIVATE,
    KEY_SPACE: PlayerAction.PLAY_PAUSE,
    KEY_MEDIA_PLAY: PlayerAction.PLAY_PAUSE,
    KEY_MEDIA_STOP: PlayerAction.STOP,
    KEY_ESCAPE: PlayerAction.LEAVE_FULLSCREEN,
    KEY_F: PlayerAction.FULLSCREEN,
    KEY_M: PlayerAction.TOP_MENU,
    KEY_P: PlayerAction.POPUP_MENU,
    KEY_E: PlayerAction.EJECT,
    KEY_S: PlayerAction.STOP,
    KEY_N: PlayerAction.NEXT_CHAPTER,
    KEY_B: PlayerAction.PREVIOUS_CHAPTER,
    # The panel's only other way in is a button on the top bar, and full
    # screen takes the top bar away.
    KEY_T: PlayerAction.TOGGLE_PANEL,
    KEY_PAGE_UP: PlayerAction.PREVIOUS_CHAPTER,
    KEY_PAGE_DOWN: PlayerAction.NEXT_CHAPTER,
    KEY_PLUS: PlayerAction.VOLUME_UP,
    KEY_EQUAL: PlayerAction.VOLUME_UP,
    KEY_MINUS: PlayerAction.VOLUME_DOWN,
}

#: Left and right seek when there is no menu to move around in.
SEEK_INSTEAD_OF_NAVIGATE = {
    PlayerAction.LEFT: PlayerAction.SKIP_BACK,
    PlayerAction.RIGHT: PlayerAction.SKIP_FORWARD,
}


def action_for(key: int, *, in_menu: bool) -> PlayerAction | None:
    """What this key means right now.

    Left and right are the only keys whose meaning depends on context: in a
    menu they move the highlight, and everywhere else they skip. Getting that
    backwards is the difference between a menu that feels broken and one that
    does not, so it is decided here and tested.
    """
    action = KEYMAP.get(key)
    if action is None:
        return None
    if not in_menu and action in SEEK_INSTEAD_OF_NAVIGATE:
        return SEEK_INSTEAD_OF_NAVIGATE[action]
    if not in_menu and action in (PlayerAction.UP, PlayerAction.DOWN):
        return PlayerAction.VOLUME_UP if action is PlayerAction.UP else PlayerAction.VOLUME_DOWN
    return action


def describe(action: PlayerAction) -> str:
    """The key someone would press, for a shortcut hint."""
    for key, mapped in KEYMAP.items():
        if mapped is action:
            return _KEY_NAMES.get(key, "")
    return ""


_KEY_NAMES = {
    KEY_SPACE: "Space",
    KEY_F: "F",
    KEY_M: "M",
    KEY_P: "P",
    KEY_E: "E",
    KEY_S: "S",
    KEY_N: "N",
    KEY_B: "B",
    KEY_ESCAPE: "Esc",
}
