"""A DVD's menus: where the buttons are, and what pressing one means.

None of this needs a disc. The NAV packs are written by our own authoring
module and read back by the Player's parser, and the command decoder is
checked against the instruction shapes real discs use.
"""

from __future__ import annotations

import pytest

from tests.fixtures.authoring import videots as vt
from wti_player.formats import dvd_nav
from wti_player.formats import dvd_vm as vm


def command(*byte_values: int) -> bytes:
    return bytes(byte_values).ljust(8, b"\x00")


class TestNavPacks:
    def test_a_nav_pack_round_trips(self) -> None:
        sector = vt.build_nav_pack(
            sector=42, start_pts=90_000, end_pts=180_000, vobu_sectors=60
        )
        assert len(sector) == dvd_nav.SECTOR

        pack = dvd_nav.parse_nav_sector(sector)
        assert pack is not None
        assert pack.sector == 42
        assert pack.start_pts == 90_000
        assert pack.end_pts == 180_000
        assert pack.vobu_sectors == 60
        assert not pack.has_menu

    def test_a_menu_pack_carries_its_buttons(self) -> None:
        buttons = (
            vt.ButtonSpec(200, 300, 520, 350, down=2, command=command(0x30, 0x02, 0, 0, 0, 1)),
            vt.ButtonSpec(200, 370, 520, 420, up=1, command=command(0x30, 0x02, 0, 0, 0, 2)),
        )
        sector = vt.build_nav_pack(
            sector=0, start_pts=0, end_pts=90_000, vobu_sectors=8, buttons=buttons, selected=1
        )
        pack = dvd_nav.parse_nav_sector(sector)

        assert pack.has_menu
        highlight = pack.highlight
        assert highlight.selected_button == 1
        real = [button for button in highlight.buttons if button.is_real]
        assert len(real) == 2
        assert (real[0].x_start, real[0].y_start) == (200, 300)
        assert (real[0].x_end, real[0].y_end) == (520, 350)
        assert real[0].width == 320
        assert real[0].height == 50
        assert real[0].down == 2
        assert real[1].up == 1

    def test_buttons_can_be_hit_with_a_mouse(self) -> None:
        buttons = (
            vt.ButtonSpec(200, 300, 520, 350),
            vt.ButtonSpec(200, 370, 520, 420),
        )
        highlight = dvd_nav.parse_nav_sector(
            vt.build_nav_pack(
                sector=0, start_pts=0, end_pts=1, vobu_sectors=1, buttons=buttons
            )
        ).highlight

        assert highlight.at(300, 320).number == 1
        assert highlight.at(300, 390).number == 2
        assert highlight.at(10, 10) is None
        # Edges belong to the button that starts there, not the one that ends.
        assert highlight.at(200, 300).number == 1
        assert highlight.at(520, 300) is None

    def test_neighbours_are_reachable_by_name(self) -> None:
        buttons = (vt.ButtonSpec(0, 0, 10, 10, up=4, down=2, left=3, right=1),)
        button = dvd_nav.parse_nav_sector(
            vt.build_nav_pack(
                sector=0, start_pts=0, end_pts=1, vobu_sectors=1, buttons=buttons
            )
        ).highlight.buttons[0]

        assert button.neighbour("up") == 4
        assert button.neighbour("down") == 2
        assert button.neighbour("left") == 3
        assert button.neighbour("right") == 1
        assert button.neighbour("sideways") == dvd_nav.NO_BUTTON

    def test_an_auto_action_button_says_so(self) -> None:
        buttons = (vt.ButtonSpec(0, 0, 10, 10, auto_action=True),)
        button = dvd_nav.parse_nav_sector(
            vt.build_nav_pack(
                sector=0, start_pts=0, end_pts=1, vobu_sectors=1, buttons=buttons
            )
        ).highlight.buttons[0]
        assert button.auto_action

    def test_something_that_is_not_a_nav_pack_is_not_mistaken_for_one(self) -> None:
        assert dvd_nav.parse_nav_sector(b"\x00" * dvd_nav.SECTOR) is None
        assert dvd_nav.parse_nav_sector(b"\x00\x00\x01\xba" + b"\xff" * 100) is None

    @pytest.mark.media
    def test_it_finds_the_nav_packs_in_a_real_vob(self, dvd_disc) -> None:
        vob = dvd_disc / "VIDEO_TS" / "VTS_01_1.VOB"
        packs = dvd_nav.read_nav_packs(vob)

        # ffmpeg writes the frame of a NAV pack and leaves the fields empty,
        # so what is checked here is that we find them and do not fall over.
        assert packs
        assert all(pack.offset % dvd_nav.SECTOR == 0 for pack in packs)
        assert not any(pack.has_menu for pack in packs)


