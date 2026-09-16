"""Discs built to break the Player.

Every byte the parsers in this program read comes off a disc somebody else
made. Most of those discs are scratched rather than hostile, but the code
cannot tell the difference and does not need to: the rule is the same either
way, and it is that a bad disc gets refused quickly.

Each test here is a real reproduction. Two of them are findings from a
security audit on 2026-08-23 that hung the Player outright, and the numbers
in their docstrings are what was measured before the fix.
"""

from __future__ import annotations

import struct
import time

import pytest

from tests.fixtures.authoring import videots
from wti_player.formats import dvd_spu, ifo
from wti_player.optical import identify

#: Nothing in here may take longer than this. A real disc takes milliseconds;
#: the generous bound is for a loaded CI machine, not for the parser.
BUDGET_SECONDS = 3.0


def timed(call):
    started = time.monotonic()
    result = call()
    return result, time.monotonic() - started


def write_vts(path, *, ptt_srpt: bytes, sector: int = 1) -> None:
    """A VTS_01_0.IFO whose chapter-pointer table is whatever we say."""
    header = bytearray(videots.SECTOR)
    header[0x00:0x0C] = ifo.VTS_MAGIC
    header[0x21] = 0x11
    struct.pack_into(">I", header, 0xC8, sector)      # PTT_SRPT
    struct.pack_into(">I", header, 0xCC, sector + 1)  # PGCIT
    body = bytearray(ptt_srpt)
    body += b"\x00" * (-len(body) % videots.SECTOR)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header) + bytes(body))


def hostile_disc(tmp_path, *, titles: int, size_kb: int = 200):
    """The audit's finding 1, built to order.

    A chapter table claiming ``titles`` titles whose offsets alternate
    between zero and four gigabytes. Every second title then re-scans the
    whole file in four-byte steps. Nothing reads out of bounds, so nothing
    raises: the parser simply never stops.
    """
    offsets = bytearray()
    for index in range(titles):
        offsets += struct.pack(">I", 0 if index % 2 else 0xFFFFFFFF)

    table = bytearray()
    table += struct.pack(">H", titles)
    table += b"\x00\x00"
    table += struct.pack(">I", 0xFFFFFFFF)   # last_byte
    table += offsets
    table += b"\x41" * (size_kb * 1024)

    root = tmp_path / "HOSTILE"
    write_vts(root / "VIDEO_TS" / "VTS_01_0.IFO", ptt_srpt=bytes(table))

    vmg = videots.build_vmg([(1, 1, 1)], title_set_count=1)
    (root / "VIDEO_TS" / "VIDEO_TS.IFO").write_bytes(vmg)
    (root / "VIDEO_TS" / "VTS_01_1.VOB").write_bytes(b"\x00" * 2048)
    return root


