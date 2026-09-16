"""P1 + P2 (28 Aug 2026): a set-then-link plays; a conditional is refused.

Found on a pressed disc: its Play button reads ``SetGPRM(0)=1; LinkPGCN 2``
and did nothing, because the decoder returned the register write and never
read the link in bits 51..48. And ``if (GPRM1 == 3) LinkPTTN 4`` ran as a
plain ``link-chapter 4``, because bits 54..52 were never read at all.
"""

from __future__ import annotations

from wti_player.dvd import navigator as nav
from wti_player.formats import dvd_vm as vm


def command(*byte_values: int) -> bytes:
    return bytes(byte_values).ljust(8, b"\x00")


# Type 3 (set GPRM, immediate, set_op 1 = assign in bits 59..56) with link
# operation 4 (LinkPGCN) in bits 51..48: byte 0 = 0b0111_0001, byte 1 = 0x04,
# register 0 in bits 35..32, value 1 in bits 31..16, chain 2 in bits 14..0.
SET_GPRM0_1_THEN_LINK_PGCN_2 = command(0x71, 0x04, 0x00, 0x00, 0x00, 0x01, 0x00, 0x02)
# Same, but the link half is zero: a bare register write.
SET_GPRM0_1_ONLY = command(0x71, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00)
# Type 1 link with a comparison (== is 2) in bits 54..52: byte 1 = 0x20 | 0x05.
IF_EQUAL_LINK_PTTN_4 = command(0x20, 0x25, 0x00, 0x00, 0x00, 0x00, 0x04, 0x04)
# Type 3 set-then-link guarded by a comparison.
IF_EQUAL_SET_THEN_LINK = command(0x71, 0x24, 0x00, 0x00, 0x00, 0x01, 0x00, 0x02)


class TestSetThenLink:
    def test_the_link_half_is_decoded_and_attached(self) -> None:
        instruction = vm.decode(SET_GPRM0_1_THEN_LINK_PGCN_2)
        assert instruction.op is vm.Op.SET_GPRM
        assert instruction.target == 0
        assert instruction.second == 1
        assert instruction.link is not None
        assert instruction.link.op is vm.Op.LINK_PGCN
        assert instruction.link.target == 2
        assert "then" in instruction.describe()

    def test_a_bare_set_has_no_link(self) -> None:
        instruction = vm.decode(SET_GPRM0_1_ONLY)
        assert instruction.op is vm.Op.SET_GPRM
        assert instruction.second == 1
        assert instruction.link is None

    def test_a_register_copy_is_refused_rather_than_guessed(self) -> None:
        # Bit 60 clear: the operand names another register. Not evaluated.
        copy = command(0x61, 0x04, 0x00, 0x00, 0x00, 0x01, 0x00, 0x02)
        assert not vm.decode(copy).understood

    def test_the_navigator_writes_the_register_and_then_acts_on_the_link(self) -> None:
        navigator = nav.Navigator()
        action = navigator.run(SET_GPRM0_1_THEN_LINK_PGCN_2)
        assert navigator.registers.get(0) == 1
        # The link is now seen. LinkPGCN names a program chain in the menu
        # domain, and following one needs the PGC command table the IFO
        # reader does not parse yet, so the honest answer is "this disc's
        # menu does something the Player does not follow", naming the link,
        # instead of the silence it used to be.
        assert action.kind == nav.UNSUPPORTED
        assert "link-chain 2" in action.reason

    def test_a_set_then_jump_title_plays_the_title(self) -> None:
        # A Play button seen in the wild: set a register, then LinkPTTN 1.
        navigator = nav.Navigator()
        set_then_pttn = command(0x71, 0x05, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01)
        action = navigator.run(set_then_pttn)
        assert action.kind == nav.PLAY_CHAPTER
        assert action.chapter == 1