class TestCommandDecoding:
    def test_the_instructions_a_menu_button_actually_uses(self) -> None:
        cases = [
            (command(0x00, 0x00), vm.Op.NOP, 0),
            (command(0x30, 0x02, 0, 0, 0, 3), vm.Op.JUMP_TITLE, 3),
            (command(0x30, 0x03, 0, 0, 0, 2), vm.Op.JUMP_VTS_TITLE, 2),
            (command(0x20, 0x04, 0, 0, 0, 0, 0, 5), vm.Op.LINK_PGCN, 5),
            (command(0x20, 0x05, 0, 0, 0, 0, 0x04, 0x02), vm.Op.LINK_PTTN, 2),
            (command(0x20, 0x06, 0, 0, 0, 0, 0, 0x03), vm.Op.LINK_PGN, 3),
            (command(0x20, 0x07, 0, 0, 0, 0, 0, 0x07), vm.Op.LINK_CN, 7),
        ]
        for raw, expected_op, expected_target in cases:
            instruction = vm.decode(raw)
            assert instruction.op is expected_op, raw.hex()
            assert instruction.target == expected_target, raw.hex()
            assert instruction.understood

    def test_the_link_family_that_takes_no_number(self) -> None:
        for sub, expected in (
            (0x09, vm.Op.LINK_TOP_PGC),
            (0x0A, vm.Op.LINK_NEXT_PGC),
            (0x0B, vm.Op.LINK_PREV_PGC),
            (0x0C, vm.Op.LINK_GO_UP_PGC),
            (0x10, vm.Op.LINK_RSM),
        ):
            assert vm.decode(command(0x20, 0x01, 0, 0, 0, 0, 0, sub)).op is expected

    def test_a_button_number_rides_along_with_a_link(self) -> None:
        # A menu that jumps somewhere and lights a particular button there.
        instruction = vm.decode(command(0x20, 0x05, 0, 0, 0, 0, 0x0C, 0x02))
        assert instruction.op is vm.Op.LINK_PTTN
        assert instruction.button == 3

    def test_the_jump_family_against_libdvdnav_s_own_field_positions(self) -> None:
        """These byte patterns were built from libdvdnav's ``vmcmd.c``.

        Checking against the reference rather than against memory caught
        three wrong offsets in this decoder, each of which would have sent
        somebody to the wrong part of a disc.
        """
        assert vm.decode(command(0x30, 0x01)).op is vm.Op.EXIT

        instruction = vm.decode(command(0x30, 0x05, 0x00, 0x07, 0x00, 0x02))
        assert instruction.op is vm.Op.JUMP_VTS_PTT
        assert instruction.target == 2  # title, seven bits ending at bit 22
        assert instruction.second == 7  # chapter, ten bits ending at bit 41

        instruction = vm.decode(command(0x30, 0x06, 0x00, 0x01, 0x01, 0x83))
        assert instruction.op is vm.Op.JUMP_SS_VTSM
        assert instruction.title_set == 1  # seven bits ending at bit 30
        assert instruction.second == 1  # title, seven bits ending at bit 38
        assert instruction.menu == "root"

        instruction = vm.decode(command(0x30, 0x06, 0x00, 0x00, 0x00, 0x43))
        assert instruction.op is vm.Op.JUMP_SS_VMGM_MENU
        assert instruction.menu == "root"

        assert vm.decode(command(0x30, 0x06)).op is vm.Op.JUMP_SS_FP

        # Call sub-instruction 2 is a title-set menu, not a disc chain.
        instruction = vm.decode(command(0x30, 0x08, 0x00, 0x00, 0x05, 0x83))
        assert instruction.op is vm.Op.CALL_SS_VTSM
        assert instruction.menu == "root"
        assert instruction.second == 5  # the cell to resume at afterwards

    def test_an_instruction_we_do_not_follow_says_so_instead_of_guessing(self) -> None:
        # Sending someone to the wrong part of a disc is worse than admitting
        # we did not understand the disc.
        instruction = vm.decode(command(0xE0, 0xFF, 0xFF, 0xFF))
        assert not instruction.understood
        assert instruction.op is vm.Op.UNKNOWN
        assert instruction.note

    def test_a_short_command_does_not_throw(self) -> None:
        assert vm.decode(b"\x00").op is vm.Op.NOP
        assert vm.decode(b"").op is vm.Op.NOP

    def test_getbits_reads_from_the_top(self) -> None:
        word = 0xF000_0000_0000_0001
        assert vm.getbits(word, 63, 4) == 0xF
        assert vm.getbits(word, 3, 4) == 0x1
        assert vm.getbits(word, 0, 1) == 1
        assert vm.getbits(word, 2, 8) == 0  # runs off the bottom, reads zero

    def test_a_listing_is_readable(self) -> None:
        listing = vm.disassemble(
            [command(0x30, 0x02, 0, 0, 0, 1), command(0x20, 0x01, 0, 0, 0, 0, 0, 0x10)]
        )
        assert "jump-title 1" in listing[0]
        assert "resume" in listing[1]