class TestTheChapterTable:
    """Audit finding 1, 2026-08-23. Critical: it fired on insertion.

    Before the fix, ``identify()`` on this folder did not return in 15
    seconds and was extrapolated to roughly 2.5 billion tuples — about 160 GB
    — for a 65535-title table. No user action was needed: reading a disc is
    what the Player does when one goes in.
    """

    def test_a_table_claiming_sixty_five_thousand_titles_returns_at_once(self, tmp_path):
        disc = hostile_disc(tmp_path, titles=65535)
        profile, seconds = timed(lambda: identify.identify(disc))
        assert seconds < BUDGET_SECONDS, f"took {seconds:.1f}s"
        assert profile.kind is identify.DiscKind.DVD_VIDEO

    def test_the_count_is_capped_at_what_the_format_allows(self, tmp_path):
        disc = hostile_disc(tmp_path, titles=4000)
        _profile, seconds = timed(lambda: ifo.read(disc))
        assert seconds < BUDGET_SECONDS

    def test_no_title_gets_more_chapters_than_a_dvd_can_hold(self, tmp_path):
        disc = hostile_disc(tmp_path, titles=8, size_kb=400)
        read = ifo.read(disc)
        for title in read.titles:
            assert len(title.chapters_ms) <= ifo.MAX_CHAPTERS

    def test_the_table_itself_returns_no_more_titles_than_a_dvd_has(self, tmp_path):
        """The clamp, on its own.

        Both bounds in this parser are load-bearing and each hides the
        other: with only the per-title chapter cap in place, 65535 titles
        still parse fast enough to pass a wall-clock test. So the count is
        asserted directly.
        """
        disc = hostile_disc(tmp_path, titles=65535)
        data = (disc / "VIDEO_TS" / "VTS_01_0.IFO").read_bytes()
        table = ifo._parse_ptt_srpt(data, videots.SECTOR)
        assert len(table) <= ifo.MAX_TITLES_PER_SET, len(table)

    def test_neither_bound_alone_is_enough(self, tmp_path):
        """A budget wide enough for a loaded machine hides one of them."""
        disc = hostile_disc(tmp_path, titles=65535, size_kb=600)
        data = (disc / "VIDEO_TS" / "VTS_01_0.IFO").read_bytes()
        table = ifo._parse_ptt_srpt(data, videots.SECTOR)
        assert sum(len(chapters) for chapters in table) <= (
            ifo.MAX_TITLES_PER_SET * ifo.MAX_CHAPTERS
        )

    def test_a_real_disc_still_reads(self, dvd_disc):
        """The clamps must not cost anything on a disc that is fine."""
        read = ifo.read(dvd_disc)
        assert read.titles
        assert read.main_feature is not None
        assert len(read.main_feature.chapters_ms) == 3


class TestTheSubpicture:
    """Audit finding 2, 2026-08-23. High: it fired on pressing Menu.

    ``SET_AREA`` gives twelve bits per edge, so a disc can declare
    4095x4095. Before the fix a six-kilobyte unit decoded to a
    seventeen-megapixel bitmap using 269 MB, on the interface thread, and
    ``MemoryError`` was not among the exceptions the caller caught.
    """

    def build(self, width: int, height: int) -> bytes:
        """A subpicture that claims an area and carries almost nothing.

        SET_AREA packs four twelve-bit edges into six bytes, which is how a
        disc gets to say 4095 in a field a careless reader assumes is 8-bit.
        """
        x_end, y_end = width - 1, height - 1
        area = bytes(
            (
                0x05,
                0,
                (x_end >> 8) & 0x0F,
                x_end & 0xFF,
                0,
                (y_end >> 8) & 0x0F,
                y_end & 0xFF,
            )
        )
        control_start = 4
        control = bytearray()
        control += (0).to_bytes(2, "big")
        control += control_start.to_bytes(2, "big")
        control += area
        control += bytes((0x06,)) + (4).to_bytes(2, "big") + (4).to_bytes(2, "big")
        control += bytes((0x01, 0xFF))
        total = control_start + len(control)
        return total.to_bytes(2, "big") + control_start.to_bytes(2, "big") + bytes(control)

    def test_a_picture_larger_than_a_dvd_frame_is_refused(self):
        with pytest.raises(dvd_spu.SpuError, match="larger than a DVD frame"):
            dvd_spu.decode(self.build(4096, 4096))

    def test_it_is_refused_quickly(self):
        started = time.monotonic()
        with pytest.raises(dvd_spu.SpuError):
            dvd_spu.decode(self.build(4096, 4096))
        assert time.monotonic() - started < 0.5

    @pytest.mark.parametrize(("width", "height"), [(721, 480), (720, 577), (2000, 100)])
    def test_anything_past_the_largest_dvd_picture_is_refused(self, width, height):
        with pytest.raises(dvd_spu.SpuError):
            dvd_spu.decode(self.build(width, height))

    @pytest.mark.parametrize(("width", "height"), [(720, 576), (720, 480), (360, 120)])
    def test_a_real_size_is_still_accepted(self, width, height):
        """The clamp is at the format's own ceiling, not below it."""
        from tests.fixtures.authoring import spu as author

        rows = author.box(width, height)
        decoded = dvd_spu.decode(
            author.build_subpicture(author.SpuSpec(x_start=0, y_start=0, rows=rows))
        )
        assert decoded.width == width
        assert decoded.height == height


