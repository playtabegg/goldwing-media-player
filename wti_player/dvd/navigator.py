"""The DVD navigator: what a menu does when somebody presses a button.

This is the piece that makes a DVD menu a menu rather than a picture. It
holds which button is lit, moves the selection when somebody presses a
direction, and turns an activation into a plain instruction the player can
carry out — play this title, jump to that chapter, show the root menu, resume
where we were.

It renders nothing and plays nothing. Everything it knows comes in as data
and everything it decides goes out as an :class:`Action`, which is what makes
a DVD's whole navigation layer testable without a disc, a window or a codec.

What it deliberately does *not* do is guess. An instruction the decoder does
not recognise comes back as :attr:`Action.kind` ``"unsupported"`` with the
reason attached, because sending somebody to the wrong part of a disc is
worse than telling them the disc does something we do not follow.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..engine.base import NavAction
from ..formats import dvd_vm as vm
from ..formats.dvd_nav import NO_BUTTON, Button, Highlight

#: What the navigator can ask the player to do.
PLAY_TITLE = "play-title"
PLAY_CHAPTER = "play-chapter"
SHOW_MENU = "show-menu"
RESUME = "resume"
STOP = "stop"
NOTHING = "nothing"
UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class Action:
    """One thing for the player to do, in the player's own terms."""

    kind: str = NOTHING
    title: int = 0
    chapter: int = 0
    menu: str = ""
    title_set: int = 0
    #: Why, when ``kind`` is ``unsupported`` — fit to show a person.
    reason: str = ""

    @property
    def is_nothing(self) -> bool:
        return self.kind == NOTHING


