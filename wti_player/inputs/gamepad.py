"""Gamepad support, through XInput, with no third-party dependency.

XInput is four functions in a DLL Windows already has, so a controller costs
the Player nothing to support and nothing to ship. The reader is a pure
state machine: :meth:`XInputReader.poll` takes a raw pad state and returns the
actions that were *pressed since last time*, which is what makes the whole
thing testable without a controller plugged in.

A d-pad you can hold down has to repeat, or menu navigation feels stuck. The
repeat delay and rate are the ones console menus use.
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass, field

from .actions import PlayerAction

# XInput button bits.
DPAD_UP = 0x0001
DPAD_DOWN = 0x0002
DPAD_LEFT = 0x0004
DPAD_RIGHT = 0x0008
START = 0x0010
BACK = 0x0020
BUTTON_A = 0x1000
BUTTON_B = 0x2000
BUTTON_X = 0x4000
BUTTON_Y = 0x8000
SHOULDER_LEFT = 0x0100
SHOULDER_RIGHT = 0x0200

BUTTON_ACTIONS: dict[int, PlayerAction] = {
    DPAD_UP: PlayerAction.UP,
    DPAD_DOWN: PlayerAction.DOWN,
    DPAD_LEFT: PlayerAction.LEFT,
    DPAD_RIGHT: PlayerAction.RIGHT,
    BUTTON_A: PlayerAction.ACTIVATE,
    BUTTON_B: PlayerAction.TOP_MENU,
    BUTTON_X: PlayerAction.POPUP_MENU,
    BUTTON_Y: PlayerAction.FULLSCREEN,
    START: PlayerAction.PLAY_PAUSE,
    BACK: PlayerAction.STOP,
    SHOULDER_LEFT: PlayerAction.PREVIOUS_CHAPTER,
    SHOULDER_RIGHT: PlayerAction.NEXT_CHAPTER,
}

#: Buttons that repeat while held, and the ones that fire once.
REPEATING = {DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT}

#: Milliseconds before a held direction starts repeating, and between repeats.
REPEAT_DELAY_MS = 400
REPEAT_RATE_MS = 120

#: Anything past this on a stick counts as a direction. XInput's own dead
#: zone constant, which is tuned for exactly this.
STICK_DEADZONE = 7849
STICK_MAX = 32767


@dataclass
class PadState:
    """One sample of a controller, already free of XInput's structs."""

    buttons: int = 0
    stick_x: int = 0
    stick_y: int = 0

    def with_stick_as_dpad(self) -> int:
        """The button mask, plus whatever the left stick is pointing at."""
        buttons = self.buttons
        if self.stick_x <= -STICK_DEADZONE:
            buttons |= DPAD_LEFT
        elif self.stick_x >= STICK_DEADZONE:
            buttons |= DPAD_RIGHT
        if self.stick_y >= STICK_DEADZONE:
            buttons |= DPAD_UP
        elif self.stick_y <= -STICK_DEADZONE:
            buttons |= DPAD_DOWN
        return buttons


@dataclass
class XInputReader:
    """Turns pad samples into actions. Holds no Windows handles."""

    #: Button bit -> the moment it went down.
    _held: dict[int, int] = field(default_factory=dict)
    #: Button bit -> how many repeats have already fired while it is held.
    _repeats: dict[int, int] = field(default_factory=dict)

    def poll(self, state: PadState, now_ms: int) -> list[PlayerAction]:
        """Actions to fire for this sample, at this moment."""
        buttons = state.with_stick_as_dpad()
        fired: list[PlayerAction] = []

        for bit, action in BUTTON_ACTIONS.items():
            down = bool(buttons & bit)
            was_down = bit in self._held
            if down and not was_down:
                self._held[bit] = now_ms
                self._repeats[bit] = 0
                fired.append(action)
            elif down and bit in REPEATING:
                held_for = now_ms - self._held[bit]
                if held_for >= REPEAT_DELAY_MS:
                    steps = 1 + (held_for - REPEAT_DELAY_MS) // REPEAT_RATE_MS
                    if steps > self._repeats.get(bit, 0):
                        self._repeats[bit] = steps
                        fired.append(action)
            elif not down and was_down:
                del self._held[bit]
                self._repeats.pop(bit, None)

        return fired

    def release_all(self) -> None:
        """Forget what is held — used when the pad is unplugged."""
        self._held.clear()
        self._repeats.clear()


class _XInputGamepad(ctypes.Structure):
    _fields_ = [
        ("wButtons", ctypes.c_ushort),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class _XInputState(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_uint), ("Gamepad", _XInputGamepad)]


class GamepadSource:
    """Reads the first connected controller. Absent hardware is not an error."""

    #: In load order — 1_4 ships with Windows 8 and later.
    _DLLS = ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll")

    def __init__(self) -> None:
        self._dll = None
        self._slot: int | None = None
        if sys.platform != "win32":
            return
        for name in self._DLLS:
            try:
                self._dll = ctypes.windll.LoadLibrary(name)  # type: ignore[attr-defined]
                break
            except OSError:
                continue

    @property
    def available(self) -> bool:
        return self._dll is not None

    def read(self) -> PadState | None:
        """The current pad state, or ``None`` when nothing is plugged in."""
        if self._dll is None:
            return None
        state = _XInputState()
        slots = (self._slot,) if self._slot is not None else (0, 1, 2, 3)
        for slot in slots:
            if self._dll.XInputGetState(slot, ctypes.byref(state)) == 0:
                self._slot = slot
                pad = state.Gamepad
                return PadState(
                    buttons=pad.wButtons,
                    stick_x=pad.sThumbLX,
                    stick_y=pad.sThumbLY,
                )
        self._slot = None
        return None