class TestNothingHangs:
    """A general sweep: rubbish in the IFO position, bounded time out."""

    @pytest.mark.parametrize(
        "payload",
        [
            b"",
            b"\x00" * 4096,
            b"\xff" * 4096,
            ifo.VTS_MAGIC + b"\xff" * 8188,
            ifo.VMG_MAGIC + b"\xff" * 8188,
        ],
        ids=["empty", "zeroes", "ones", "vts-of-ones", "vmg-of-ones"],
    )
    def test_a_folder_of_rubbish_is_refused_quickly(self, tmp_path, payload):
        video_ts = tmp_path / "VIDEO_TS"
        video_ts.mkdir()
        (video_ts / "VIDEO_TS.IFO").write_bytes(payload)
        (video_ts / "VTS_01_0.IFO").write_bytes(payload)

        profile, seconds = timed(lambda: identify.identify(tmp_path))
        assert seconds < BUDGET_SECONDS, f"took {seconds:.1f}s"
        assert profile.kind is identify.DiscKind.DVD_VIDEO

    def test_a_bdmv_of_rubbish_is_refused_quickly(self, tmp_path):
        bdmv = tmp_path / "BDMV"
        (bdmv / "PLAYLIST").mkdir(parents=True)
        (bdmv / "CLIPINF").mkdir(parents=True)
        (bdmv / "index.bdmv").write_bytes(b"\xff" * 65536)
        for index in range(4):
            (bdmv / "PLAYLIST" / f"{index:05d}.mpls").write_bytes(b"\xff" * 65536)

        profile, seconds = timed(lambda: identify.identify(tmp_path))
        assert seconds < BUDGET_SECONDS, f"took {seconds:.1f}s"
        assert profile.problem or not profile.titles


class TestTheSeekIndex:
    """The entry-point map, which is where libbluray walks off the end.

    A coarse entry names a fine entry by index. libbluray follows that index
    without checking it fits in the fine table, so a corrupt number is an
    access violation rather than an error. The gate that used to guard this
    read one field — whether the CPI block's length was zero — and nothing
    inside it, which caught a missing map and no bad map at all.
    """

    def test_a_real_clip_passes(self, feature_disc):
        from wti_player.formats import clpi

        clips = list((feature_disc / "BDMV" / "CLIPINF").glob("*.clpi"))
        assert clips, "the fixture disc has no clip info"
        for clip in clips:
            assert clpi.seek_index_is_sound(clip.read_bytes())

    def test_a_coarse_entry_pointing_past_its_fine_table_is_refused(self, feature_disc):
        from wti_player.formats import clpi

        data = _first_clip(feature_disc)
        assert clpi.seek_index_is_sound(data)
        assert not clpi.seek_index_is_sound(_break_coarse_pointer(data))

    def test_a_missing_map_is_refused(self, feature_disc):
        from wti_player.formats import clpi

        data = bytearray(_first_clip(feature_disc))
        start = int.from_bytes(data[16:20], "big")
        data[start : start + 4] = b"\x00\x00\x00\x00"
        assert not clpi.seek_index_is_sound(bytes(data))

    def test_a_map_claiming_more_than_the_file_holds_is_refused(self, feature_disc):
        from wti_player.formats import clpi

        data = bytearray(_first_clip(feature_disc))
        start = int.from_bytes(data[16:20], "big")
        entry = start + 6 + 2
        # A coarse count of 60000, in a block that has room for a handful.
        packed = int.from_bytes(data[entry + 2 : entry + 8], "big")
        packed = (packed & ~(0xFFFF << 18)) | (60_000 << 18)
        data[entry + 2 : entry + 8] = packed.to_bytes(6, "big")
        assert not clpi.seek_index_is_sound(bytes(data))

    def test_a_truncated_file_is_refused_rather_than_raising(self, feature_disc):
        from wti_player.formats import clpi

        data = _first_clip(feature_disc)
        for cut in range(0, len(data), 37):
            assert clpi.seek_index_is_sound(data[:cut]) in (True, False)

    def test_rubbish_is_refused_rather_than_raising(self):
        from wti_player.formats import clpi

        for payload in (b"", b"\xff" * 4096, b"HDMV0300" + b"\x00" * 200):
            assert clpi.seek_index_is_sound(payload) in (True, False)

    def test_the_disc_never_reaches_the_engine(self, feature_disc, tmp_path):
        """The whole point: identify() refuses, so nothing opens it."""
        import shutil

        from wti_player.optical.identify import identify

        broken = tmp_path / "scratched"
        shutil.copytree(feature_disc, broken)
        for clip in (broken / "BDMV" / "CLIPINF").glob("*.clpi"):
            clip.write_bytes(_break_coarse_pointer(clip.read_bytes()))

        profile = identify(broken, label="SCRATCHED")

        assert profile.refuses
        assert "seek index" in profile.problem


