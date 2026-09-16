"""Read a DVD's structure from its own IFO files.

The Player does not ship a DVD engine, and that is deliberate: the ones that
exist carry a CSS descrambler, and we would rather pay for the key than break
the lock. So DVD support is built the same way Blu-ray support is — we read
the disc's own tables ourselves, and hand libvlc the video.

The happy consequence is that there is no encrypted path anywhere in this
code. It reads `VIDEO_TS.IFO` and `VTS_nn_0.IFO`, which are never scrambled on
any disc, and works out titles, chapters, durations and stream lists. The
video is then the VOB files, which libvlc plays as the program streams they
are. On a protected disc the VOBs are scrambled, playback fails, and the
Player says so plainly. Nothing here can decrypt anything, by construction.

Field layouts follow libdvdread's ``ifo_types.h``, which is the practical
authority on what real discs contain.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

#: A DVD sector. Every offset in an IFO is counted in these.
SECTOR = 2048

VMG_MAGIC = b"DVDVIDEO-VMG"
VTS_MAGIC = b"DVDVIDEO-VTS"

# The format's own maxima. Every count in an IFO is a 16-bit field the disc
# fills in, and a disc that lies about one is either damaged or hostile.
# Clamping to what the specification allows costs nothing on a real disc and
# is the difference between a bad disc and a hung program.

#: DVD-Video allows 99 titles in a title set, and 99 across the disc.
MAX_TITLES_PER_SET = 99
MAX_TITLES = 99
#: And 99 chapters in a title.
MAX_CHAPTERS = 99
#: Program chains per table. The specification's own ceiling.
MAX_CHAINS = 999

#: Menu language units on a disc. DVD-Video allows sixteen; this is generous
#: to a disc that stretched the format, and still not 65535.
MAX_LANGUAGE_UNITS = 64

#: And how many menus to collect in total, across every language. A disc with
#: more than this is not a disc with a lot of menus, and the count is read on
#: insertion while somebody waits for a window to paint.
MAX_MENUS = 2000

#: Where the sixteen-colour palette sits inside a program chain. Used, not
#: decorative: it was defined here and the parser called with the literal,
#: so changing it changed nothing and a test could not tell.
_PGC_PALETTE = 0xA4

#: Where the tables live in VMGI_MAT and VTSI_MAT, in sectors.
_VMG_TT_SRPT = 0xC4
_VTS_TITLE_VOBS = 0xC4
_VTS_PTT_SRPT = 0xC8
_VTS_PGCIT = 0xCC

#: VTS stream attributes.
_VTS_VIDEO_ATTR = 0x200
_VTS_AUDIO_COUNT = 0x203
_VTS_AUDIO_ATTR = 0x204
_VTS_SUBP_COUNT = 0x255
_VTS_SUBP_ATTR = 0x256

_AUDIO_FORMATS = {0: "AC-3", 2: "MPEG-1", 3: "MPEG-2", 4: "LPCM", 6: "DTS"}
_AUDIO_CHANNELS = {0: "mono", 1: "stereo"}


class IfoError(ValueError):
    """This is not a DVD structure we can read."""


def _u8(data: bytes, offset: int) -> int:
    return data[offset]


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _bcd(value: int) -> int:
    return ((value >> 4) & 0x0F) * 10 + (value & 0x0F)


def dvd_time_ms(data: bytes, offset: int) -> int:
    """A ``dvd_time_t``: BCD hours, minutes, seconds, then frames and a rate.

    The top two bits of the fourth byte are the frame rate — 0b11 is 30 fps
    (meaning 29.97), 0b10 is 25. Discs in the wild do leave that field zero,
    which is why an unknown rate falls back to 30 rather than dividing by it.
    """
    hours = _bcd(data[offset])
    minutes = _bcd(data[offset + 1])
    seconds = _bcd(data[offset + 2])
    frame_byte = data[offset + 3]
    frames = _bcd(frame_byte & 0x3F)
    rate = {0b11: 30000 / 1001, 0b10: 25.0}.get((frame_byte >> 6) & 0x03, 30000 / 1001)
    total = hours * 3600 + minutes * 60 + seconds
    return int(total * 1000 + (frames / rate) * 1000)


@dataclass(frozen=True)
class AudioStream:
    number: int
    coding: str
    language: str
    channels: int

    @property
    def name(self) -> str:
        parts = [self.language.upper() if self.language else f"Track {self.number + 1}"]
        parts.append(self.coding)
        if self.channels:
            parts.append(_AUDIO_CHANNELS.get(self.channels - 1, f"{self.channels}ch"))
        return " ".join(parts)


@dataclass(frozen=True)
class SubtitleStream:
    number: int
    language: str

    @property
    def name(self) -> str:
        return self.language.upper() if self.language else f"Subtitle {self.number + 1}"


@dataclass(frozen=True)
class Cell:
    """One cell of a program chain: a span of sectors and how long it runs."""

    first_sector: int
    last_sector: int
    duration_ms: int
    still_seconds: int = 0


@dataclass(frozen=True)
class ProgramChain:
    """A PGC: the thing a DVD actually plays."""

    number: int
    duration_ms: int
    cells: tuple[Cell, ...]
    #: 1-based cell number each program starts at.
    program_cells: tuple[int, ...]
    #: Sixteen colours, as ``(Y << 16) | (Cb << 8) | Cr``. Everything a menu
    #: is drawn in comes out of this: the subpicture's four colours are four
    #: indices into it, and so are the four a lit button uses.
    palette: tuple[int, ...] = ()

    def program_start_ms(self, program: int) -> int:
        """Where program ``program`` (1-based) starts, from the PGC's start."""
        if program < 1 or program > len(self.program_cells):
            return 0
        first_cell = self.program_cells[program - 1]
        if first_cell < 1:
            # Cell numbers are 1-based and come off the disc unchecked, so a
            # zero means cells[:-1] — the sum of every cell but the last, i.e.
            # chapter one placed nine minutes into a ten-minute film. It goes
            # straight onto the scrub bar and into the next-chapter key.
            return 0
        return sum(cell.duration_ms for cell in self.cells[: first_cell - 1])

    @property
    def first_sector(self) -> int:
        return self.cells[0].first_sector if self.cells else 0


