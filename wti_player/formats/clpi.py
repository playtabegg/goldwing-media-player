"""Read a Blu-ray clip info file (``BDMV/CLIPINF/*.clpi``).

A playlist says *what* to play; the clip info says what is actually inside the
matching ``STREAM/*.m2ts`` — the elementary streams, their PIDs and codecs, and
the presentation window in 45 kHz ticks.

The Player uses this to describe a disc without starting playback, and menu
preview mode uses it to say "this menu clip carries an interactive graphics
stream on PID 0x1400" when the menu does not come up.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .bitreader import BitReader, TruncatedError
from .mpls import _CODING_NAMES, TICKS_PER_SECOND, Stream  # noqa: F401 - shared vocabulary

CLPI_MAGIC = b"HDMV"
SUPPORTED_VERSIONS = ("0100", "0200", "0300")

#: Stream coding types that identify an interactive-graphics (menu) stream.
INTERACTIVE_GRAPHICS = 0x91
PRESENTATION_GRAPHICS = 0x90

_VIDEO_CODINGS = (0x01, 0x02, 0x1B, 0x20, 0x24, 0xEA)
_AUDIO_CODINGS = (0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0xA1, 0xA2)


class ClpiError(ValueError):
    """This file is not a clip info file we can read."""


@dataclass(frozen=True)
class ClipStream:
    """One elementary stream declared by the clip."""

    pid: int
    coding_type: int
    language: str = ""
    format_code: int = 0
    rate_code: int = 0
    aspect_code: int = 0

    @property
    def coding_name(self) -> str:
        return _CODING_NAMES.get(self.coding_type, f"0x{self.coding_type:02x}")

    @property
    def kind(self) -> str:
        if self.coding_type in _VIDEO_CODINGS:
            return "video"
        if self.coding_type in _AUDIO_CODINGS:
            return "audio"
        if self.coding_type == PRESENTATION_GRAPHICS:
            return "subtitle"
        if self.coding_type == INTERACTIVE_GRAPHICS:
            return "interactive"
        if self.coding_type == 0x92:
            return "subtitle"
        return "other"


@dataclass(frozen=True)
class ClipInfo:
    """A parsed ``.clpi``."""

    name: str
    version: str
    clip_stream_type: int
    application_type: int
    ts_recording_rate: int
    source_packet_count: int
    presentation_start: int = 0
    presentation_end: int = 0
    pcr_pid: int = 0
    streams: tuple[ClipStream, ...] = ()

    @property
    def duration_ms(self) -> int:
        return max(0, self.presentation_end - self.presentation_start) * 1000 // TICKS_PER_SECOND

    @property
    def has_interactive_graphics(self) -> bool:
        return any(stream.coding_type == INTERACTIVE_GRAPHICS for stream in self.streams)

    def streams_of(self, kind: str) -> tuple[ClipStream, ...]:
        return tuple(stream for stream in self.streams if stream.kind == kind)


def _parse_stream_coding(reader: BitReader) -> tuple[int, str, int, int, int]:
    """StreamCodingInfo: returns (coding_type, language, format, rate, aspect)."""
    length = reader.u8()
    end = reader.byte_pos + length
    coding = reader.u8()
    language = ""
    format_code = rate_code = aspect_code = 0
    if coding in _VIDEO_CODINGS:
        format_code = reader.bits(4)
        rate_code = reader.bits(4)
        aspect_code = reader.bits(4)
        reader.bits(4)  # reserved / oc flag
    elif coding in _AUDIO_CODINGS:
        format_code = reader.bits(4)
        rate_code = reader.bits(4)
        language = reader.ascii(3).rstrip("\x00")
    elif coding in (PRESENTATION_GRAPHICS, INTERACTIVE_GRAPHICS):
        language = reader.ascii(3).rstrip("\x00")
    elif coding == 0x92:
        reader.u8()  # character code
        language = reader.ascii(3).rstrip("\x00")
    reader.seek(end)
    return coding, language, format_code, rate_code, aspect_code


def parse(data: bytes, name: str = "") -> ClipInfo:
    """Parse ``.clpi`` bytes. Raises :class:`ClpiError` on anything unreadable."""
    try:
        reader = BitReader(data)
        magic = reader.read(4)
        if magic != CLPI_MAGIC:
            raise ClpiError(f"not a clip info file: magic {magic!r}")
        version = reader.ascii(4)
        if version not in SUPPORTED_VERSIONS:
            raise ClpiError(f"unsupported clip info version {version!r}")
        sequence_start = reader.u32()
        program_start = reader.u32()
        reader.u32()  # CPI start
        reader.u32()  # clip mark start
        reader.u32()  # extension data start

        reader.seek(40)  # ClipInfo()
        reader.u32()  # length
        reader.u16()  # reserved
        clip_stream_type = reader.u8()
        application_type = reader.u8()
        reader.u32()  # reserved(31) + is_ATC_delta
        ts_recording_rate = reader.u32()
        source_packet_count = reader.u32()

        pcr_pid = 0
        presentation_start = presentation_end = 0
        if sequence_start:
            reader.seek(sequence_start)
            reader.u32()  # length
            reader.u8()  # reserved
            atc_count = reader.u8()
            for _ in range(atc_count):
                reader.u32()  # SPN_ATC_start
                stc_count = reader.u8()
                reader.u8()  # offset_STC_id
                for index in range(stc_count):
                    pid = reader.u16()
                    reader.u32()  # SPN_STC_start
                    start = reader.u32()
                    end = reader.u32()
                    if index == 0 and not presentation_end:
                        pcr_pid, presentation_start, presentation_end = pid, start, end

        streams: list[ClipStream] = []
        if program_start:
            reader.seek(program_start)
            reader.u32()  # length
            reader.u8()  # reserved
            program_count = reader.u8()
            for _ in range(program_count):
                reader.u32()  # SPN_program_sequence_start
                reader.u16()  # program_map_PID
                stream_count = reader.u8()
                reader.u8()  # number_of_groups
                for _ in range(stream_count):
                    pid = reader.u16()
                    coding, language, fmt, rate, aspect = _parse_stream_coding(reader)
                    streams.append(
                        ClipStream(
                            pid=pid,
                            coding_type=coding,
                            language=language,
                            format_code=fmt,
                            rate_code=rate,
                            aspect_code=aspect,
                        )
                    )
    except TruncatedError as exc:
        raise ClpiError(f"clip info is truncated: {exc}") from exc

    return ClipInfo(
        name=name,
        version=version,
        clip_stream_type=clip_stream_type,
        application_type=application_type,
        ts_recording_rate=ts_recording_rate,
        source_packet_count=source_packet_count,
        presentation_start=presentation_start,
        presentation_end=presentation_end,
        pcr_pid=pcr_pid,
        streams=tuple(streams),
    )


def read(path: Path) -> ClipInfo:
    return parse(path.read_bytes(), name=path.stem)


def read_all(clipinf_dir: Path) -> dict[str, ClipInfo]:
    """Every readable clip info in a ``CLIPINF`` directory, keyed by clip id."""
    out: dict[str, ClipInfo] = {}
    for path in sorted(clipinf_dir.glob("*.clpi")):
        try:
            out[path.stem] = read(path)
        except (ClpiError, OSError):
            continue
    return out


# ---------------------------------------------------------------------------
# The seek index
# ---------------------------------------------------------------------------
#
# A clip's entry-point map is what a seek lands on: a coarse table of rough
# positions, and a fine table each coarse entry points into. libbluray walks
# it without checking that the pointers stay inside the tables, so a coarse
# entry naming fine entry 200000 in a table of 40 reads whatever is after the
# buffer. That is an access violation, not an error message, and three bad
# bytes on a scratched disc are enough to cause it.
#
# So the map is walked here first and a disc that fails it never reaches the
# engine. Nothing below decodes the map for use — the Player seeks through
# libvlc — it only answers whether libbluray can be trusted with this file.

#: Field widths, so a corrupt count cannot become a long loop. A real clip is
#: three orders of magnitude under each of these.
MAX_EP_PIDS = 255
MAX_CPI_BYTES = 8 << 20

#: One entry in the EP map header: PID, stream type, the two counts, and where
#: this PID's tables start. 96 bits, byte-aligned at both ends.
_EP_HEADER_ENTRY = 12


def seek_index_is_sound(data: bytes) -> bool:
    """Can libbluray be handed this clip without walking off a table?

    False for a CPI block that is missing, empty, truncated, or whose coarse
    entries point outside their own fine table. True is not a promise that
    seeking is accurate, only that it stays inside the file.
    """
    try:
        return _walk_seek_index(data)
    except (IndexError, ValueError, TruncatedError):
        return False


def _walk_seek_index(data: bytes) -> bool:
    if len(data) < 20:
        return False
    cpi_start = int.from_bytes(data[16:20], "big")
    if cpi_start < 40 or cpi_start + 6 > len(data):
        return False

    block_length = int.from_bytes(data[cpi_start : cpi_start + 4], "big")
    if block_length == 0 or block_length > MAX_CPI_BYTES:
        return False
    block_end = cpi_start + 4 + block_length
    if block_end > len(data):
        return False

    # reserved(12) + CPI_type(4), so the type is the low nibble of the second
    # byte. Type 1 is the EP map, and the only type BD-ROM defines. Anything
    # else carries no map, which means there is no map to walk off the end of
    # — not our problem to refuse, and refusing it would refuse discs that
    # play. The reserved bits are left alone: nothing reads them, discs fill
    # them with whatever they like, and a disc is not damaged for it.
    if (data[cpi_start + 5] & 0x0F) != 0x01:
        return True

    # EP_map() begins at the first byte after CPI_type, and every start
    # address below is counted from there.
    ep_map = cpi_start + 6
    pid_count = data[ep_map + 1]
    if pid_count == 0 or pid_count > MAX_EP_PIDS:
        return False
    header_end = ep_map + 2 + pid_count * _EP_HEADER_ENTRY
    if header_end > block_end:
        return False

    for index in range(pid_count):
        at = ep_map + 2 + index * _EP_HEADER_ENTRY
        # bits 16..63 of the entry: reserved(10), type(4), coarse(16), fine(18)
        packed = int.from_bytes(data[at + 2 : at + 8], "big")
        coarse = (packed >> 18) & 0xFFFF
        fine = packed & 0x3FFFF
        start = int.from_bytes(data[at + 8 : at + 12], "big")
        if not _tables_are_sound(data, ep_map + start, coarse, fine, block_end):
            return False
    return True


def _tables_are_sound(data: bytes, base: int, coarse: int, fine: int, block_end: int) -> bool:
    """One PID's coarse and fine tables: inside the block, and consistent.

    A PID with no entries at all is sound — there is nothing to walk, the disc
    simply cannot be seeked on that stream. It is a pointer into a table that
    is not there that has to be caught.
    """
    if coarse == 0 and fine == 0:
        return True
    if base < 0 or base + 4 > block_end:
        return False

    # A coarse entry is 8 bytes, a fine entry 4, and the fine table follows
    # the coarse one after the 4-byte address that opens the structure.
    coarse_table = base + 4
    fine_table = coarse_table + coarse * 8
    if fine_table + fine * 4 > block_end:
        return False

    for index in range(coarse):
        at = coarse_table + index * 8
        # ref_to_EP_fine_id is the top 18 bits of the entry's first word.
        ref = int.from_bytes(data[at : at + 4], "big") >> 14
        if ref >= fine:
            return False
    return True
