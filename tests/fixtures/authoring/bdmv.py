"""Write the four BDMV files, and splice an IG stream into a muxed clip.

tsMuxeR builds a correct Blu-ray from video and audio, but it cannot author a
menu: no open tool can. So the fixture disc is built in two halves — tsMuxeR
makes the streams, and this module replaces the navigation layer on top of
them with one that has a real HDMV menu in it.

What gets rewritten, and why:

``index.bdmv``        First Play and Top Menu must point at our movie objects.
``MovieObject.bdmv``  The little HDMV programs: loop the menu, play the film.
``*.mpls``            The menu playlist has to declare the IG stream in its
                      STN table — that is where libbluray looks for the menu.
``*.clpi``            Same stream, declared again for the clip. The menu clip
                      is written with an empty CPI: a menu is never seeked,
                      and an EP map whose packet numbers we have shifted is
                      worse than no EP map at all.
``STREAM/*.m2ts``     The IG transport packets are spliced in ahead of the
                      first video packet, and every copy of the PMT is
                      rewritten to declare PID 0x1400.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from . import hdmv

BDMV_VERSION = b"0200"

# Stream coding types, as the STN table and clip info spell them.
CODING_H264 = 0x1B
CODING_AC3 = 0x81
CODING_IG = 0x91


def _align4(data: bytearray) -> None:
    while len(data) % 4:
        data += b"\x00"


# --------------------------------------------------------------------------
# index.bdmv and MovieObject.bdmv
# --------------------------------------------------------------------------


def _index_entry(movie_object: int, playback_type: int) -> bytes:
    """One 12-byte HDMV index slot."""
    out = bytearray()
    out += ((hdmv.GRP_BRANCH + 1) << 30).to_bytes(4, "big")  # object_type 1 = HDMV
    out += ((playback_type & 0x03) << 30 | movie_object).to_bytes(4, "big")
    out += b"\x00\x00\x00\x00"
    return bytes(out)


def build_index(first_play: int, top_menu: int, titles: list[int]) -> bytes:
    """``index.bdmv`` pointing First Play, Top Menu and each title at a movie object."""
    indexes = bytearray()
    indexes += _index_entry(first_play, playback_type=1)  # interactive
    indexes += _index_entry(top_menu, playback_type=1)
    indexes += len(titles).to_bytes(2, "big")
    for movie_object in titles:
        indexes += _index_entry(movie_object, playback_type=0)  # movie

    out = bytearray()
    out += b"INDX" + BDMV_VERSION
    out += b"\x00\x00\x00\x00"  # indexes_start_address, filled in below
    out += b"\x00\x00\x00\x00"  # extension_data_start_address
    out += b"\x00" * 24  # reserved
    app_info = b"\x00" * 34
    out += len(app_info).to_bytes(4, "big") + app_info
    struct.pack_into(">I", out, 8, len(out))
    out += len(indexes).to_bytes(4, "big") + indexes
    return bytes(out)


@dataclass(frozen=True)
class MovieObjectSpec:
    """One HDMV movie object: its commands and its two mask bits."""

    commands: tuple[bytes, ...]
    resume_intention: bool = True
    menu_call_mask: bool = False
    title_search_mask: bool = False


def build_movie_objects(objects: list[MovieObjectSpec]) -> bytes:
    body = bytearray()
    body += b"\x00\x00\x00\x00"  # reserved
    body += len(objects).to_bytes(2, "big")
    for spec in objects:
        flags = 0
        if spec.resume_intention:
            flags |= 0x8000
        if spec.menu_call_mask:
            flags |= 0x4000
        if spec.title_search_mask:
            flags |= 0x2000
        body += flags.to_bytes(2, "big")
        body += len(spec.commands).to_bytes(2, "big")
        for command in spec.commands:
            if len(command) != 12:
                raise ValueError("an HDMV navigation command is 12 bytes")
            body += command

    out = bytearray()
    out += b"MOBJ" + BDMV_VERSION
    out += b"\x00\x00\x00\x00"  # extension_data_start_address
    out += b"\x00" * 28  # reserved
    out += len(body).to_bytes(4, "big") + body
    return bytes(out)


# --------------------------------------------------------------------------
# Playlists
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class StreamSpec:
    """One STN table entry: a PID and what is on it."""

    pid: int
    coding_type: int
    language: str = ""
    #: For video, the packed format/rate byte tsMuxeR writes (e.g. 0x51).
    format_rate: int = 0

    @property
    def kind(self) -> str:
        if self.coding_type in (0x01, 0x02, 0x1B, 0x20, 0x24, 0xEA):
            return "video"
        if self.coding_type in (0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86):
            return "audio"
        if self.coding_type == 0x91:
            return "interactive"
        if self.coding_type == 0x90:
            return "subtitle"
        return "other"

    def entry_bytes(self) -> bytes:
        entry = bytes((0x01,)) + self.pid.to_bytes(2, "big") + b"\x00" * 6
        return bytes((len(entry),)) + entry

    def attribute_bytes(self) -> bytes:
        if self.kind == "video":
            attrs = bytes((self.coding_type, self.format_rate, 0x30)) + b"\x00" * 2
        elif self.kind == "audio":
            attrs = bytes((self.coding_type, self.format_rate)) + _lang(self.language)
        else:
            attrs = bytes((self.coding_type,)) + _lang(self.language)
        return bytes((len(attrs),)) + attrs


def _lang(language: str) -> bytes:
    return (language or "und").encode("ascii", "replace")[:3].ljust(3, b"\x00")


@dataclass(frozen=True)
class PlayItemSpec:
    clip_id: str
    in_time: int
    out_time: int
    streams: tuple[StreamSpec, ...]
    #: 0 = normal playback, 2 = a still that holds until the user acts.
    still_mode: int = 0
    still_seconds: int = 0
    connection_condition: int = 1


def _stn_table(streams: tuple[StreamSpec, ...]) -> bytes:
    ordered = {
        "video": [s for s in streams if s.kind == "video"],
        "audio": [s for s in streams if s.kind == "audio"],
        "subtitle": [s for s in streams if s.kind == "subtitle"],
        "interactive": [s for s in streams if s.kind == "interactive"],
    }
    body = bytearray()
    body += b"\x00\x00"  # reserved
    body += bytes(
        (
            len(ordered["video"]),
            len(ordered["audio"]),
            len(ordered["subtitle"]),
            len(ordered["interactive"]),
            0,  # secondary audio
            0,  # secondary video
            0,  # picture-in-picture subtitles
        )
    )
    body += b"\x00" * 5  # reserved
    for kind in ("video", "audio", "subtitle", "interactive"):
        for stream in ordered[kind]:
            body += stream.entry_bytes()
            body += stream.attribute_bytes()
    return len(body).to_bytes(2, "big") + bytes(body)


def _play_item(spec: PlayItemSpec) -> bytes:
    body = bytearray()
    body += spec.clip_id.encode("ascii").ljust(5, b"0")
    body += b"M2TS"
    body += (spec.connection_condition & 0x0F).to_bytes(2, "big")
    body += b"\x00"  # ref_to_STC_id
    body += spec.in_time.to_bytes(4, "big")
    body += spec.out_time.to_bytes(4, "big")
    body += b"\x00" * 8  # UO mask table
    body += b"\x00"  # random access flag + reserved
    body += bytes((spec.still_mode,))
    body += spec.still_seconds.to_bytes(2, "big")
    body += _stn_table(spec.streams)
    return len(body).to_bytes(2, "big") + bytes(body)


def build_playlist(
    items: list[PlayItemSpec],
    marks: list[tuple[int, int]],
    *,
    playback_type: int = 1,
    playback_count: int = 0,
) -> bytes:
    """A ``.mpls``. ``marks`` is a list of ``(play_item_index, timestamp)``."""
    out = bytearray()
    out += b"MPLS" + BDMV_VERSION
    out += b"\x00" * 12  # the three start addresses, filled in below
    out += b"\x00" * 20  # reserved

    app_info = bytearray()
    app_info += b"\x00"  # reserved
    app_info += bytes((playback_type,))
    app_info += playback_count.to_bytes(2, "big")
    app_info += b"\x00" * 8  # UO mask table
    app_info += b"\x00\x00"  # random access / mixing flags
    out += len(app_info).to_bytes(4, "big") + app_info
    _align4(out)

    playlist_start = len(out)
    playlist = bytearray()
    playlist += b"\x00\x00"  # reserved
    playlist += len(items).to_bytes(2, "big")
    playlist += b"\x00\x00"  # number of sub paths
    for spec in items:
        playlist += _play_item(spec)
    out += len(playlist).to_bytes(4, "big") + playlist
    _align4(out)

    marks_start = len(out)
    mark_body = bytearray()
    mark_body += len(marks).to_bytes(2, "big")
    for play_item_index, timestamp in marks:
        mark_body += b"\x00"  # reserved
        mark_body += b"\x01"  # mark_type: entry mark, i.e. a chapter
        mark_body += play_item_index.to_bytes(2, "big")
        mark_body += timestamp.to_bytes(4, "big")
        mark_body += b"\x00\x00"  # entry ES PID: unspecified
        mark_body += b"\x00\x00\x00\x00"  # duration
    out += len(mark_body).to_bytes(4, "big") + mark_body

    struct.pack_into(">I", out, 8, playlist_start)
    struct.pack_into(">I", out, 12, marks_start)
    struct.pack_into(">I", out, 16, 0)  # no extension data
    return bytes(out)


# --------------------------------------------------------------------------
# Clip info
# --------------------------------------------------------------------------


def build_clip_info(
    *,
    streams: tuple[StreamSpec, ...],
    source_packet_count: int,
    ts_recording_rate: int,
    pcr_pid: int,
    pmt_pid: int,
    presentation_start: int,
    presentation_end: int,
    cpi_block: bytes = b"",
) -> bytes:
    """A ``.clpi``. ``cpi_block`` is the raw CPI payload, empty for no EP map."""
    out = bytearray()
    out += b"HDMV" + BDMV_VERSION
    out += b"\x00" * 20  # five start addresses, filled in below
    out += b"\x00" * 12  # reserved

    clip_info = bytearray()
    clip_info += b"\x00\x00"  # reserved
    clip_info += b"\x01"  # clip_stream_type: AV stream
    clip_info += b"\x01"  # application_type: main TS for a movie
    clip_info += b"\x00\x00\x00\x00"  # reserved + is_ATC_delta
    clip_info += ts_recording_rate.to_bytes(4, "big")
    clip_info += source_packet_count.to_bytes(4, "big")
    clip_info += b"\x00" * 128  # reserved
    ts_type_info = bytearray(b"\x80" + b"HDMV")
    ts_type_info += b"\x00" * (30 - len(ts_type_info))
    clip_info += len(ts_type_info).to_bytes(2, "big") + ts_type_info
    out += len(clip_info).to_bytes(4, "big") + clip_info
    _align4(out)

    sequence_start = len(out)
    sequence = bytearray()
    sequence += b"\x00"  # reserved
    sequence += b"\x01"  # one ATC sequence
    sequence += b"\x00\x00\x00\x00"  # SPN_ATC_start
    sequence += b"\x01"  # one STC sequence
    sequence += b"\x00"  # offset_STC_id
    sequence += pcr_pid.to_bytes(2, "big")
    sequence += b"\x00\x00\x00\x00"  # SPN_STC_start
    sequence += presentation_start.to_bytes(4, "big")
    sequence += presentation_end.to_bytes(4, "big")
    out += len(sequence).to_bytes(4, "big") + sequence
    _align4(out)

    program_start = len(out)
    program = bytearray()
    program += b"\x00"  # reserved
    program += b"\x01"  # one program
    program += b"\x00\x00\x00\x00"  # SPN_program_sequence_start
    program += pmt_pid.to_bytes(2, "big")
    program += bytes((len(streams), 0))
    for stream in streams:
        program += stream.pid.to_bytes(2, "big")
        if stream.kind == "video":
            coding = bytes((stream.coding_type, stream.format_rate, 0x30)) + b"\x00" * 18
        elif stream.kind == "audio":
            coding = bytes((stream.coding_type, stream.format_rate)) + _lang(stream.language)
        else:
            coding = bytes((stream.coding_type,)) + _lang(stream.language)
        program += bytes((len(coding),)) + coding
    out += len(program).to_bytes(4, "big") + program
    _align4(out)

    cpi_start = len(out)
    out += len(cpi_block).to_bytes(4, "big") + cpi_block
    _align4(out)

    mark_start = len(out)
    out += b"\x00\x00\x00\x00"  # ClipMark: none

    extension_start = len(out)
    out += b"\x00\x00\x00\x00"  # extension data: none

    for offset, value in (
        (8, sequence_start),
        (12, program_start),
        (16, cpi_start),
        (20, mark_start),
        (24, extension_start),
    ):
        struct.pack_into(">I", out, offset, value)
    return bytes(out)


# --------------------------------------------------------------------------
# The EP map
#
# libbluray dereferences a clip's EP map without checking it is there — every
# disc in the world has one — so a clip written with an empty CPI crashes the
# player rather than merely refusing to seek. Splicing packets into a clip
# moves every source packet number in the map, so the map has to move with
# them. Rather than find the I-frames ourselves, we take the map tsMuxeR
# already got right and shift it.
#
# Layout, confirmed against a tsMuxeR clip:
#
#   CPI:  reserved(12) CPI_type(4) | reserved(8) n_pid_entries(8)
#         per PID: pid(16) reserved(10) ep_stream_type(4)
#                  n_coarse(16) n_fine(18) start_address(32)
#         per PID, at start_address counted from the n_pid_entries byte:
#                  fine_table_start(32)
#                  coarse: ref_to_fine(18) pts_coarse(14) spn_coarse(32)
#                  fine:   angle(1) i_end(3) pts_fine(11) spn_fine(17)
#
#   PTS_EP = (pts_coarse << 19) | (pts_fine << 9), in 90 kHz units.
#   SPN_EP = (spn_coarse & ~0x1ffff) | spn_fine.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EntryPoint:
    """One seek point: a presentation time and the packet it starts at."""

    pts_90khz: int
    source_packet: int
    angle_change: bool = False
    i_end_offset: int = 0


@dataclass(frozen=True)
class EpMap:
    stream_pid: int
    ep_stream_type: int
    entries: tuple[EntryPoint, ...]


def parse_cpi(data: bytes) -> list[EpMap]:
    """Decode a CPI block into absolute (time, packet) entry points."""
    if len(data) < 4:
        return []
    reader = _Bits(data)
    reader.skip(12)
    cpi_type = reader.bits(4)
    if cpi_type != 1:
        return []
    ep_map_start = reader.byte_pos
    reader.bits(8)
    pid_count = reader.bits(8)

    headers = []
    for _ in range(pid_count):
        pid = reader.bits(16)
        reader.skip(10)
        ep_stream_type = reader.bits(4)
        coarse_count = reader.bits(16)
        fine_count = reader.bits(18)
        start_address = reader.bits(32)
        headers.append((pid, ep_stream_type, coarse_count, fine_count, start_address))

    maps: list[EpMap] = []
    for pid, ep_stream_type, coarse_count, fine_count, start_address in headers:
        base = ep_map_start + start_address
        reader.seek(base)
        fine_start = reader.bits(32)
        coarse: list[tuple[int, int, int]] = []
        for _ in range(coarse_count):
            ref_to_fine = reader.bits(18)
            pts_coarse = reader.bits(14)
            spn_coarse = reader.bits(32)
            coarse.append((ref_to_fine, pts_coarse, spn_coarse))

        reader.seek(base + fine_start)
        fine: list[tuple[int, int, int, int]] = []
        for _ in range(fine_count):
            angle = reader.bits(1)
            i_end = reader.bits(3)
            pts_fine = reader.bits(11)
            spn_fine = reader.bits(17)
            fine.append((angle, i_end, pts_fine, spn_fine))

        # Each coarse entry owns the fine entries from its ref_to_fine up to
        # the next coarse entry's, and supplies their high bits.
        entries: list[EntryPoint] = []
        for index, (ref_to_fine, pts_coarse, spn_coarse) in enumerate(coarse):
            last = coarse[index + 1][0] if index + 1 < len(coarse) else len(fine)
            for angle, i_end, pts_fine, spn_fine in fine[ref_to_fine:last]:
                entries.append(
                    EntryPoint(
                        pts_90khz=(pts_coarse << 19) | (pts_fine << 9),
                        source_packet=(spn_coarse & ~0x1FFFF) | spn_fine,
                        angle_change=bool(angle),
                        i_end_offset=i_end,
                    )
                )
        maps.append(EpMap(stream_pid=pid, ep_stream_type=ep_stream_type, entries=tuple(entries)))
    return maps


def build_cpi(maps: list[EpMap]) -> bytes:
    """Re-emit a CPI block from absolute entry points."""
    if not maps:
        return b""
    header = _BitWriter()
    header.bits(0, 12)  # reserved
    header.bits(1, 4)  # CPI_type: EP map
    ep_map = _BitWriter()
    ep_map.bits(0, 8)  # reserved
    ep_map.bits(len(maps), 8)

    tables: list[bytes] = []
    for entry_map in maps:
        coarse: list[tuple[int, int, int]] = []
        fine: list[tuple[int, int, int, int]] = []
        for entry in entry_map.entries:
            high = (entry.pts_90khz >> 19, entry.source_packet >> 17)
            if not coarse or (coarse[-1][1], coarse[-1][2] >> 17) != high:
                coarse.append((len(fine), high[0], entry.source_packet))
            fine.append(
                (
                    1 if entry.angle_change else 0,
                    entry.i_end_offset,
                    (entry.pts_90khz >> 9) & 0x7FF,
                    entry.source_packet & 0x1FFFF,
                )
            )
        table = _BitWriter()
        table.bits(4 + len(coarse) * 8, 32)  # EP_fine_table_start_address
        for ref_to_fine, pts_coarse, spn_coarse in coarse:
            table.bits(ref_to_fine, 18)
            table.bits(pts_coarse, 14)
            table.bits(spn_coarse, 32)
        for angle, i_end, pts_fine, spn_fine in fine:
            table.bits(angle, 1)
            table.bits(i_end, 3)
            table.bits(pts_fine, 11)
            table.bits(spn_fine, 17)
        tables.append(table.to_bytes())
        ep_map.bits(entry_map.stream_pid, 16)
        ep_map.bits(0, 10)
        ep_map.bits(entry_map.ep_stream_type, 4)
        ep_map.bits(len(coarse), 16)
        ep_map.bits(len(fine), 18)
        ep_map.bits(0, 32)  # start address, patched below

    body = bytearray(ep_map.to_bytes())
    offset = len(body)
    for index, table in enumerate(tables):
        struct.pack_into(">I", body, 2 + index * 12 + 8, offset)
        body += table
        offset += len(table)
    return header.to_bytes() + bytes(body)


def shift_ep_map(cpi: bytes, delta: int, *, anchor_at_zero: bool = True) -> bytes:
    """The same map, with every source packet number moved along by ``delta``.

    ``anchor_at_zero`` adds an entry for packet 0 pointing at the first real
    entry point. Without it libbluray logs "no timestamp for SPN 0" every time
    the clip starts, because the first packet is now one of ours.
    """
    maps = parse_cpi(cpi)
    if not maps:
        return cpi
    if anchor_at_zero:
        maps = [
            EpMap(
                stream_pid=entry_map.stream_pid,
                ep_stream_type=entry_map.ep_stream_type,
                entries=(
                    (
                        EntryPoint(
                            pts_90khz=entry_map.entries[0].pts_90khz,
                            source_packet=-delta,
                            i_end_offset=entry_map.entries[0].i_end_offset,
                        ),
                        *entry_map.entries,
                    )
                    if entry_map.entries and entry_map.entries[0].source_packet + delta > 0
                    else entry_map.entries
                ),
            )
            for entry_map in maps
        ]
    shifted = [
        EpMap(
            stream_pid=entry_map.stream_pid,
            ep_stream_type=entry_map.ep_stream_type,
            entries=tuple(
                EntryPoint(
                    pts_90khz=entry.pts_90khz,
                    source_packet=entry.source_packet + delta,
                    angle_change=entry.angle_change,
                    i_end_offset=entry.i_end_offset,
                )
                for entry in entry_map.entries
            ),
        )
        for entry_map in maps
    ]
    return build_cpi(shifted)


def cpi_of(clpi_bytes: bytes) -> bytes:
    """Pull the raw CPI payload out of a ``.clpi``."""
    cpi_start = struct.unpack_from(">I", clpi_bytes, 16)[0]
    length = struct.unpack_from(">I", clpi_bytes, cpi_start)[0]
    return clpi_bytes[cpi_start + 4 : cpi_start + 4 + length]


class _Bits:
    """A tiny big-endian bit reader, so the authoring side does not depend on
    the Player's own reader (which the tests are meant to be checking)."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    @property
    def byte_pos(self) -> int:
        return self._pos // 8

    def seek(self, offset: int) -> None:
        self._pos = offset * 8

    def skip(self, count: int) -> None:
        self._pos += count

    def bits(self, count: int) -> int:
        value = 0
        for _ in range(count):
            byte = self._data[self._pos // 8]
            value = (value << 1) | ((byte >> (7 - self._pos % 8)) & 1)
            self._pos += 1
        return value


class _BitWriter:
    def __init__(self) -> None:
        self._bits: list[int] = []

    def bits(self, value: int, count: int) -> None:
        for shift in range(count - 1, -1, -1):
            self._bits.append((value >> shift) & 1)

    def to_bytes(self) -> bytes:
        while len(self._bits) % 8:
            self._bits.append(0)
        out = bytearray()
        for index in range(0, len(self._bits), 8):
            byte = 0
            for bit in self._bits[index : index + 8]:
                byte = (byte << 1) | bit
            out.append(byte)
        return bytes(out)


# --------------------------------------------------------------------------
# Splicing the IG stream into a muxed clip
# --------------------------------------------------------------------------

_CRC_TABLE: list[int] = []


def _mpeg_crc32(data: bytes) -> int:
    """The MPEG-2 systems CRC: poly 0x04C11DB7, MSB first, no final xor."""
    if not _CRC_TABLE:
        for index in range(256):
            value = index << 24
            for _ in range(8):
                value = ((value << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if value & 0x80000000 else (value << 1) & 0xFFFFFFFF
            _CRC_TABLE.append(value)
    crc = 0xFFFFFFFF
    for byte in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _CRC_TABLE[((crc >> 24) ^ byte) & 0xFF]
    return crc


def _patch_pmt(packet: bytes, pid: int, stream_type: int) -> bytes:
    """Add one elementary stream to a PMT carried in a single TS packet."""
    if packet[0] != 0x47 or not packet[1] & 0x40:
        return packet
    header_len = 4
    if packet[3] & 0x20:  # adaptation field present
        header_len += 1 + packet[4]
    pointer = packet[header_len]
    section_start = header_len + 1 + pointer
    if packet[section_start] != 0x02:  # table_id: program map section
        return packet
    section_length = ((packet[section_start + 1] & 0x0F) << 8) | packet[section_start + 2]
    section_end = section_start + 3 + section_length
    section = bytearray(packet[section_start:section_end])

    entry = bytes((stream_type,)) + (0xE000 | pid).to_bytes(2, "big") + b"\x00\x00"
    body = section[:-4] + entry  # everything but the old CRC
    new_length = len(body) - 3 + 4
    body[1] = (body[1] & 0xF0) | ((new_length >> 8) & 0x0F)
    body[2] = new_length & 0xFF
    body += _mpeg_crc32(bytes(body)).to_bytes(4, "big")

    rebuilt = bytearray(packet[:section_start]) + body
    if len(rebuilt) > 188:
        raise ValueError("the PMT no longer fits in one transport packet")
    rebuilt += b"\xff" * (188 - len(rebuilt))
    return bytes(rebuilt)


def splice_interactive_graphics(
    m2ts: bytes,
    ig_packets: list[bytes],
    *,
    pmt_pid: int = 0x0100,
    video_pid: int = 0x1011,
    ig_pid: int = hdmv.IG_PID,
) -> tuple[bytes, int]:
    """Return the clip with an IG stream in it, and how many packets moved.

    The IG packets go in immediately before the first video packet, so they
    are decoded well ahead of the first frame they have to be on top of. The
    file keeps its 6144-byte alignment: BD source packets come in aligned
    units of 32, and readers assume it.
    """
    if len(m2ts) % 192:
        raise ValueError("not a source-packet-aligned M2TS")

    packets = [m2ts[offset : offset + 192] for offset in range(0, len(m2ts), 192)]
    insert_at = None
    for index, source_packet in enumerate(packets):
        pid = ((source_packet[5] & 0x1F) << 8) | source_packet[6]
        if pid == video_pid:
            insert_at = index
            break
    if insert_at is None:
        raise ValueError(f"no video packets on PID 0x{video_pid:04x}")

    patched: list[bytes] = []
    for source_packet in packets:
        pid = ((source_packet[5] & 0x1F) << 8) | source_packet[6]
        if pid == pmt_pid:
            patched.append(
                source_packet[:4] + _patch_pmt(source_packet[4:], ig_pid, hdmv.IG_STREAM_TYPE)
            )
        else:
            patched.append(source_packet)

    # Give the injected packets the arrival timestamp of the packet they
    # displace, which keeps the stream monotonic without re-stamping it.
    arrival = patched[insert_at][:4]
    injected = [arrival + packet for packet in ig_packets]

    out = patched[:insert_at] + injected + patched[insert_at:]
    while len(out) % 32:
        out.append(arrival + _null_packet())
    return b"".join(out), len(injected)


def _null_packet() -> bytes:
    return b"\x47\x1f\xff\x10" + b"\xff" * 184


def write_bdmv(root: Path, files: dict[str, bytes]) -> None:
    """Write a BDMV tree, and the BACKUP copies a real disc carries."""
    for relative, data in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if not relative.startswith("BDMV/STREAM/"):
            backup = root / relative.replace("BDMV/", "BDMV/BACKUP/", 1)
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(data)