@dataclass(frozen=True)
class Title:
    """A title as the disc's own table of contents lists it."""

    number: int
    title_set: int
    title_set_title: int
    chapter_count: int
    angle_count: int
    duration_ms: int = 0
    chapters_ms: tuple[int, ...] = ()
    audio: tuple[AudioStream, ...] = ()
    subtitles: tuple[SubtitleStream, ...] = ()
    #: Where in the title set's VOB stream this title starts.
    start_ms: int = 0

    @property
    def name(self) -> str:
        return f"Title {self.number}"


@dataclass(frozen=True)
class Disc:
    """A whole DVD, read from its IFOs."""

    root: Path
    titles: tuple[Title, ...] = ()
    title_set_count: int = 0

    @property
    def main_feature(self) -> Title | None:
        """The longest title, which is the feature on every disc in practice."""
        timed = [title for title in self.titles if title.duration_ms]
        if not timed:
            return self.titles[0] if self.titles else None
        return max(timed, key=lambda title: title.duration_ms)

    def title(self, number: int) -> Title | None:
        for entry in self.titles:
            if entry.number == number:
                return entry
        return None

    def vob_files(self, title: Title) -> list[Path]:
        """The VOB files a title's video lives in, in order.

        ``VTS_01_0.VOB`` is the title set's *menu*, not its content, so it is
        left out — including it would put the menu in front of the film.
        """
        video_ts = self.root / "VIDEO_TS"
        if not video_ts.is_dir():
            video_ts = self.root
        return sorted(
            path
            for path in video_ts.glob(f"VTS_{title.title_set:02d}_[1-9].VOB")
            if path.is_file()
        )