class TestConditionals:
    def test_a_guarded_link_is_refused_rather_than_run(self) -> None:
        instruction = vm.decode(IF_EQUAL_LINK_PTTN_4)
        assert not instruction.understood
        assert "conditional" in instruction.note
        assert "==" in instruction.note

    def test_a_guarded_set_then_link_is_refused_too(self) -> None:
        instruction = vm.decode(IF_EQUAL_SET_THEN_LINK)
        assert not instruction.understood

    def test_the_navigator_says_so_instead_of_guessing(self) -> None:
        action = nav.Navigator().run(IF_EQUAL_LINK_PTTN_4)
        assert action.kind == nav.UNSUPPORTED
        assert "does not follow" in action.reason

    def test_an_unguarded_link_still_runs(self) -> None:
        plain = command(0x20, 0x05, 0x00, 0x00, 0x00, 0x00, 0x04, 0x04)
        assert vm.decode(plain).op is vm.Op.LINK_PTTN


class TestSprm8:
    def test_the_lit_button_is_stored_scaled(self) -> None:
        from tests.unit.test_dvd_navigator import two_button_menu

        navigator = nav.Navigator(highlight=two_button_menu(selected=1))
        assert navigator.registers.get(vm.GPRM_COUNT + vm.SPRM_HIGHLIGHTED_BUTTON) == 1 * 1024
        navigator.move("down")
        assert navigator.selected == 2
        assert navigator.registers.get(vm.GPRM_COUNT + vm.SPRM_HIGHLIGHTED_BUTTON) == 2 * 1024


class TestEveryFamilyIsGuarded:
    """Review, 28 Aug 2026: the comparison bits guard jumps and specials too."""

    def test_a_guarded_jump_is_refused(self) -> None:
        # Type 1, bit 60 (a jump), comparison == in bits 54..52, JumpTT 4.
        guarded_jump = command(0x30, 0x22, 0x00, 0x00, 0x00, 0x04)
        assert not vm.decode(guarded_jump).understood
        assert vm.decode(command(0x30, 0x02, 0x00, 0x00, 0x00, 0x04)).op is vm.Op.JUMP_TITLE

    def test_a_guarded_special_is_refused(self) -> None:
        # Type 0, comparison == in bits 54..52, Goto 5.
        guarded_goto = command(0x00, 0x21, 0x00, 0x00, 0x00, 0x00, 0x00, 0x05)
        assert not vm.decode(guarded_goto).understood
        assert vm.decode(command(0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x05)).op is vm.Op.GOTO


class TestTheSetOperation:
    """Bits 59..56 say what the operand does to the register."""

    def _set(self, set_op: int, value: int, link_op: int = 0) -> bytes:
        # Type 3 (0b011), immediate (bit 60), set_op in bits 59..56.
        byte0 = 0x70 | (set_op & 0x0F)
        return command(byte0, link_op & 0x0F, 0x00, 0x00, (value >> 8) & 0xFF, value & 0xFF, 0x00, 0x02)

    def test_assign_add_and_the_others_are_read(self) -> None:
        assert vm.decode(self._set(1, 5)).set_op == "="
        assert vm.decode(self._set(3, 5)).set_op == "+="
        assert vm.decode(self._set(5, 5)).set_op == "*="
        assert vm.decode(self._set(11, 5)).set_op == "^="

    def test_the_navigator_folds_the_operand_in(self) -> None:
        navigator = nav.Navigator()
        navigator.run(self._set(1, 5))
        assert navigator.registers.get(0) == 5
        navigator.run(self._set(3, 7))
        assert navigator.registers.get(0) == 12
        navigator.run(self._set(4, 2))
        assert navigator.registers.get(0) == 10
        navigator.run(self._set(9, 0x0008))
        assert navigator.registers.get(0) == 8

    def test_a_zero_set_op_is_only_its_link(self) -> None:
        # set_op 0 (a NOP per libdvdnav) with LinkPGCN 2: no register write.
        instruction = vm.decode(self._set(0, 5, link_op=4))
        assert instruction.op is vm.Op.LINK_PGCN
        navigator = nav.Navigator()
        navigator.run(self._set(0, 5, link_op=4))
        assert navigator.registers.get(0) == 0

    def test_swap_and_random_are_refused(self) -> None:
        assert not vm.decode(self._set(2, 5)).understood
        assert not vm.decode(self._set(8, 5)).understood

    def test_a_system_set_then_link_is_not_guessed(self) -> None:
        system_then_link = command(0x50, 0x04, 0x00, 0x00, 0x00, 0x01, 0x00, 0x02)
        assert not vm.decode(system_then_link).understood
        assert "system-register" in vm.decode(system_then_link).note