def _first_clip(disc) -> bytes:
    return sorted((disc / "BDMV" / "CLIPINF").glob("*.clpi"))[0].read_bytes()


def _break_coarse_pointer(data: bytes) -> bytes:
    """Point every coarse entry at a fine entry that is not there.

    Three bad bytes, which is what a scratch produces: the file still parses,
    the numbers in it are still numbers, and one of them is a lie.
    """
    out = bytearray(data)
    start = int.from_bytes(out[16:20], "big")
    ep_map = start + 6
    packed = int.from_bytes(out[ep_map + 4 : ep_map + 10], "big")
    coarse = (packed >> 18) & 0xFFFF
    table = ep_map + int.from_bytes(out[ep_map + 10 : ep_map + 14], "big") + 4
    for index in range(max(1, coarse)):
        at = table + index * 8
        out[at : at + 4] = (0x3FFFF << 14).to_bytes(4, "big")
    return bytes(out)


class TestTheStreamTable:
    """Seven bytes that say how many streams a PlayItem carries.

    Each is a u8, so seven of them can claim 1785 streams for one PlayItem —
    on every PlayItem, in every playlist, while somebody stands in front of a
    drive waiting for a disc to come up. Measured before the cap: 38 seconds
    and 630 MB for a 10 MB PLAYLIST folder.
    """

    def test_a_table_claiming_everything_is_read_at_once(self):
        from wti_player.formats import mpls

        body = bytearray()
        body += b"\x00\x00"  # reserved
        body += b"\xff" * 7  # 255 of every kind
        body += b"\x00" * 5  # reserved
        table = len(body).to_bytes(2, "big") + bytes(body)

        started = time.monotonic()
        streams = mpls._parse_stn_table(_reader(table))
        elapsed = time.monotonic() - started

        assert streams == ()
        assert elapsed < 0.05

    def test_no_kind_reads_more_than_the_format_allows(self):
        from wti_player.formats import mpls

        entry = b"\x09\x01\x10\x11" + b"\x00" * 6
        attrs = b"\x04\x81\x00" + b"eng"
        one = entry + attrs
        body = bytearray()
        body += b"\x00\x00"
        body += bytes((0, 200, 0, 0, 0, 0, 0))
        body += b"\x00" * 5
        body += one * 200
        table = len(body).to_bytes(2, "big") + bytes(body)

        streams = mpls._parse_stn_table(_reader(table))

        assert len(streams) <= mpls.MAX_STREAMS_PER_KIND

    def test_a_pid_is_read_from_where_its_entry_type_says(self):
        """Types 3 and 4 were read at the wrong offset, so the PID was noise."""
        from wti_player.formats import mpls

        for entry_type, lead in ((1, 0), (2, 2), (3, 1), (4, 2)):
            payload = bytes((entry_type,)) + b"\xaa" * lead + b"\x1f\xa0"
            entry = bytes((len(payload) + 6,)) + payload + b"\x00" * 6
            attrs = b"\x04\x81\x00" + b"eng"
            body = bytearray(b"\x00\x00" + bytes((0, 1, 0, 0, 0, 0, 0)) + b"\x00" * 5)
            body += entry + attrs
            table = len(body).to_bytes(2, "big") + bytes(body)

            streams = mpls._parse_stn_table(_reader(table))

            assert streams[0].pid == 0x1FA0, f"entry type {entry_type}"

    def test_a_secondary_stream_does_not_swallow_the_one_after_it(self):
        """Its trailing reference bytes have to be stepped over, not read."""
        from wti_player.formats import mpls

        def stream(coding: int, pid: int) -> bytes:
            entry = b"\x09\x01" + pid.to_bytes(2, "big") + b"\x00" * 6
            return entry + b"\x04" + bytes((coding,)) + b"\x00" + b"eng"

        body = bytearray(b"\x00\x00" + bytes((0, 0, 0, 0, 1, 0, 0)) + b"\x00" * 5)
        body += stream(0xA1, 0x1A00)
        body += b"\x02\x00\x00\x00"  # two primary audio references
        body += stream(0x81, 0x1100)  # and a stream that must survive it
        table = len(body).to_bytes(2, "big") + bytes(body)

        streams = mpls._parse_stn_table(_reader(table))

        assert next(s.pid for s in streams) == 0x1A00

    def test_a_playlist_that_ends_before_it_starts_has_no_negative_length(self):
        from wti_player.formats import mpls

        item = mpls.PlayItem(
            clip_id="00000",
            codec_id="M2TS",
            in_time=90_000,
            out_time=0,
            still_mode=0,
            still_seconds=0,
            connection_condition=1,
        )
        assert item.duration_ms == 0