class TestRegisters:
    def test_a_fresh_player_answers_adult_and_region_free(self) -> None:
        # A disc that asks about parental level or region gets an answer that
        # does not stand between somebody and a disc they own.
        registers = vm.Registers()
        assert registers.system[vm.SPRM_PARENTAL_LEVEL] == 0xF
        assert registers.system[vm.SPRM_PLAYER_CONFIG] == 0

    def test_general_and_system_registers_are_separate(self) -> None:
        registers = vm.Registers()
        registers.set(3, 42)
        registers.set(vm.GPRM_COUNT + vm.SPRM_AUDIO_STREAM, 2)

        assert registers.get(3) == 42
        assert registers.get(vm.GPRM_COUNT + vm.SPRM_AUDIO_STREAM) == 2
        assert registers.general[3] == 42
        assert registers.system[vm.SPRM_AUDIO_STREAM] == 2

    def test_values_are_sixteen_bit(self) -> None:
        registers = vm.Registers()
        registers.set(0, 0x1_0001)
        assert registers.get(0) == 1

    def test_a_register_that_does_not_exist_reads_zero(self) -> None:
        assert vm.Registers().get(999) == 0


class TestMenuTables:
    """Finding a disc's menus: which program chain is the root menu."""

    @staticmethod
    def _disc(tmp_path, menus: dict[str, vt.TitleSpec] | None):
        vob = tmp_path / "video.vob"
        vob.write_bytes(b"\x00" * (vt.SECTOR * 16))
        title = vt.TitleSpec(
            cells=(vt.CellSpec(4000, 0, 7), vt.CellSpec(3000, 8, 15)),
            chapter_cells=(1, 2),
        )
        root = tmp_path / "disc"
        vt.write_video_ts(
            root, vob, title=title, menus=menus, menu_vob=vob if menus else None
        )
        return root

    def test_a_disc_with_menus_reports_them_by_kind(self, tmp_path) -> None:
        from wti_player.formats import ifo

        menu = vt.TitleSpec(cells=(vt.CellSpec(0, 0, 7),))
        disc = self._disc(tmp_path, {"root": menu, "title": menu, "chapter": menu})

        found = ifo.read_menus(disc)
        assert found.has_menus
        assert {menu.kind for menu in found.menus} == {"root", "title", "chapter"}
        assert found.of_kind("root").name == "Main menu"
        assert found.of_kind("chapter").name == "Chapter menu"
        assert all(menu.language == "en" for menu in found.menus)
        assert found.vob_files and found.vob_files[0].name == "VTS_01_0.VOB"

    def test_the_menu_button_prefers_root_then_title(self, tmp_path) -> None:
        from wti_player.formats import ifo

        menu = vt.TitleSpec(cells=(vt.CellSpec(0, 0, 7),))
        assert ifo.read_menus(self._disc(tmp_path, {"root": menu})).root.kind == "root"

    def test_with_no_root_it_falls_back_rather_than_offering_nothing(
        self, tmp_path
    ) -> None:
        from wti_player.formats import ifo

        menu = vt.TitleSpec(cells=(vt.CellSpec(0, 0, 7),))
        found = ifo.read_menus(self._disc(tmp_path, {"title": menu}))
        assert found.root.kind == "title"

    def test_a_disc_with_no_menus_says_so_rather_than_inventing_one(
        self, tmp_path
    ) -> None:
        from wti_player.formats import ifo

        found = ifo.read_menus(self._disc(tmp_path, None))
        assert not found.has_menus
        assert found.root is None

    def test_adding_menus_does_not_disturb_the_titles(self, tmp_path) -> None:
        from wti_player.formats import ifo

        menu = vt.TitleSpec(cells=(vt.CellSpec(0, 0, 7),))
        disc = self._disc(tmp_path, {"root": menu})

        read = ifo.read(disc)
        assert len(read.titles) == 1
        assert read.titles[0].duration_ms == 7000
        assert read.titles[0].chapters_ms == (0, 4000)