def _parse_tt_srpt(data: bytes) -> list[Title]:
    """VMG's title search pointer table: every title on the disc."""
    start = _u32(data, _VMG_TT_SRPT) * SECTOR
    if start == 0 or start + 8 > len(data):
        raise IfoError("this DVD has no title table")
    count = min(_u16(data, start), MAX_TITLES)
    titles: list[Title] = []
    for index in range(count):
        entry = start + 8 + index * 12
        if entry + 12 > len(data):
            break
        titles.append(
            Title(
                number=index + 1,
                angle_count=_u8(data, entry + 1),
                chapter_count=_u16(data, entry + 2),
                title_set=_u8(data, entry + 6),
                title_set_title=_u8(data, entry + 7),
            )
        )
    return titles


def _parse_pgc(data: bytes, offset: int, number: int) -> ProgramChain:
    program_count = _u8(data, offset + 0x02)
    cell_count = _u8(data, offset + 0x03)
    duration = dvd_time_ms(data, offset + 0x04)
    program_map_offset = _u16(data, offset + 0xE6)
    cell_playback_offset = _u16(data, offset + 0xE8)

    program_cells: list[int] = []
    for index in range(program_count):
        position = offset + program_map_offset + index
        if position < len(data):
            program_cells.append(_u8(data, position))

    cells: list[Cell] = []
    for index in range(cell_count):
        base = offset + cell_playback_offset + index * 24
        if base + 24 > len(data):
            break
        cells.append(
            Cell(
                still_seconds=_u8(data, base + 0x02),
                duration_ms=dvd_time_ms(data, base + 0x04),
                first_sector=_u32(data, base + 0x08),
                last_sector=_u32(data, base + 0x14),
            )
        )
    return ProgramChain(
        number=number,
        duration_ms=duration,
        cells=tuple(cells),
        program_cells=tuple(program_cells),
        palette=_parse_palette(data, offset + _PGC_PALETTE),
    )


def _parse_palette(data: bytes, offset: int) -> tuple[int, ...]:
    """A program chain's sixteen colours.

    Stored on the disc as four bytes per entry: a reserved byte, then Y, Cr,
    Cb. Returned as ``(Y << 16) | (Cb << 8) | Cr`` — Cb and Cr swapped round
    — because that is the order :func:`dvd_spu.resolve_palette` expects, and
    doing it once here beats doing it at every call site and getting it wrong
    at one of them.
    """
    if offset + 64 > len(data):
        return ()
    out: list[int] = []
    for index in range(16):
        base = offset + index * 4
        luma = data[base + 1]
        chroma_red = data[base + 2]
        chroma_blue = data[base + 3]
        out.append((luma << 16) | (chroma_blue << 8) | chroma_red)
    return tuple(out)


def _parse_pgcit(data: bytes, start: int) -> dict[int, ProgramChain]:
    if start == 0 or start + 8 > len(data):
        return {}
    count = min(_u16(data, start), MAX_CHAINS)
    chains: dict[int, ProgramChain] = {}
    for index in range(count):
        entry = start + 8 + index * 8
        if entry + 8 > len(data):
            break
        pgc_offset = start + _u32(data, entry + 4)
        if pgc_offset + 0xEC > len(data):
            continue
        chains[index + 1] = _parse_pgc(data, pgc_offset, index + 1)
    return chains


def _parse_ptt_srpt(data: bytes, start: int) -> list[list[tuple[int, int]]]:
    """Per title in this set, the chapters as (program chain, program).

    Every number here comes off the disc, and two of them used to be trusted.
    A table claiming 65535 titles whose offsets alternate between 0 and 4 GB
    makes half of them re-scan the whole file in four-byte steps: no read goes
    out of bounds, nothing raises, and the Player sits there allocating until
    the machine gives up. It happens on insertion, before anybody has pressed
    anything.

    So: the format's own maxima are enforced, and an offset table that does
    not climb is refused rather than walked.
    """
    if start == 0 or start + 8 > len(data):
        return []
    count = min(_u16(data, start), MAX_TITLES_PER_SET)
    if start + 8 + count * 4 > len(data):
        return []
    last_byte = min(_u32(data, start + 4), len(data))
    offsets = [_u32(data, start + 8 + index * 4) for index in range(count)]

    titles: list[list[tuple[int, int]]] = []
    for index, offset in enumerate(offsets):
        end = offsets[index + 1] if index + 1 < len(offsets) else last_byte + 1
        chapters: list[tuple[int, int]] = []
        position = start + offset
        # A title's chapter list runs from its own offset to the next one.
        # An entry that does not move forward is a corrupt table, not a
        # title with a lot of chapters.
        stop = min(start + end, len(data), position + MAX_CHAPTERS * 4)
        while position + 4 <= stop:
            chapters.append((_u16(data, position), _u16(data, position + 2)))
            position += 4
        titles.append(chapters)
    return titles