class TestReadingAWholeFolder:
    def test_it_stops_rather_than_reading_a_thousand_playlists(self, tmp_path):
        """A disc going in is somebody waiting, not a batch job."""
        from wti_player.formats import mpls

        folder = tmp_path / "PLAYLIST"
        folder.mkdir()
        for number in range(60):
            (folder / f"{number:05d}.mpls").write_bytes(b"MPLS0200" + b"\x00" * 512)

        started = time.monotonic()
        out = mpls.read_all(folder)
        elapsed = time.monotonic() - started

        assert out == []
        assert elapsed < mpls.READ_ALL_SECONDS + 1

    def test_a_real_disc_still_reads(self, menu_disc):
        from wti_player.formats import mpls

        playlists = mpls.read_all(menu_disc / "BDMV" / "PLAYLIST")
        assert playlists
        assert any(pl.has_interactive_graphics for pl in playlists)


def _reader(table: bytes):
    from wti_player.formats.bitreader import BitReader

    return BitReader(table)


class TestTheMenuStream:
    """A menu read back off a disc somebody else made."""

    def test_a_segment_cannot_claim_more_than_its_packet_holds(self):
        """65535 bytes claimed inside a sixteen-byte packet, six hundred times."""
        from wti_player.formats import hdmv_read

        packet = bytearray()
        packet += b"\x00\x00\x01\xbd"
        packet += (16).to_bytes(2, "big")
        packet += b"\x80\x00\x00"       # flags, flags, header length 0
        packet += b"\x18"               # an interactive composition segment
        packet += b"\xff\xff"           # claiming 65535 bytes of body
        packet += b"\x00" * 9
        payload = bytes(packet) * 600

        found = hdmv_read.segments(payload)

        assert sum(len(body) for _, body in found) <= len(payload)

    def test_a_pop_up_menu_reads_its_pages_from_the_right_place(self):
        """Its two timeouts are absent, and skipping them anyway loses ten bytes."""
        from wti_player.formats import hdmv_read

        page = bytearray()
        page += bytes((0, 0))          # page_id, version
        page += b"\x00" * 8            # UO mask
        page += b"\x00\x00"            # in_effects: no windows, no effects
        page += b"\x00\x00"            # out_effects
        page += b"\xff"                # animation_frame_rate
        page += (7).to_bytes(2, "big")  # default_selected_button_id_ref
        page += b"\xff\xff"            # default_activated
        page += b"\x00"                # palette_id_ref
        page += b"\x00"                # no button overlap groups

        body = bytearray()
        body += (1920).to_bytes(2, "big") + (1080).to_bytes(2, "big") + b"\x20"
        body += b"\x00\x00" + b"\x80"  # composition descriptor
        body += b"\xc0"                # sequence descriptor
        body += (len(page) + 5).to_bytes(3, "big")
        body += b"\x80"                # stream_model 1: out of mux, no timeouts
        body += b"\x00\x00\x00"        # user_timeout_duration
        body += bytes((1,))            # one page
        body += page

        width, height, buttons, selected, _palette = hdmv_read._read_composition(bytes(body))

        assert (width, height) == (1920, 1080)
        assert selected == 7
        assert buttons == ()

    def test_a_page_that_animates_in_does_not_lose_its_buttons(self):
        """An effect sequence is not two bytes when there is an effect in it."""
        from wti_player.formats import hdmv_read

        in_effects = bytearray()
        in_effects += b"\x01"                       # one window
        in_effects += b"\x00" + b"\x00" * 8         # id, x, y, width, height
        in_effects += b"\x00"                       # no effects

        page = bytearray()
        page += bytes((0, 0))
        page += b"\x00" * 8
        page += bytes(in_effects)
        page += b"\x00\x00"                          # out_effects: empty
        page += b"\xff"
        page += (3).to_bytes(2, "big")
        page += b"\xff\xff"
        page += b"\x00"
        page += b"\x00"

        body = bytearray()
        body += (1920).to_bytes(2, "big") + (1080).to_bytes(2, "big") + b"\x20"
        body += b"\x00\x00" + b"\x80" + b"\xc0"
        body += (len(page) + 15).to_bytes(3, "big")
        body += b"\x00"                              # stream_model 0
        body += b"\x00" * 5 + b"\x00" * 5            # the two timeouts
        body += b"\x00\x00\x00"
        body += bytes((1,))
        body += page

        _, _, _, selected, _palette = hdmv_read._read_composition(bytes(body))

        assert selected == 3


