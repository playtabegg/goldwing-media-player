"""Read a Blu-ray playlist (``BDMV/PLAYLIST/*.mpls``).

The Player reads playlists directly, without starting the engine, for three
things: listing what is on a disc before anything plays, picking the main
feature ("the longest playlist that is not a menu"), and menu preview mode,
where we want to say what a playlist *claims* even when it will not play.

Times on a Blu-ray are in 45 kHz ticks. They are converted to milliseconds at
the edge of this module and nowhere else.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .bitreader import BitReader, TruncatedError

#: Blu-ray timestamps tick at 45 kHz.
TICKS_PER_SECOND = 45_000

MPLS_MAGIC = b"MPLS"
SUPPORTED_VERSIONS = ("0100", "0200", "0300")

#: STN table stream coding types we care to name.
_CODING_NAMES = {
    0x01: "MPEG-1 video",
    0x02: "MPEG-2 video",
    0x1B: "H.264",
    0x20: "H.264 MVC",
    0x24: "HEVC",
    0xEA: "VC-1",
    0x80: "LPCM",
    0x81: "AC-3",
    0x82: "DTS",
    0x83: "TrueHD",
    0x84: "AC-3 Plus",
    0x85: "DTS-HD",
    0x86: "DTS-HD Master",
    0xA1: "AC-3 Plus (secondary)",
    0xA2: "DTS-HD (secondary)",
    0x90: "Presentation Graphics",
    0x91: "Interactive Graphics",
    0x92: "Text subtitle",
}

#: Stream kinds, in the order the STN table lists them.
STREAM_KINDS = (
    "video",
    "audio",
    "subtitle",
    "interactive",
    "secondary_audio",
    "secondary_video",
    "pip_subtitle",
)


class MplsError(ValueError):
    """This file is not a playlist we can read."""


@dataclass(frozen=True)
class Stream:
    """One entry of a PlayItem's STN table."""

    kind: str
    pid: int
    coding_type: int
    language: str = ""
    format_code: int = 0
    rate_code: int = 0

    @property
    def coding_name(self) -> str:
        return _CODING_NAMES.get(self.coding_type, f"0x{self.coding_type:02x}")