@dataclass
class Navigator:
    """The menu currently on screen, and what pressing things does to it."""

    highlight: Highlight | None = None
    registers: vm.Registers = field(default_factory=vm.Registers)
    #: Which title set the menu belongs to, for commands that omit it.
    title_set: int = 1
    _selected: int = 0

    def __post_init__(self) -> None:
        if self.highlight is not None:
            self.show(self.highlight)

    # -- what is on screen -------------------------------------------------

    def show(self, highlight: Highlight | None) -> Action:
        """A new menu came up. Returns any action its default button forces."""
        self.highlight = highlight
        if highlight is None:
            self._selected = NO_BUTTON
            return Action()

        first = highlight.selected_button
        if not self._is_selectable(first):
            first = next(
                (button.number for button in highlight.buttons if button.is_real),
                NO_BUTTON,
            )
        self._selected = first
        self._record_highlight()

        if highlight.activated_button and self._is_selectable(highlight.activated_button):
            self._selected = highlight.activated_button
            return self.activate()
        return Action()

    def clear(self) -> None:
        self.highlight = None
        self._selected = NO_BUTTON

    def _record_highlight(self) -> None:
        """SPRM 8 holds the lit button in its top six bits: number * 1024."""
        self.registers.set(
            vm.GPRM_COUNT + vm.SPRM_HIGHLIGHTED_BUTTON,
            (self._selected * vm.SPRM_BUTTON_SCALE) & 0xFFFF,
        )

    @property
    def active(self) -> bool:
        return self.highlight is not None and self.highlight.has_buttons

    @property
    def selected(self) -> int:
        """The lit button, 1-based. Zero when nothing is lit."""
        return self._selected

    @property
    def selected_button(self) -> Button | None:
        if self.highlight is None:
            return None
        return self.highlight.button(self._selected)

    def _is_selectable(self, number: int) -> bool:
        if self.highlight is None or number == NO_BUTTON:
            return False
        button = self.highlight.button(number)
        return button is not None and button.is_real

    # -- moving around -----------------------------------------------------

    def move(self, direction: str) -> Action:
        """Move the selection. Returns an action if the button acts on arrival."""
        button = self.selected_button
        if button is None:
            return Action()
        target = button.neighbour(direction)
        if not self._is_selectable(target) or target == self._selected:
            # A menu's edges are walls, not wraps — that is how discs author
            # them, and moving somewhere invisible would look like a bug.
            return Action()
        self._selected = target
        self._record_highlight()

        arrived = self.selected_button
        if arrived is not None and arrived.auto_action:
            return self.activate()
        return Action()

    def press(self, action: NavAction) -> Action:
        """Route one of the Player's navigation actions to the menu."""
        if not self.active:
            return Action()
        if action is NavAction.UP:
            return self.move("up")
        if action is NavAction.DOWN:
            return self.move("down")
        if action is NavAction.LEFT:
            return self.move("left")
        if action is NavAction.RIGHT:
            return self.move("right")
        if action is NavAction.ACTIVATE:
            return self.activate()
        return Action()

    def point_at(self, x: int, y: int) -> bool:
        """Move the selection to whatever is under the cursor. True if it moved."""
        if self.highlight is None:
            return False
        button = self.highlight.at(x, y)
        if button is None or button.number == self._selected:
            return False
        self._selected = button.number
        self._record_highlight()
        return True

    def click_at(self, x: int, y: int) -> Action:
        """Press whatever is under the cursor."""
        if self.highlight is None:
            return Action()
        button = self.highlight.at(x, y)
        if button is None:
            return Action()
        self._selected = button.number
        return self.activate()

    # -- doing what a button says -----------------------------------------

    def activate(self) -> Action:
        button = self.selected_button
        if button is None:
            return Action()
        return self.run(button.command)

    def run(self, command: bytes) -> Action:
        """Execute one DVD command, as far as a player needs to care."""
        instruction = vm.decode(command)
        return self._act_on(instruction)

    def _act_on(self, instruction: vm.Instruction) -> Action:
        op = instruction.op

        if op is vm.Op.JUMP_TITLE:
            return Action(kind=PLAY_TITLE, title=instruction.target)
        if op is vm.Op.JUMP_VTS_TITLE:
            return Action(
                kind=PLAY_TITLE, title=instruction.target, title_set=self.title_set
            )
        if op is vm.Op.JUMP_VTS_PTT:
            return Action(
                kind=PLAY_CHAPTER,
                title=instruction.target,
                chapter=instruction.second,
                title_set=self.title_set,
            )
        if op in (vm.Op.LINK_PTTN, vm.Op.LINK_PGN):
            return Action(kind=PLAY_CHAPTER, chapter=instruction.target)

        if op in (vm.Op.JUMP_SS_VMGM_MENU, vm.Op.CALL_SS_VMGM_MENU):
            return Action(kind=SHOW_MENU, menu=instruction.menu or "root")
        if op in (vm.Op.JUMP_SS_VTSM, vm.Op.CALL_SS_VTSM):
            return Action(
                kind=SHOW_MENU,
                menu=instruction.menu or "root",
                title_set=instruction.title_set or self.title_set,
            )
        if op is vm.Op.LINK_TOP_PGC:
            return Action(kind=SHOW_MENU, menu="root")

        if op in (vm.Op.LINK_RSM, vm.Op.CALL_SS_FP, vm.Op.JUMP_SS_FP):
            return Action(kind=RESUME)
        if op is vm.Op.EXIT:
            return Action(kind=STOP)

        if op in (vm.Op.NOP, vm.Op.LINK_NO_LINK, vm.Op.SET_GPRM, vm.Op.SET_SPRM):
            if op in (vm.Op.SET_GPRM, vm.Op.SET_SPRM):
                register = instruction.target + (
                    vm.GPRM_COUNT if op is vm.Op.SET_SPRM else 0
                )
                try:
                    value = _apply_set(
                        instruction.set_op, self.registers.get(register), instruction.second
                    )
                except ZeroDivisionError:
                    return Action(
                        kind=UNSUPPORTED,
                        reason=(
                            "This disc's menu divides a register by zero"
                            f" ({instruction.describe()})."
                        ),
                    )
                self.registers.set(register, value)
                if instruction.link is not None:
                    # The register write is bookkeeping; the link is what
                    # the button was for.
                    return self._act_on(instruction.link)
            return Action()

        return Action(
            kind=UNSUPPORTED,
            reason=(
                "This disc's menu does something GoldWing does not follow yet"
                f" ({instruction.describe()})."
            ),
        )


def _apply_set(operator: str, current: int, operand: int) -> int:
    """One register set operation, on sixteen-bit values."""
    if operator == "=":
        result = operand
    elif operator == "+=":
        result = current + operand
    elif operator == "-=":
        result = current - operand
    elif operator == "*=":
        result = current * operand
    elif operator == "/=":
        result = current // operand
    elif operator == "%=":
        result = current % operand
    elif operator == "&=":
        result = current & operand
    elif operator == "|=":
        result = current | operand
    elif operator == "^=":
        result = current ^ operand
    else:
        result = operand
    return result & 0xFFFF