def _parse_streams(data: bytes) -> tuple[tuple[AudioStream, ...], tuple[SubtitleStream, ...]]:
    audio: list[AudioStream] = []
    count = min(_u8(data, _VTS_AUDIO_COUNT), 8)
    for index in range(count):
        base = _VTS_AUDIO_ATTR + index * 8
        if base + 8 > len(data):
            break
        attributes = _u8(data, base)
        coding = _AUDIO_FORMATS.get((attributes >> 5) & 0x07, "unknown")
        channels = (_u8(data, base + 1) & 0x07) + 1
        language = ""
        if (attributes >> 2) & 0x03 == 1:
            language = data[base + 2 : base + 4].decode("latin-1").strip("\x00 ")
        audio.append(
            AudioStream(number=index, coding=coding, language=language, channels=channels)
        )

    subtitles: list[SubtitleStream] = []
    count = min(_u8(data, _VTS_SUBP_COUNT), 32)
    for index in range(count):
        base = _VTS_SUBP_ATTR + index * 6
        if base + 6 > len(data):
            break
        language = ""
        if (_u8(data, base) >> 2) & 0x03 == 1:
            language = data[base + 2 : base + 4].decode("latin-1").strip("\x00 ")
        subtitles.append(SubtitleStream(number=index, language=language))
    return tuple(audio), tuple(subtitles)


def _video_ts(root: Path) -> Path:
    if (root / "VIDEO_TS").is_dir():
        return root / "VIDEO_TS"
    if root.name.upper() == "VIDEO_TS":
        return root
    return root / "VIDEO_TS"