@dataclass(frozen=True)
class PlayItem:
    """One clip, or part of one, in playback order."""

    clip_id: str
    codec_id: str
    in_time: int
    out_time: int
    still_mode: int
    still_seconds: int
    connection_condition: int
    streams: tuple[Stream, ...] = ()

    @property
    def duration_ms(self) -> int:
        """How long this item runs. Never negative.

        A playlist whose out time is before its in time is corrupt, and the
        subtraction happily returns a negative number that then propagates
        into a total duration, a scrub bar and a "main feature" choice.
        """
        return max(0, (self.out_time - self.in_time) * 1000 // TICKS_PER_SECOND)

    @property
    def is_still(self) -> bool:
        """A still PlayItem holds one frame — how BD menus are usually built."""
        return self.still_mode != 0x00

    def streams_of(self, kind: str) -> tuple[Stream, ...]:
        return tuple(stream for stream in self.streams if stream.kind == kind)


@dataclass(frozen=True)
class Mark:
    """A PlayListMark. ``mark_type`` 1 is an entry mark, i.e. a chapter."""

    mark_type: int
    play_item_id: int
    timestamp: int
    duration: int = 0

    @property
    def is_chapter(self) -> bool:
        return self.mark_type == 0x01


@dataclass(frozen=True)
class Playlist:
    """A parsed ``.mpls``."""

    name: str
    version: str
    playback_type: int
    playback_count: int
    play_items: tuple[PlayItem, ...] = ()
    marks: tuple[Mark, ...] = ()
    sub_path_count: int = 0

    @property
    def duration_ms(self) -> int:
        return sum(item.duration_ms for item in self.play_items)

    @property
    def chapters_ms(self) -> tuple[int, ...]:
        """Chapter marks as offsets from the start of the playlist."""
        starts: list[int] = []
        running = 0
        for item in self.play_items:
            starts.append(running)
            running += item.duration_ms
        out: list[int] = []
        for mark in self.marks:
            if not mark.is_chapter or mark.play_item_id >= len(self.play_items):
                continue
            item = self.play_items[mark.play_item_id]
            offset = (mark.timestamp - item.in_time) * 1000 // TICKS_PER_SECOND
            out.append(starts[mark.play_item_id] + max(0, offset))
        return tuple(sorted(set(out)))

    @property
    def clip_ids(self) -> tuple[str, ...]:
        return tuple(item.clip_id for item in self.play_items)

    @property
    def has_interactive_graphics(self) -> bool:
        """True when a PlayItem carries an IG stream — i.e. this is a menu."""
        return any(item.streams_of("interactive") for item in self.play_items)

    @property
    def looks_like_menu(self) -> bool:
        """Our own heuristic, used only where the disc does not tell us.

        A menu playlist either carries interactive graphics or is a still.
        Short playlists are *not* assumed to be menus: a two-minute trailer
        is not a menu, and guessing wrong hides a title from the user.
        """
        return self.has_interactive_graphics or any(item.is_still for item in self.play_items)


#: The most streams of one kind BD-ROM allows. A disc past this is not a
#: disc with a lot of audio tracks, it is a disc with a corrupt count — and
#: without the cap, seven bytes claiming 255 each is 1785 entries per
#: PlayItem, on every playlist, while somebody waits for a disc to come up.
MAX_STREAMS_PER_KIND = 32

#: How many leading bytes sit between a stream entry's type and its PID.
#: Type 1 is in this clip; 2 and 4 name a sub-path and a sub-clip; 3 names a
#: sub-path only. Reading the wrong number here does not fail, it just
#: returns two bytes of something else as the PID.
_PID_LEAD = {1: 0, 2: 2, 3: 1, 4: 2}


def _parse_stn_table(reader: BitReader) -> tuple[Stream, ...]:
    """The stream number table: what this PlayItem actually carries.

    The order the entries come in is not the order the counts come in, which
    is the trap. Presentation graphics and picture-in-picture presentation
    graphics share one run of entries, and the two secondary kinds each carry
    a block of reference bytes after their attributes. A parser that walks
    them as seven independent lists reads the right number of entries and
    gives them the wrong names from the third one onwards.
    """
    length = reader.u16()
    if length == 0:
        return ()
    end = reader.byte_pos + length
    reader.u16()  # reserved
    counts = {
        kind: min(reader.u8(), MAX_STREAMS_PER_KIND)
        for kind in (
            "video",
            "audio",
            "subtitle",
            "interactive",
            "secondary_audio",
            "secondary_video",
            "pip_subtitle",
        )
    }
    reader.read(5)  # reserved

    streams: list[Stream] = []

    def take(kind: str, count: int, extra: str = "") -> None:
        for _ in range(count):
            if reader.byte_pos >= end:
                # The table said more than it holds. Stop where it ran out
                # rather than reading whatever is after it.
                return
            streams.append(_parse_stream_entry(reader, kind))
            if extra:
                _skip_reference_block(reader, extra, end)

    take("video", counts["video"])
    take("audio", counts["audio"])
    # One run, in file order: presentation graphics then picture-in-picture.
    take("subtitle", counts["subtitle"])
    take("pip_subtitle", counts["pip_subtitle"])
    take("interactive", counts["interactive"])
    take("secondary_audio", counts["secondary_audio"], extra="audio")
    take("secondary_video", counts["secondary_video"], extra="video")

    reader.seek(end)
    return tuple(streams)


def _parse_stream_entry(reader: BitReader, kind: str) -> Stream:
    entry_length = reader.u8()
    entry_end = reader.byte_pos + entry_length
    entry_type = reader.u8()
    pid = 0
    if entry_type in _PID_LEAD:
        reader.read(_PID_LEAD[entry_type])
        pid = reader.u16()
    reader.seek(entry_end)

    attr_length = reader.u8()
    attr_end = reader.byte_pos + attr_length
    coding = reader.u8()
    format_code = 0
    rate_code = 0
    language = ""
    if coding in (0x01, 0x02, 0x1B, 0x20, 0x24, 0xEA):
        format_code = reader.bits(4)
        rate_code = reader.bits(4)
    elif coding in (0x80, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0xA1, 0xA2):
        format_code = reader.bits(4)
        rate_code = reader.bits(4)
        language = reader.ascii(3).rstrip("\x00")
    elif coding in (0x90, 0x91):
        language = reader.ascii(3).rstrip("\x00")
    elif coding == 0x92:
        reader.u8()  # character code
        language = reader.ascii(3).rstrip("\x00")
    reader.seek(attr_end)

    return Stream(
        kind=kind,
        pid=pid,
        coding_type=coding,
        language=language,
        format_code=format_code,
        rate_code=rate_code,
    )


def _skip_reference_block(reader: BitReader, kind: str, end: int) -> None:
    """The bytes a secondary stream carries after its attributes.

    A secondary audio stream names the primary audio streams it may be mixed
    with; a secondary video stream names both its audio and its
    picture-in-picture subtitles. Each list is a count, a reserved byte, the
    entries, and a pad byte when the count is odd. Skipping them is not
    optional: whatever comes next is read from wherever this left off.
    """
    blocks = 2 if kind == "video" else 1
    for _ in range(blocks):
        if reader.byte_pos >= end:
            return
        count = reader.u8()
        reader.u8()  # reserved
        stop = min(reader.byte_pos + count + (count % 2), end)
        reader.seek(stop)


def _parse_play_item(reader: BitReader) -> PlayItem:
    length = reader.u16()
    end = reader.byte_pos + length
    clip_id = reader.ascii(5)
    codec_id = reader.ascii(4)
    reader.bits(11)  # reserved
    is_multi_angle = reader.bits(1)
    connection_condition = reader.bits(4)
    reader.u8()  # ref_to_STC_id
    in_time = reader.u32()
    out_time = reader.u32()
    reader.read(8)  # UO mask table
    reader.bits(1)  # random access flag
    reader.bits(7)  # reserved
    still_mode = reader.u8()
    # The 16 bits after still_mode are always there: still_time on a timed
    # still, reserved otherwise. Reading them conditionally puts every later
    # field two bytes out, which is how the STN table goes missing.
    trailing = reader.u16()
    still_seconds = trailing if still_mode == 0x01 else 0

    if is_multi_angle:
        angle_count = reader.u8()
        reader.u8()  # flags
        for _ in range(max(0, angle_count - 1)):
            reader.read(10)  # clip id + codec id + STC id for each extra angle

    streams = _parse_stn_table(reader)
    reader.seek(end)
    return PlayItem(
        clip_id=clip_id,
        codec_id=codec_id,
        in_time=in_time,
        out_time=out_time,
        still_mode=still_mode,
        still_seconds=still_seconds,
        connection_condition=connection_condition,
        streams=streams,
    )


def _parse_marks(reader: BitReader) -> tuple[Mark, ...]:
    reader.u32()  # length
    count = reader.u16()
    marks: list[Mark] = []
    for _ in range(count):
        reader.u8()  # reserved
        mark_type = reader.u8()
        play_item_id = reader.u16()
        timestamp = reader.u32()
        reader.u16()  # entry ES PID
        duration = reader.u32()
        marks.append(
            Mark(
                mark_type=mark_type,
                play_item_id=play_item_id,
                timestamp=timestamp,
                duration=duration,
            )
        )
    return tuple(marks)


def parse(data: bytes, name: str = "") -> Playlist:
    """Parse ``.mpls`` bytes. Raises :class:`MplsError` on anything unreadable."""
    try:
        reader = BitReader(data)
        magic = reader.read(4)
        if magic != MPLS_MAGIC:
            raise MplsError(f"not a playlist: magic {magic!r}")
        version = reader.ascii(4)
        if version not in SUPPORTED_VERSIONS:
            raise MplsError(f"unsupported playlist version {version!r}")
        playlist_start = reader.u32()
        marks_start = reader.u32()
        reader.u32()  # extension data start

        reader.seek(40)  # AppInfoPlayList
        reader.u32()  # length
        reader.u8()  # reserved
        playback_type = reader.u8()
        playback_count = reader.u16()

        reader.seek(playlist_start)
        reader.u32()  # length
        reader.u16()  # reserved
        item_count = reader.u16()
        sub_path_count = reader.u16()
        items = tuple(_parse_play_item(reader) for _ in range(item_count))

        marks: tuple[Mark, ...] = ()
        if marks_start:
            reader.seek(marks_start)
            marks = _parse_marks(reader)
    except TruncatedError as exc:
        raise MplsError(f"playlist is truncated: {exc}") from exc

    return Playlist(
        name=name,
        version=version,
        playback_type=playback_type,
        playback_count=playback_count,
        play_items=items,
        marks=marks,
        sub_path_count=sub_path_count,
    )


def read(path: Path) -> Playlist:
    """Parse the playlist at ``path``, named after the file."""
    return parse(path.read_bytes(), name=path.stem)


#: How long reading a whole PLAYLIST folder may take before we stop and work
#: with what we have. A real disc is done in milliseconds. This is here for
#: the disc that is not real: a folder of large files that parse slowly is
#: otherwise seconds of a window that has stopped painting, every time the
#: disc goes in.
READ_ALL_SECONDS = 4.0

#: And how many playlists to read at all. Discs with more than this exist
#: only as an attempt to make a player do work.
MAX_PLAYLISTS = 2000


def read_all(playlist_dir: Path) -> list[Playlist]:
    """Every readable playlist in a ``PLAYLIST`` directory, in file order.

    Unreadable playlists are skipped rather than fatal: one bad file on a
    scratched disc must not hide the other twenty. And the whole walk is on a
    clock, because the caller is a disc going into a drive and somebody
    watching the window.
    """
    out: list[Playlist] = []
    deadline = time.monotonic() + READ_ALL_SECONDS
    for path in sorted(playlist_dir.glob("*.mpls"))[:MAX_PLAYLISTS]:
        try:
            out.append(read(path))
        except (MplsError, OSError):
            continue
        if time.monotonic() > deadline:
            break
    return out


def main_feature(playlists: list[Playlist]) -> Playlist | None:
    """The playlist "Play main feature" should start.

    The longest non-menu playlist, which is what every disc in practice makes
    the feature. Ties break towards the lower file name so the answer is
    stable across runs.
    """
    candidates = [pl for pl in playlists if not pl.looks_like_menu and pl.duration_ms > 0]
    if not candidates:
        candidates = [pl for pl in playlists if pl.duration_ms > 0]
    if not candidates:
        return None
    return min(candidates, key=lambda pl: (-pl.duration_ms, pl.name))
