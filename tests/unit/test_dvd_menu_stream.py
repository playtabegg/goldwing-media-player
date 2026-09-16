"""Pulling a menu's picture out of a VOB.

The reader that finishes the DVD menu path. A menu VOB is an MPEG program
stream, and the words on the buttons are a subpicture inside it, not video
and not audio.
"""

from __future__ import annotations

import pytest

from tests.fixtures.authoring import spu as author
from wti_player.dvd import menu_stream
from wti_player.formats import dvd_spu


def a_picture(width: int = 120, height: int = 40) -> bytes:
    return author.build_subpicture(
        author.SpuSpec(x_start=60, y_start=80, rows=author.box(width, height))
    )


def a_vob(tmp_path, *sectors: bytes, name: str = "menu.vob"):
    path = tmp_path / name
    path.write_bytes(b"".join(sectors))
    return path


def stream_sectors(payload: bytes, chunk: int = 1600) -> list[bytes]:
    """The payload, spread across as many sectors as it takes."""
    return [
        author.sector_with(payload[start : start + chunk])
        for start in range(0, len(payload), chunk)
    ]


class TestFindingIt:
    def test_a_subpicture_in_one_packet_is_found(self, tmp_path):
        picture = a_picture()
        pes = author.spu_pes_packets(picture, chunk=len(picture))
        vob = a_vob(tmp_path, author.sector_with(pes))

        found = menu_stream.read_menu_picture(vob)
        assert found is not None
        assert found.subpicture.width == 120
        assert found.subpicture.height == 40
        assert not found.subpicture.is_blank

    def test_a_subpicture_split_across_packets_is_reassembled(self, tmp_path):
        """One picture, many packets. This is the ordinary case on a disc."""
        picture = a_picture(320, 90)
        pes = author.spu_pes_packets(picture, chunk=64)
        assert pes.count(b"\x00\x00\x01\xbd") > 4, "the split did not happen"
        vob = a_vob(tmp_path, *stream_sectors(pes))

        found = menu_stream.read_menu_picture(vob)
        assert found is not None
        assert found.subpicture.width == 320

    def test_it_decodes_to_the_same_pixels_that_went_in(self, tmp_path):
        rows = author.box(64, 24, border=2, fill=3)
        picture = author.build_subpicture(
            author.SpuSpec(x_start=10, y_start=10, rows=rows)
        )
        vob = a_vob(tmp_path, author.sector_with(author.spu_pes_packets(picture)))

        found = menu_stream.read_menu_picture(vob)
        assert found is not None
        for y in (0, 1, 12, 22, 23):
            for x in (0, 1, 30, 62, 63):
                assert found.subpicture.pixel(x, y) == rows[y][x], (x, y)

    def test_the_padding_a_real_sector_carries_is_stepped_over(self, tmp_path):
        picture = a_picture()
        # sector_with() pads to 2048 with a 0xBE packet, exactly as a muxer
        # does. A walker that treats padding as data finds nothing.
        vob = a_vob(tmp_path, author.sector_with(author.spu_pes_packets(picture)))
        assert menu_stream.read_menu_picture(vob) is not None

    def test_a_particular_stream_can_be_asked_for(self, tmp_path):
        wanted = author.build_subpicture(
            author.SpuSpec(x_start=0, y_start=0, rows=author.box(200, 50))
        )
        other = author.build_subpicture(
            author.SpuSpec(x_start=0, y_start=0, rows=author.box(80, 20))
        )
        vob = a_vob(
            tmp_path,
            author.sector_with(author.spu_pes_packets(other, stream=0)),
            author.sector_with(author.spu_pes_packets(wanted, stream=3)),
        )

        found = menu_stream.read_menu_picture(vob, stream=3)
        assert found is not None
        assert found.stream == menu_stream.SPU_FIRST + 3
        assert found.subpicture.width == 200

    def test_the_first_stream_wins_when_none_is_named(self, tmp_path):
        first = author.build_subpicture(
            author.SpuSpec(x_start=0, y_start=0, rows=author.box(200, 50))
        )
        vob = a_vob(tmp_path, author.sector_with(author.spu_pes_packets(first, stream=0)))
        found = menu_stream.read_menu_picture(vob)
        assert found is not None
        assert found.subpicture.width == 200


