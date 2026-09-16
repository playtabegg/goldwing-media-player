"""One set of actions, whatever pressed them.

Keyboard, mouse and gamepad all reduce to this before anything else sees
them, so "keyboard, mouse and gamepad all drive the menus" is one code path
rather than three that drift apart.
"""

from __future__ import annotations

from enum import Enum

from ..engine.base import NavAction


class PlayerAction(Enum):
    # Menu navigation — these map straight onto the engine's NavAction.
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    ACTIVATE = "activate"
    TOP_MENU = "top-menu"
    POPUP_MENU = "popup-menu"

    # Transport.
    PLAY_PAUSE = "play-pause"
    STOP = "stop"
    SKIP_BACK = "skip-back"
    SKIP_FORWARD = "skip-forward"
    PREVIOUS_CHAPTER = "previous-chapter"
    NEXT_CHAPTER = "next-chapter"
    VOLUME_UP = "volume-up"
    VOLUME_DOWN = "volume-down"
    MUTE = "mute"

    # The shell.
    FULLSCREEN = "fullscreen"
    LEAVE_FULLSCREEN = "leave-fullscreen"
    TOGGLE_PANEL = "toggle-panel"
    EJECT = "eject"

    @property
    def is_navigation(self) -> bool:
        return self in _NAVIGATION

    def to_nav(self) -> NavAction | None:
        return _NAVIGATION.get(self)


_NAVIGATION: dict[PlayerAction, NavAction] = {
    PlayerAction.UP: NavAction.UP,
    PlayerAction.DOWN: NavAction.DOWN,
    PlayerAction.LEFT: NavAction.LEFT,
    PlayerAction.RIGHT: NavAction.RIGHT,
    PlayerAction.ACTIVATE: NavAction.ACTIVATE,
    PlayerAction.TOP_MENU: NavAction.TOP_MENU,
    PlayerAction.POPUP_MENU: NavAction.POPUP_MENU,
}

#: How far the skip keys move, in milliseconds.
SKIP_MS = 10_000
VOLUME_STEP = 5
