"""Decoding the graphics a DVD menu is drawn with.

The run lengths are variable-width nibbles and the picture is interlaced
across two fields, which is exactly the sort of format a decoder can get
consistently wrong. So the pictures are encoded by a separate writer and
decoded back, and the pixels have to match exactly.
"""

from __future__ import annotations

import pytest

from tests.fixtures.authoring import spu as enc
from wti_player.formats import dvd_spu as dec


def encode(rows: list[list[int]], **kwargs) -> bytes:
    spec = enc.SpuSpec(
        x_start=kwargs.pop("x", 0), y_start=kwargs.pop("y", 0), rows=rows, **kwargs
    )
    return enc.build_subpicture(spec)


class TestRoundTrip:
    @pytest.mark.parametrize(
        ("label", "rows"),
        [
            ("a button box", enc.box(40, 12, border=2, fill=3)),
            ("a wide bar", enc.box(300, 30, border=3, fill=1)),
            ("a tall column", enc.box(16, 200, border=1, fill=2)),
            ("an odd height", enc.box(21, 7, border=1, fill=3)),
            ("a single line", [[1, 2, 3, 0, 1, 2]]),
            ("one pixel", [[2]]),
            ("all transparent", [[0] * 20 for _ in range(6)]),
            ("every colour", [[(x + y) % 4 for x in range(32)] for y in range(8)]),
        ],
    )
    def test_the_pixels_survive(self, label: str, rows: list[list[int]]) -> None:
        picture = dec.decode(encode(rows))

        assert picture.width == max(len(row) for row in rows)
        assert picture.height == len(rows)
        for index, row in enumerate(rows):
            assert picture.rows[index] == tuple(row), f"{label}, line {index}"

    def test_a_run_longer_than_a_single_code_can_hold(self) -> None:
        # 700 pixels of one colour is more than the widest run code, so it
        # has to be split. A real disc's background lines look like this.
        rows = [[2] * 700]
        assert dec.decode(encode(rows)).rows[0] == tuple(rows[0])

    def test_where_it_sits_on_screen(self) -> None:
        picture = dec.decode(encode(enc.box(40, 12), x=100, y=200))

        assert picture.area.x_start == 100
        assert picture.area.y_start == 200
        assert picture.area.x_end == 139
        assert picture.area.y_end == 211
        assert picture.width == 40
        assert picture.height == 12

    def test_the_palette_and_alpha_come_back(self) -> None:
        picture = dec.decode(
            encode(enc.box(8, 4), palette=(0, 5, 10, 15), alpha=(0, 0xF, 0x8, 0xF))
        )
        assert picture.palette == (0, 5, 10, 15)
        assert picture.alpha == (0, 0xF, 0x8, 0xF)

    def test_a_picture_with_nothing_visible_says_so(self) -> None:
        # Worth knowing before drawing: a subpicture whose every pixel is the
        # transparent entry is a frame with nothing on it.
        assert dec.decode(encode([[0] * 20 for _ in range(6)])).is_blank
        assert not dec.decode(encode(enc.box(20, 6))).is_blank


class TestRefusingRubbish:
    def test_something_too_short(self) -> None:
        with pytest.raises(dec.SpuError):
            dec.decode(b"\x00")

    def test_a_control_block_pointing_outside_the_data(self) -> None:
        with pytest.raises(dec.SpuError):
            dec.decode(b"\x00\x10\xff\xff" + b"\x00" * 12)

    def test_a_picture_that_never_says_where_it_goes(self) -> None:
        # No set-area command, so there is no rectangle to draw into.
        data = bytes([0, 10, 0, 4]) + bytes([0, 0, 0, 4, 0xFF]) + b"\x00" * 4
        with pytest.raises(dec.SpuError, match="where on screen"):
            dec.decode(data)

    def test_a_control_chain_that_loops_does_not_hang(self) -> None:
        picture = encode(enc.box(8, 4))
        control_start = int.from_bytes(picture[2:4], "big")
        looping = bytearray(picture)
        looping[control_start + 2 : control_start + 4] = control_start.to_bytes(2, "big")
        # It either decodes or refuses; what it must not do is spin forever.
        try:
            dec.decode(bytes(looping))
        except dec.SpuError:
            pass


class TestColour:
    def test_ycbcr_becomes_rgb(self) -> None:
        assert dec.yuv_to_rgb(235, 128, 128) == (255, 255, 255)
        assert dec.yuv_to_rgb(16, 128, 128) == (0, 0, 0)

    def test_the_four_indices_resolve_against_the_chain_palette(self) -> None:
        # The indirection is the whole trick behind a DVD highlight: change
        # the four indices and the same pixels become a lit button.
        chain = [0x108080, 0xEB8080, 0x808080, 0x515151] + [0] * 12
        resolved = dec.resolve_palette(chain, (0, 1, 2, 3), (0, 0xF, 0xF, 0x8))

        assert len(resolved) == 4
        assert resolved[0][3] == 0  # fully transparent
        assert resolved[1][:3] == (255, 255, 255)
        assert resolved[3][3] == 136  # eight sixteenths, as a byte

    def test_an_index_off_the_end_of_the_palette_does_not_throw(self) -> None:
        assert dec.resolve_palette([0x108080], (0, 9, 9, 9), (0xF,) * 4)