class TestTheMenuTable:
    """A DVD's menu table, which is read the moment the disc goes in."""

    def test_a_table_claiming_sixty_five_thousand_menus_returns_at_once(self, tmp_path):
        """It did not return. 24 MB to 744 MB in twenty-five seconds, climbing."""
        from wti_player.formats import ifo

        data = bytearray(2048 * 4)
        start = 1024
        data[start : start + 2] = (0xFFFF).to_bytes(2, "big")
        for index in range(64):
            entry = start + 8 + index * 8
            data[entry : entry + 2] = b"en"
            data[entry + 4 : entry + 8] = (512).to_bytes(4, "big")
        unit = start + 512
        data[unit : unit + 2] = (0xFFFF).to_bytes(2, "big")

        began = time.monotonic()
        menus = ifo._parse_pgci_ut(bytes(data), start, domain="vmg", title_set=0)
        elapsed = time.monotonic() - began

        assert elapsed < 1.0
        assert len(menus) <= ifo.MAX_MENUS

    def test_a_real_disc_still_finds_its_menus(self, dvd_disc):
        from wti_player.formats import ifo

        found = ifo.read_menus(dvd_disc)
        assert found.menus == () or all(menu.kind for menu in found.menus)


class TestTheChapterTable2:
    def test_a_program_starting_at_cell_zero_is_not_put_at_the_end(self):
        """cells[:-1] sums every cell but the last: chapter 1 at 9:00 of 10:00."""
        from wti_player.formats import ifo

        cells = tuple(ifo.Cell(first_sector=0, last_sector=0, duration_ms=60_000) for _ in range(10))
        chain = ifo.ProgramChain(
            number=1, duration_ms=600_000, cells=cells, program_cells=(0, 1, 5)
        )
        assert chain.program_start_ms(1) == 0
        assert chain.program_start_ms(2) == 0
        assert chain.program_start_ms(3) == 4 * 60_000