def read(root: Path) -> Disc:
    """Read a DVD at ``root`` — a drive, a folder, or a VIDEO_TS directory."""
    video_ts = _video_ts(root)
    vmg_path = video_ts / "VIDEO_TS.IFO"
    if not vmg_path.is_file():
        raise IfoError("no VIDEO_TS.IFO, so this is not a DVD-Video disc")
    try:
        vmg = vmg_path.read_bytes()
    except OSError as exc:
        raise IfoError(f"VIDEO_TS.IFO could not be read: {exc}") from exc
    if not vmg.startswith(VMG_MAGIC):
        raise IfoError("VIDEO_TS.IFO does not start the way a DVD's does")

    try:
        titles = _parse_tt_srpt(vmg)
    except (struct.error, IndexError) as exc:
        raise IfoError(f"the title table is damaged: {exc}") from exc
    by_set: dict[int, list[Title]] = {}
    for title in titles:
        by_set.setdefault(title.title_set, []).append(title)

    filled: list[Title] = []
    for title_set, group in sorted(by_set.items()):
        vts_path = video_ts / f"VTS_{title_set:02d}_0.IFO"
        if not vts_path.is_file():
            filled.extend(group)
            continue
        try:
            vts = vts_path.read_bytes()
        except OSError:
            filled.extend(group)
            continue
        if not vts.startswith(VTS_MAGIC):
            filled.extend(group)
            continue

        try:
            chains = _parse_pgcit(vts, _u32(vts, _VTS_PGCIT) * SECTOR)
            chapters_by_title = _parse_ptt_srpt(vts, _u32(vts, _VTS_PTT_SRPT) * SECTOR)
            audio, subtitles = _parse_streams(vts)
        except (struct.error, IndexError):
            # One damaged title set should not hide the rest of the disc.
            filled.extend(group)
            continue

        # Titles inside one set share its VOB stream, so a title's own start
        # is where its first program chain starts within that stream.
        #
        # Worked out once for the whole set, not once per chapter mark. It
        # used to be a sum over the whole chain table inside a double loop,
        # which at the format's own maxima is ~9900 walks of 999 entries:
        # 1.5 seconds of pure CPU, and _play_dvd_title runs read() again on
        # the GUI thread for every title change and every menu Play button.
        starts = _chain_starts(chains)
        for title in group:
            index = title.title_set_title - 1
            entries = (
                chapters_by_title[index] if 0 <= index < len(chapters_by_title) else []
            )
            marks: list[int] = []
            duration = 0
            start_ms = 0
            if entries:
                first_chain = chains.get(entries[0][0])
                if first_chain is not None:
                    start_ms = starts.get(entries[0][0], 0)
                    duration = first_chain.duration_ms
                for chain_number, program in entries:
                    chain = chains.get(chain_number)
                    if chain is None:
                        continue
                    marks.append(
                        starts.get(chain_number, 0)
                        - start_ms
                        + chain.program_start_ms(program)
                    )
            filled.append(
                Title(
                    number=title.number,
                    title_set=title.title_set,
                    title_set_title=title.title_set_title,
                    chapter_count=title.chapter_count,
                    angle_count=title.angle_count,
                    duration_ms=duration,
                    chapters_ms=tuple(sorted({mark for mark in marks if mark >= 0})),
                    audio=audio,
                    subtitles=subtitles,
                    start_ms=start_ms,
                )
            )

    filled.sort(key=lambda title: title.number)
    return Disc(root=root, titles=tuple(filled), title_set_count=len(by_set))


def _chain_starts(chains: dict[int, ProgramChain]) -> dict[int, int]:
    """Where every program chain starts within its title set's stream.

    One pass in chain order, carrying a running total. The version this
    replaced summed the whole table afresh for every chapter mark on the
    disc, which is the same answer computed thousands of times.
    """
    running = 0
    starts: dict[int, int] = {}
    for number in sorted(chains):
        starts[number] = running
        running += chains[number].duration_ms
    return starts


# --------------------------------------------------------------------------
# Menus
#
# A disc's menus are program chains like any other, kept in a separate table
# indexed by language and by what kind of menu each one is. Finding the root
# menu means: open the language unit table, pick a language, then find the
# chain whose entry id says "root".
#
# There are two of these tables. VMGM_PGCI_UT in VIDEO_TS.IFO holds the disc's
# own menus; VTSM_PGCI_UT in each VTS_nn_0.IFO holds that title set's. Most
# discs put the menu people actually see in the title set's table.
# --------------------------------------------------------------------------

_VMG_PGCI_UT = 0xC8
_VTS_PGCI_UT = 0xD0
_VMG_MENU_VOBS = 0xC0
_VTS_MENU_VOBS = 0xC0

#: What the low nibble of a menu chain's entry id means.
MENU_KINDS = {
    2: "title",
    3: "root",
    4: "subtitle",
    5: "audio",
    6: "angle",
    7: "chapter",
}


@dataclass(frozen=True)
class Menu:
    """One menu on a disc: which chain plays it, and what kind it is."""

    kind: str
    language: str
    chain: ProgramChain
    #: Which table this came from: "disc" or "title-set".
    domain: str = "title-set"
    title_set: int = 0

    @property
    def name(self) -> str:
        return {
            "root": "Main menu",
            "title": "Title menu",
            "chapter": "Chapter menu",
            "audio": "Audio menu",
            "subtitle": "Subtitle menu",
            "angle": "Angle menu",
        }.get(self.kind, self.kind.title())


