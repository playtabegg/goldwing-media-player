"""The DVD virtual machine's instruction set, decoded.

Every DVD carries little programs: eight bytes each, attached to program
chains and to menu buttons. Press a button on a DVD menu and what happens is
one of these running. A player that wants to show DVD menus without a
third-party navigator has to understand them.

This is the decoder. It turns eight bytes into a named instruction with its
operands, and it says plainly when it does not recognise one rather than
guessing — a mis-decoded jump would send someone to the wrong part of a disc,
which is worse than saying "this disc does something we do not follow".

The bit numbering follows libdvdnav: the eight bytes are one 64-bit
big-endian word, bit 63 is the top bit of the first byte, and a field is
named by the bit it *ends* at and how wide it is.

Every field offset here was checked against libdvdnav's own ``vmcmd.c``
rather than trusted to memory, which caught three that were wrong: the jump
family's operation 1 is Exit and not a jump, JumpSS VTSM names its title set
and title in seven bits each rather than eight, and call sub-instruction 2 is
a title-set menu rather than a chain in the disc menu domain. A player that
gets those wrong sends somebody to the wrong part of a disc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

#: How many general-purpose and system registers a DVD has.
GPRM_COUNT = 16
SPRM_COUNT = 24

#: System registers a player has to answer for. There are more; these are the
#: ones a menu actually reads.
SPRM_AUDIO_STREAM = 1
SPRM_SUBTITLE_STREAM = 2
SPRM_ANGLE = 3
SPRM_TITLE = 4
SPRM_VTS_TITLE = 5
SPRM_PGC = 6
SPRM_PTT = 7
SPRM_HIGHLIGHTED_BUTTON = 8
#: SPRM 8 stores the button number in its top six bits (the specification's
#: ``button * 1024``); a menu that reads it back compares against that.
SPRM_BUTTON_SCALE = 1024
SPRM_NAV_TIMER = 9
SPRM_PARENTAL_LEVEL = 13
SPRM_PLAYER_CONFIG = 16


class Op(Enum):
    """What an instruction does, in words a player can act on."""

    NOP = "nop"
    GOTO = "goto"
    BREAK = "break"
    EXIT = "exit"
    SET_PARENTAL = "set-parental-level"

    LINK_NO_LINK = "link-nothing"
    LINK_TOP_CELL = "link-top-cell"
    LINK_NEXT_CELL = "link-next-cell"
    LINK_PREV_CELL = "link-previous-cell"
    LINK_TOP_PROGRAM = "link-top-program"
    LINK_NEXT_PROGRAM = "link-next-program"
    LINK_PREV_PROGRAM = "link-previous-program"
    LINK_TOP_PGC = "link-top-chain"
    LINK_NEXT_PGC = "link-next-chain"
    LINK_PREV_PGC = "link-previous-chain"
    LINK_GO_UP_PGC = "link-parent-chain"
    LINK_TAIL_PGC = "link-chain-end"
    LINK_RSM = "resume"
    LINK_PGCN = "link-chain"
    LINK_PTTN = "link-chapter"
    LINK_PGN = "link-program"
    LINK_CN = "link-cell"

    JUMP_TITLE = "jump-title"
    JUMP_VTS_TITLE = "jump-title-in-set"
    JUMP_VTS_PTT = "jump-chapter-in-set"
    JUMP_SS_FP = "jump-first-play-domain"
    JUMP_SS_VMGM_MENU = "jump-disc-menu"
    JUMP_SS_VTSM = "jump-title-set-menu"
    JUMP_SS_VMGM_PGC = "jump-disc-chain"
    CALL_SS_FP = "call-first-play-domain"
    CALL_SS_VMGM_MENU = "call-disc-menu"
    CALL_SS_VTSM = "call-title-set-menu"
    CALL_SS_VMGM_PGC = "call-disc-chain"

    SET_GPRM = "set-register"
    SET_SPRM = "set-system-register"
    UNKNOWN = "unknown"

    @property
    def is_jump(self) -> bool:
        return self.name.startswith(("JUMP_", "CALL_"))

    @property
    def is_link(self) -> bool:
        return self.name.startswith("LINK_")


#: Which menu a JumpSS_VTSM or JumpSS_VMGM_MENU is asking for.
MENU_NAMES = {
    2: "title",
    3: "root",
    4: "subtitle",
    5: "audio",
    6: "angle",
    7: "chapter",
}

_LINK_SUB = {
    0: Op.LINK_NO_LINK,
    1: Op.LINK_TOP_CELL,
    2: Op.LINK_NEXT_CELL,
    3: Op.LINK_PREV_CELL,
    5: Op.LINK_TOP_PROGRAM,
    6: Op.LINK_NEXT_PROGRAM,
    7: Op.LINK_PREV_PROGRAM,
    9: Op.LINK_TOP_PGC,
    10: Op.LINK_NEXT_PGC,
    11: Op.LINK_PREV_PGC,
    12: Op.LINK_GO_UP_PGC,
    13: Op.LINK_TAIL_PGC,
    16: Op.LINK_RSM,
}


@dataclass(frozen=True)
class Instruction:
    """One decoded DVD command."""

    op: Op
    #: What the operation acts on: a title, a chain, a chapter, a menu.
    target: int = 0
    #: A second operand, where one applies — a chapter within a title, say.
    second: int = 0
    #: The button to highlight once the jump lands. Zero means "leave it".
    button: int = 0
    #: For a menu jump, which menu — "root", "title", "chapter"...
    menu: str = ""
    #: The title set a JumpVTS_* refers to, when the instruction names one.
    title_set: int = 0
    raw: bytes = b""
    #: Set when the instruction was not recognised, so a caller can refuse
    #: rather than do the wrong thing.
    note: str = ""
    #: For a set-then-link command (types 2 and 3): the link half, decoded.
    #: The register write is this instruction; the link is what a player
    #: then acts on. ``None`` when the command only sets.
    link: Instruction | None = None
    #: For a register set: what to do with the operand. ``=`` assigns; the
    #: arithmetic forms (``+=`` ...) fold it into the register's value.
    set_op: str = "="

    @property
    def understood(self) -> bool:
        return self.op is not Op.UNKNOWN

    def describe(self) -> str:
        own = self._describe_own()
        if self.link is not None:
            return f"{own} then {self.link.describe()}"
        return own

    def _describe_own(self) -> str:
        parts = [self.op.value]
        if self.menu:
            parts.append(f"“{self.menu}”")
        if self.title_set:
            parts.append(f"set {self.title_set}")
        if self.target:
            parts.append(str(self.target))
        if self.second:
            parts.append(f"/{self.second}")
        if self.button:
            parts.append(f"button {self.button}")
        return " ".join(parts)


def _word(command: bytes) -> int:
    return int.from_bytes(command.ljust(8, b"\x00")[:8], "big")


def getbits(word: int, start: int, count: int) -> int:
    """``count`` bits of a 64-bit word, ending at bit ``start`` (63 is the top)."""
    if count <= 0 or start - count + 1 < 0:
        return 0
    return (word >> (start - count + 1)) & ((1 << count) - 1)


#: The general-register set operations in bits 59..56 (libdvdnav's
#: ``set_op_table``). 2 (swap) and 8 (random) need a second register and
#: are not evaluated; the rest fold an immediate into the register.
_SET_OPS = {1: "=", 3: "+=", 4: "-=", 5: "*=", 6: "/=", 7: "%=", 9: "&=", 10: "|=", 11: "^="}

#: The comparison a link, set-then-link or jump can carry in bits 54..52:
#: 0 is none; 1..7 are &, ==, !=, >=, >, <=, <.
_COMPARISONS = {1: "&", 2: "==", 3: "!=", 4: ">=", 5: ">", 6: "<=", 7: "<"}


def _refuse_conditional(word: int, raw: bytes) -> Instruction | None:
    """An instruction guarded by a comparison we do not evaluate, or None.

    Types 1, 2 and 3 can make their link conditional on a register test in
    bits 54..52. This decoder does not evaluate the test: the operand
    layout differs by type and a wrong guess sends somebody to the wrong
    part of a disc. Until it does, a guarded instruction is refused as not
    understood, and the navigator says so, rather than run unconditionally
    (which is what happened before 28 Aug 2026: ``if (GPRM1 == 3) LinkPTTN
    4`` became a plain ``link-chapter 4``).
    """
    comparison = getbits(word, 54, 3)
    if comparison == 0:
        return None
    return Instruction(
        op=Op.UNKNOWN,
        raw=raw,
        note=f"conditional ({_COMPARISONS.get(comparison, comparison)}) is not evaluated",
    )


def _decode_link(word: int, raw: bytes) -> Instruction:
    """The link family: staying inside the current program chain, mostly."""
    operation = getbits(word, 51, 4)
    button = getbits(word, 15, 6)
    if operation == 1:
        sub = getbits(word, 7, 8)
        return Instruction(
            op=_LINK_SUB.get(sub, Op.UNKNOWN),
            button=button,
            raw=raw,
            note="" if sub in _LINK_SUB else f"link sub-instruction {sub}",
        )
    if operation == 4:
        return Instruction(op=Op.LINK_PGCN, target=getbits(word, 14, 15), raw=raw)
    if operation == 5:
        return Instruction(
            op=Op.LINK_PTTN, target=getbits(word, 9, 10), button=button, raw=raw
        )
    if operation == 6:
        return Instruction(
            op=Op.LINK_PGN, target=getbits(word, 6, 7), button=button, raw=raw
        )
    if operation == 7:
        return Instruction(
            op=Op.LINK_CN, target=getbits(word, 7, 8), button=button, raw=raw
        )
    return Instruction(op=Op.UNKNOWN, raw=raw, note=f"link operation {operation}")


def _decode_jump(word: int, raw: bytes) -> Instruction:
    """The jump and call family: leaving for another title or another menu."""
    operation = getbits(word, 51, 4)
    if operation == 1:
        return Instruction(op=Op.EXIT, raw=raw)
    if operation == 2:
        return Instruction(op=Op.JUMP_TITLE, target=getbits(word, 22, 7), raw=raw)
    if operation == 3:
        return Instruction(op=Op.JUMP_VTS_TITLE, target=getbits(word, 22, 7), raw=raw)
    if operation == 5:
        return Instruction(
            op=Op.JUMP_VTS_PTT,
            target=getbits(word, 22, 7),
            second=getbits(word, 41, 10),
            raw=raw,
        )
    if operation == 6:
        sub = getbits(word, 23, 2)
        if sub == 0:
            return Instruction(op=Op.JUMP_SS_FP, raw=raw)
        if sub == 1:
            return Instruction(
                op=Op.JUMP_SS_VMGM_MENU,
                target=getbits(word, 19, 4),
                menu=MENU_NAMES.get(getbits(word, 19, 4), ""),
                raw=raw,
            )
        if sub == 2:
            return Instruction(
                op=Op.JUMP_SS_VTSM,
                title_set=getbits(word, 30, 7),
                second=getbits(word, 38, 7),
                target=getbits(word, 19, 4),
                menu=MENU_NAMES.get(getbits(word, 19, 4), ""),
                raw=raw,
            )
        return Instruction(op=Op.JUMP_SS_VMGM_PGC, target=getbits(word, 46, 15), raw=raw)
    if operation == 8:
        sub = getbits(word, 23, 2)
        if sub == 0:
            return Instruction(op=Op.CALL_SS_FP, second=getbits(word, 31, 8), raw=raw)
        if sub in (1, 2):
            return Instruction(
                op=Op.CALL_SS_VMGM_MENU if sub == 1 else Op.CALL_SS_VTSM,
                target=getbits(word, 19, 4),
                menu=MENU_NAMES.get(getbits(word, 19, 4), ""),
                second=getbits(word, 31, 8),
                raw=raw,
            )
        return Instruction(
            op=Op.CALL_SS_VMGM_PGC,
            target=getbits(word, 46, 15),
            second=getbits(word, 31, 8),
            raw=raw,
        )
    return Instruction(op=Op.UNKNOWN, raw=raw, note=f"jump operation {operation}")


def decode(command: bytes) -> Instruction:
    """Decode one eight-byte DVD command."""
    raw = bytes(command[:8])
    word = _word(command)
    kind = getbits(word, 63, 3)

    # Every family can carry a comparison in bits 54..52 (libdvdnav's
    # if_version_1 for specials and links, if_version_2 for jumps). A
    # guarded instruction this decoder cannot evaluate is refused whole,
    # never run as if the test had passed.
    if kind == 0:
        refused = _refuse_conditional(word, raw)
        if refused is not None:
            return refused
        operation = getbits(word, 51, 4)
        if operation == 0:
            return Instruction(op=Op.NOP, raw=raw)
        if operation == 1:
            return Instruction(op=Op.GOTO, target=getbits(word, 7, 8), raw=raw)
        if operation == 2:
            return Instruction(op=Op.BREAK, raw=raw)
        if operation == 3:
            return Instruction(
                op=Op.SET_PARENTAL,
                target=getbits(word, 11, 4),
                second=getbits(word, 7, 8),
                raw=raw,
            )
        return Instruction(op=Op.UNKNOWN, raw=raw, note=f"special operation {operation}")

    if kind == 1:
        refused = _refuse_conditional(word, raw)
        if refused is not None:
            return refused
        if getbits(word, 60, 1):
            return _decode_jump(word, raw)
        return _decode_link(word, raw)

    if kind in (2, 3):
        # Setting a register, then usually linking. The link half is what a
        # player has to act on; the set half is bookkeeping we carry out.
        # Bits 51..48 are the link operation, decoded exactly as a bare
        # link is; zero means the command only sets. A Play button that
        # reads "SetGPRM(0)=1; LinkPGCN 2" did nothing at all until the
        # link was read (found on a pressed disc, 28 Aug 2026).
        refused = _refuse_conditional(word, raw)
        if refused is not None:
            return refused
        has_link = bool(getbits(word, 51, 4))
        link = _decode_link(word, raw) if has_link else None
        if link is not None and link.op is Op.UNKNOWN:
            return link

        if kind == 2:
            # A system-register set switches its whole layout on the set
            # operation (libdvdnav's `print_system_set`): the audio, subtitle
            # and angle streams, the highlighted button, the timer... none of
            # which this player acts on. A bare one keeps the reading this
            # decoder always had; a system set followed by a link is not
            # decoded rather than decoded wrong.
            if has_link:
                return Instruction(
                    op=Op.UNKNOWN, raw=raw, note="system-register set-then-link is not decoded"
                )
            return Instruction(
                op=Op.SET_SPRM,
                target=getbits(word, 35, 4),
                second=getbits(word, 15, 16),
                raw=raw,
            )

        # kind 3, a general register: libdvdnav's `print_set_version_1`.
        set_op = getbits(word, 59, 4)
        if set_op == 0:
            # No set at all: the command is only its link (or nothing).
            return link if link is not None else Instruction(op=Op.NOP, raw=raw)
        operator = _SET_OPS.get(set_op)
        if operator is None:
            return Instruction(
                op=Op.UNKNOWN, raw=raw, note=f"register set operation {set_op} is not evaluated"
            )
        # The operand is immediate when bit 60 is set and lives in bits
        # 31..16; otherwise it names another register, which this decoder
        # does not copy.
        if not getbits(word, 60, 1):
            return Instruction(
                op=Op.UNKNOWN, raw=raw, note="register-to-register set is not evaluated"
            )
        return Instruction(
            op=Op.SET_GPRM,
            target=getbits(word, 35, 4),
            second=getbits(word, 31, 16),
            raw=raw,
            link=link,
            set_op=operator,
        )

    return Instruction(
        op=Op.UNKNOWN, raw=raw, note=f"instruction group {kind} is not decoded"
    )


@dataclass
class Registers:
    """A DVD's registers: sixteen general, twenty-four system.

    Menus read and write these — which audio track is selected, which button
    is lit, which title is playing. A player that shows menus has to keep them
    even if it never runs a full program.
    """

    general: list[int] = field(default_factory=lambda: [0] * GPRM_COUNT)
    system: list[int] = field(default_factory=lambda: [0] * SPRM_COUNT)

    def __post_init__(self) -> None:
        # A player with no parental restriction set answers "adult", which is
        # what discs expect when they ask.
        self.system[SPRM_PARENTAL_LEVEL] = 0xF
        # Region-free: we have no business enforcing regions on a disc
        # somebody owns.
        self.system[SPRM_PLAYER_CONFIG] = 0

    def get(self, register: int) -> int:
        if register < GPRM_COUNT:
            return self.general[register]
        index = register - GPRM_COUNT
        return self.system[index] if index < SPRM_COUNT else 0

    def set(self, register: int, value: int) -> None:
        value &= 0xFFFF
        if register < GPRM_COUNT:
            self.general[register] = value
        elif register - GPRM_COUNT < SPRM_COUNT:
            self.system[register - GPRM_COUNT] = value


def disassemble(commands: list[bytes]) -> list[str]:
    """A readable listing, for menu preview mode and for bug reports."""
    out: list[str] = []
    for index, command in enumerate(commands):
        instruction = decode(command)
        line = f"{index:3d}  {instruction.describe()}"
        if instruction.note:
            line += f"   ({instruction.note})"
        out.append(line)
    return out