class TestNotBeingFooled:
    def test_audio_in_the_same_private_stream_is_not_mistaken_for_a_picture(self, tmp_path):
        """AC-3 rides in private stream 1 too, at sub-stream 0x80."""
        body = bytes((0x81, 0x00, 0x00)) + bytes((0x80, 0x01, 0x00, 0x00)) + b"\x0b\x77" * 200
        audio = b"\x00\x00\x01\xbd" + len(body).to_bytes(2, "big") + body
        vob = a_vob(tmp_path, author.sector_with(audio))
        assert menu_stream.read_menu_picture(vob) is None

    def test_a_video_packet_is_stepped_over(self, tmp_path):
        picture = a_picture()
        body = bytes((0x81, 0x00, 0x00)) + b"\x00\x00\x01\xb3" + b"\x11" * 300
        video = b"\x00\x00\x01\xe0" + len(body).to_bytes(2, "big") + body
        vob = a_vob(
            tmp_path,
            author.sector_with(video + author.spu_pes_packets(picture)),
        )
        found = menu_stream.read_menu_picture(vob)
        assert found is not None

    def test_a_file_that_is_not_a_vob_reads_as_no_menu(self, tmp_path):
        assert menu_stream.read_menu_picture(a_vob(tmp_path, b"not a program stream" * 500)) is None

    def test_a_file_that_is_not_there_reads_as_no_menu(self, tmp_path):
        assert menu_stream.read_menu_picture(tmp_path / "gone.vob") is None

    def test_an_empty_file_reads_as_no_menu(self, tmp_path):
        assert menu_stream.read_menu_picture(a_vob(tmp_path, b"")) is None

    def test_a_truncated_picture_is_dropped_rather_than_guessed_at(self, tmp_path):
        picture = a_picture()
        pes = author.spu_pes_packets(picture, chunk=64)
        # Cut the stream in half: the length field says more is coming and it
        # never does.
        vob = a_vob(tmp_path, author.sector_with(pes[: len(pes) // 2]))
        assert menu_stream.read_menu_picture(vob) is None

    def test_a_lying_length_is_refused(self, tmp_path):
        picture = bytearray(a_picture())
        picture[0:2] = (0xFF, 0xFF)  # claims 64KB, is 200 bytes
        vob = a_vob(tmp_path, author.sector_with(author.spu_pes_packets(bytes(picture))))
        assert menu_stream.read_menu_picture(vob) is None

    def test_a_blank_picture_is_not_the_menu(self, tmp_path):
        """A menu shows one between highlights. It is not what we are after."""
        blank = author.build_subpicture(
            author.SpuSpec(x_start=0, y_start=0, rows=[[0] * 100 for _ in range(30)])
        )
        vob = a_vob(tmp_path, author.sector_with(author.spu_pes_packets(blank)))
        assert menu_stream.read_menu_picture(vob) is None

    def test_the_scan_is_bounded(self, tmp_path):
        """A caller who points this at a title VOB waits a moment, not a minute."""
        picture = a_picture()
        junk = b"\x00" * 40_000
        vob = a_vob(
            tmp_path,
            junk,
            author.sector_with(author.spu_pes_packets(picture)),
        )
        assert menu_stream.read_menu_picture(vob, max_bytes=20_000) is None
        assert menu_stream.read_menu_picture(vob) is not None


class TestTheDecoderItself:
    @pytest.mark.parametrize("size", [(16, 8), (100, 40), (360, 120), (720, 60)])
    def test_a_box_survives_the_round_trip(self, size):
        width, height = size
        rows = author.box(width, height)
        decoded = dvd_spu.decode(
            author.build_subpicture(author.SpuSpec(x_start=0, y_start=0, rows=rows))
        )
        assert decoded.width == width
        assert decoded.height == height
        assert decoded.pixel(0, 0) == rows[0][0]
        assert decoded.pixel(width // 2, height // 2) == rows[height // 2][width // 2]