@dataclass(frozen=True)
class MenuSet:
    """Every menu found on a disc, and the files their video is in."""

    menus: tuple[Menu, ...] = ()
    #: Menu video lives in VIDEO_TS.VOB or VTS_nn_0.VOB, never the title VOBs.
    vob_files: tuple[Path, ...] = ()

    @property
    def has_menus(self) -> bool:
        return bool(self.menus)

    def of_kind(self, kind: str) -> Menu | None:
        for menu in self.menus:
            if menu.kind == kind:
                return menu
        return None

    @property
    def root(self) -> Menu | None:
        """What pressing "menu" should show: the root, or the next best thing."""
        for kind in ("root", "title", "chapter"):
            found = self.of_kind(kind)
            if found is not None:
                return found
        return self.menus[0] if self.menus else None


def _parse_pgci_ut(data: bytes, start: int, *, domain: str, title_set: int) -> list[Menu]:
    if start == 0 or start + 8 > len(data):
        return []
    try:
        # Both counts are unclamped u16s off the disc, and this runs on
        # insertion — identify() calls it only to decide whether to light the
        # Menu button. 65535 units of 65535 chains never finished: 24 MB to
        # 744 MB in twenty-five seconds and still climbing, with the window
        # not painting. The chain table next door has had MAX_CHAINS since
        # the day it was written; this one never got it.
        unit_count = min(_u16(data, start), MAX_LANGUAGE_UNITS)
        menus: list[Menu] = []
        for index in range(unit_count):
            if len(menus) >= MAX_MENUS:
                break
            entry = start + 8 + index * 8
            if entry + 8 > len(data):
                break
            language = data[entry : entry + 2].decode("latin-1").strip("\x00 ")
            unit_start = start + _u32(data, entry + 4)
            if unit_start + 8 > len(data):
                continue

            chain_count = min(_u16(data, unit_start), MAX_CHAINS)
            for chain_index in range(chain_count):
                if len(menus) >= MAX_MENUS:
                    break
                srp = unit_start + 8 + chain_index * 8
                if srp + 8 > len(data):
                    break
                entry_id = _u8(data, srp)
                kind = MENU_KINDS.get(entry_id & 0x0F)
                if kind is None:
                    continue
                pgc_offset = unit_start + _u32(data, srp + 4)
                if pgc_offset + 0xEC > len(data):
                    continue
                menus.append(
                    Menu(
                        kind=kind,
                        language=language,
                        chain=_parse_pgc(data, pgc_offset, chain_index + 1),
                        domain=domain,
                        title_set=title_set,
                    )
                )
        return menus
    except (struct.error, IndexError):
        return []


def read_menus(root: Path, title_set: int = 1) -> MenuSet:
    """Every menu on a disc: the title set's own, then the disc's.

    The title set's come first because that is the menu a viewer means when
    they press the menu button during a film.
    """
    video_ts = _video_ts(root)
    menus: list[Menu] = []
    vobs: list[Path] = []

    vts_path = video_ts / f"VTS_{title_set:02d}_0.IFO"
    if vts_path.is_file():
        try:
            vts = vts_path.read_bytes()
            if vts.startswith(VTS_MAGIC):
                menus += _parse_pgci_ut(
                    vts,
                    _u32(vts, _VTS_PGCI_UT) * SECTOR,
                    domain="title-set",
                    title_set=title_set,
                )
                menu_vob = video_ts / f"VTS_{title_set:02d}_0.VOB"
                if _u32(vts, _VTS_MENU_VOBS) and menu_vob.is_file():
                    vobs.append(menu_vob)
        except (OSError, struct.error):
            pass

    vmg_path = video_ts / "VIDEO_TS.IFO"
    if vmg_path.is_file():
        try:
            vmg = vmg_path.read_bytes()
            if vmg.startswith(VMG_MAGIC):
                menus += _parse_pgci_ut(
                    vmg, _u32(vmg, _VMG_PGCI_UT) * SECTOR, domain="disc", title_set=0
                )
                menu_vob = video_ts / "VIDEO_TS.VOB"
                if _u32(vmg, _VMG_MENU_VOBS) and menu_vob.is_file():
                    vobs.append(menu_vob)
        except (OSError, struct.error):
            pass

    return MenuSet(menus=tuple(menus), vob_files=tuple(vobs))
