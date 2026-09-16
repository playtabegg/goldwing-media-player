"""Write a minimal but real VIDEO_TS, so there is a DVD to test against.

`dvdauthor` is not on this machine and does not build on it easily, and the
Player's DVD support has to be tested before a real disc turns up. So the
fixture disc is written here, the same way the Blu-ray one is: the tables by
hand, the video from ffmpeg.

What it produces is a disc structure our reader agrees with and a player can
follow — one title set, one program chain, several cells with real durations,
audio and subtitle attributes. It is not a mastering tool and it does not
pretend to be: no menus, no angles, no seamless branching.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

SECTOR = 2048


def _sectors(payload: bytes) -> bytes:
    """Pad to a whole number of sectors, which every IFO table is."""
    remainder = len(payload) % SECTOR
    return payload + b"\x00" * (SECTOR - remainder) if remainder else payload


def dvd_time(milliseconds: int, frame_rate_code: int = 0b11) -> bytes:
    """A ``dvd_time_t``: BCD hours, minutes, seconds, frames plus a rate."""
    rate = 30000 / 1001 if frame_rate_code == 0b11 else 25.0
    total_seconds, remainder_ms = divmod(max(0, milliseconds), 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    frames = min(int(remainder_ms * rate / 1000), 29)

    def bcd(value: int) -> int:
        return ((value // 10) << 4) | (value % 10)

    return bytes(
        (
            bcd(hours),
            bcd(minutes),
            bcd(seconds),
            (frame_rate_code << 6) | bcd(frames),
        )
    )


@dataclass(frozen=True)
class CellSpec:
    duration_ms: int
    first_sector: int
    last_sector: int


#: Sixteen colours, stored the way a disc stores them: a reserved byte, then
#: Y, Cr, Cb. Black, white, and fourteen greys, which is enough for a menu.
DEFAULT_PALETTE: tuple[int, ...] = tuple(
    (0x00 << 24) | (level << 16) | (0x80 << 8) | 0x80
    for level in (16, 35, 54, 73, 92, 110, 129, 148, 167, 186, 204, 223, 235, 242, 248, 235)
)


@dataclass(frozen=True)
class TitleSpec:
    """One title: its cells, and which cell each chapter starts at."""

    cells: tuple[CellSpec, ...]
    #: 1-based cell number each chapter (program) begins at.
    chapter_cells: tuple[int, ...] = (1,)
    #: The sixteen colours everything this chain draws is made of. A menu
    #: chain needs one; a title chain carries one anyway.
    palette: tuple[int, ...] = DEFAULT_PALETTE

    @property
    def duration_ms(self) -> int:
        return sum(cell.duration_ms for cell in self.cells)


def build_pgc(title: TitleSpec) -> bytes:
    """One program chain."""
    program_count = len(title.chapter_cells)
    cell_count = len(title.cells)

    header = bytearray(0xEC)
    header[0x02] = program_count
    header[0x03] = cell_count
    header[0x04:0x08] = dvd_time(title.duration_ms)

    # The palette: sixteen four-byte entries at 0xA4. A menu chain without
    # one is a menu drawn in whatever the player guesses.
    for index, entry in enumerate(title.palette[:16]):
        struct.pack_into(">I", header, 0xA4 + index * 4, entry)

    program_map = bytes(title.chapter_cells)
    cell_playback = bytearray()
    for cell in title.cells:
        entry = bytearray(24)
        entry[0x04:0x08] = dvd_time(cell.duration_ms)
        struct.pack_into(">I", entry, 0x08, cell.first_sector)
        struct.pack_into(">I", entry, 0x14, cell.last_sector)
        cell_playback += entry
    cell_position = b"\x00\x00\x00\x01" * cell_count

    program_map_offset = len(header)
    cell_playback_offset = program_map_offset + len(program_map)
    cell_position_offset = cell_playback_offset + len(cell_playback)
    struct.pack_into(">H", header, 0xE6, program_map_offset)
    struct.pack_into(">H", header, 0xE8, cell_playback_offset)
    struct.pack_into(">H", header, 0xEA, cell_position_offset)

    return bytes(header) + program_map + bytes(cell_playback) + cell_position


def build_pgcit(titles: list[TitleSpec]) -> bytes:
    """The program chain table: one chain per title in this set."""
    chains = [build_pgc(title) for title in titles]
    header_size = 8 + len(chains) * 8
    body = bytearray()
    offsets: list[int] = []
    for chain in chains:
        offsets.append(header_size + len(body))
        body += chain

    out = bytearray()
    out += struct.pack(">HH", len(chains), 0)
    out += struct.pack(">I", header_size + len(body) - 1)
    for index, offset in enumerate(offsets):
        out += bytes((index + 1, 0))
        out += struct.pack(">H", 0)
        out += struct.pack(">I", offset)
    out += body
    return bytes(out)


def build_ptt_srpt(titles: list[TitleSpec]) -> bytes:
    """Chapter search pointers: for each title, its chapters as (pgc, program)."""
    header_size = 8 + len(titles) * 4
    body = bytearray()
    offsets: list[int] = []
    for index, title in enumerate(titles):
        offsets.append(header_size + len(body))
        for program in range(1, len(title.chapter_cells) + 1):
            body += struct.pack(">HH", index + 1, program)

    out = bytearray()
    out += struct.pack(">HH", len(titles), 0)
    out += struct.pack(">I", header_size + len(body) - 1)
    for offset in offsets:
        out += struct.pack(">I", offset)
    out += body
    return bytes(out)


def build_tt_srpt(titles: list[tuple[int, int, int]]) -> bytes:
    """VMG's title table. Each entry is (title_set, title_in_set, chapters)."""
    out = bytearray()
    out += struct.pack(">HH", len(titles), 0)
    out += struct.pack(">I", 8 + len(titles) * 12 - 1)
    for title_set, title_in_set, chapters in titles:
        entry = bytearray(12)
        entry[0x00] = 0x3C  # playback type: one sequential PGC
        entry[0x01] = 1  # angles
        struct.pack_into(">H", entry, 0x02, chapters)
        entry[0x06] = title_set
        entry[0x07] = title_in_set
        struct.pack_into(">I", entry, 0x08, 0)
        out += entry
    return bytes(out)


def build_vmg(titles: list[tuple[int, int, int]], title_set_count: int) -> bytes:
    """``VIDEO_TS.IFO``: the disc's own table of contents."""
    header = bytearray(SECTOR)
    header[0x00:0x0C] = b"DVDVIDEO-VMG"
    header[0x21] = 0x11  # specification version 1.1
    struct.pack_into(">H", header, 0x3E, title_set_count)
    struct.pack_into(">I", header, 0x80, SECTOR - 1)
    struct.pack_into(">I", header, 0xC4, 1)  # TT_SRPT lives in sector 1

    tt_srpt = _sectors(build_tt_srpt(titles))
    struct.pack_into(">I", header, 0x0C, (SECTOR + len(tt_srpt)) // SECTOR - 1)
    struct.pack_into(">I", header, 0x1C, (SECTOR + len(tt_srpt)) // SECTOR - 1)
    return bytes(header) + tt_srpt


def build_vts(
    titles: list[TitleSpec],
    *,
    audio_languages: tuple[str, ...] = ("en",),
    subtitle_languages: tuple[str, ...] = (),
    menus: dict[str, TitleSpec] | None = None,
) -> bytes:
    """``VTS_nn_0.IFO``: one title set's chains, chapters and streams."""
    header = bytearray(SECTOR)
    header[0x00:0x0C] = b"DVDVIDEO-VTS"
    header[0x21] = 0x11

    header[0x203] = len(audio_languages)
    for index, language in enumerate(audio_languages):
        base = 0x204 + index * 8
        # coding 0 = AC-3, and "a language is present" in bits 2-3.
        header[base] = (0 << 5) | (1 << 2)
        header[base + 1] = 0x01  # two channels
        header[base + 2 : base + 4] = language.encode("latin-1")[:2].ljust(2, b" ")

    header[0x255] = len(subtitle_languages)
    for index, language in enumerate(subtitle_languages):
        base = 0x256 + index * 6
        header[base] = 1 << 2
        header[base + 2 : base + 4] = language.encode("latin-1")[:2].ljust(2, b" ")

    ptt_srpt = _sectors(build_ptt_srpt(titles))
    pgcit = _sectors(build_pgcit(titles))
    pgci_ut = _sectors(build_pgci_ut(menus)) if menus else b""

    ptt_sector = 1
    pgcit_sector = ptt_sector + len(ptt_srpt) // SECTOR
    pgci_ut_sector = pgcit_sector + len(pgcit) // SECTOR
    struct.pack_into(">I", header, 0xC8, ptt_sector)
    struct.pack_into(">I", header, 0xCC, pgcit_sector)
    if pgci_ut:
        struct.pack_into(">I", header, 0xC0, 1)  # the menu VOB exists
        struct.pack_into(">I", header, 0xD0, pgci_ut_sector)
    # Where the title VOBs begin, after every table.
    struct.pack_into(
        ">I", header, 0xC4, pgci_ut_sector + len(pgci_ut) // SECTOR
    )

    total = SECTOR + len(ptt_srpt) + len(pgcit) + len(pgci_ut)
    struct.pack_into(">I", header, 0x1C, total // SECTOR - 1)
    struct.pack_into(">I", header, 0x0C, total // SECTOR - 1)
    struct.pack_into(">I", header, 0x80, total - 1)
    return bytes(header) + ptt_srpt + pgcit + pgci_ut


def write_video_ts(
    root: Path,
    vob: Path,
    *,
    title: TitleSpec,
    audio_languages: tuple[str, ...] = ("en",),
    subtitle_languages: tuple[str, ...] = (),
    menus: dict[str, TitleSpec] | None = None,
    menu_vob: Path | None = None,
) -> Path:
    """Write a one-title-set DVD around an existing VOB."""
    video_ts = root / "VIDEO_TS"
    video_ts.mkdir(parents=True, exist_ok=True)

    vmg = build_vmg([(1, 1, len(title.chapter_cells))], title_set_count=1)
    (video_ts / "VIDEO_TS.IFO").write_bytes(vmg)
    (video_ts / "VIDEO_TS.BUP").write_bytes(vmg)

    vts = build_vts(
        [title],
        audio_languages=audio_languages,
        subtitle_languages=subtitle_languages,
        menus=menus,
    )
    (video_ts / "VTS_01_0.IFO").write_bytes(vts)
    (video_ts / "VTS_01_0.BUP").write_bytes(vts)

    if menus and menu_vob is not None and menu_vob.is_file():
        (video_ts / "VTS_01_0.VOB").write_bytes(menu_vob.read_bytes())

    payload = vob.read_bytes()
    (video_ts / "VTS_01_1.VOB").write_bytes(payload)
    return root


# --------------------------------------------------------------------------
# NAV packs
#
# A DVD's menu buttons are not in its IFOs — they are in a NAV pack at the
# head of every VOBU, inside the video itself. ffmpeg writes the frame of one
# and leaves every field zero, because it is a muxer and not an authoring
# tool, so the fixture menus are written here.
#
# The sector layout, confirmed against ffmpeg's own output:
#
#     0     pack header            14 bytes
#     14    system header          24 bytes
#     38    PCI  (substream 0x00)   6 + 980 bytes
#     1024  DSI  (substream 0x01)   6 + 1018 bytes
#     2048  end
# --------------------------------------------------------------------------

PCI_PES_LENGTH = 0x03D4
DSI_PES_LENGTH = 0x03FA

#: Where the highlight sits inside a PCI payload.
HLI_OFFSET = 0x60
BTNI_OFFSET = HLI_OFFSET + 22 + 24
BTNI_SIZE = 18


@dataclass(frozen=True)
class ButtonSpec:
    """One menu button: where it is, where it leads, and what it does."""

    x_start: int
    y_start: int
    x_end: int
    y_end: int
    command: bytes = b"\x00" * 8
    up: int = 0
    down: int = 0
    left: int = 0
    right: int = 0
    auto_action: bool = False
    colour_set: int = 0


class _BitPacker:
    def __init__(self) -> None:
        self._bits: list[int] = []

    def add(self, value: int, width: int) -> None:
        for shift in range(width - 1, -1, -1):
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


def build_button(button: ButtonSpec) -> bytes:
    packer = _BitPacker()
    packer.add(button.colour_set, 2)
    packer.add(button.x_start, 10)
    packer.add(0, 2)
    packer.add(button.x_end, 10)
    packer.add(1 if button.auto_action else 0, 2)
    packer.add(button.y_start, 10)
    packer.add(0, 2)
    packer.add(button.y_end, 10)
    packer.add(0, 2)
    packer.add(button.up, 6)
    packer.add(0, 2)
    packer.add(button.down, 6)
    packer.add(0, 2)
    packer.add(button.left, 6)
    packer.add(0, 2)
    packer.add(button.right, 6)
    body = packer.to_bytes()
    if len(body) != 10:
        raise ValueError(f"a button's fields pack to 10 bytes, got {len(body)}")
    return body + button.command.ljust(8, b"\x00")[:8]


#: A button colour set, as a disc writes it: palette indices in the top
#: sixteen bits (emphasis 2, emphasis 1, pattern, background) and opacities
#: in the bottom sixteen, same order. This one lights a button up in white
#: with the background left clear.
SELECTED_COLOURS = 0x0F00_FF00
ACTION_COLOURS = 0x0E00_FF00


def build_pci(
    *,
    start_pts: int,
    end_pts: int,
    buttons: tuple[ButtonSpec, ...] = (),
    selected: int = 1,
    activated: int = 0,
    highlight_start_pts: int = 0,
    highlight_end_pts: int = 0,
    colour_sets: tuple[tuple[int, int], ...] = ((SELECTED_COLOURS, ACTION_COLOURS),),
) -> bytes:
    payload = bytearray(PCI_PES_LENGTH - 1)
    struct.pack_into(">I", payload, 0x00, 0)  # nv_pck_lbn
    struct.pack_into(">I", payload, 0x0C, start_pts)
    struct.pack_into(">I", payload, 0x10, end_pts)

    if buttons:
        # hli_ss 1 = "a new highlight starts here".
        struct.pack_into(">H", payload, HLI_OFFSET, 1)
        struct.pack_into(">I", payload, HLI_OFFSET + 2, highlight_start_pts or start_pts)
        struct.pack_into(">I", payload, HLI_OFFSET + 6, highlight_end_pts or end_pts)
        payload[HLI_OFFSET + 0x10] = 0  # btn_ofn
        payload[HLI_OFFSET + 0x11] = len(buttons)
        payload[HLI_OFFSET + 0x14] = selected
        payload[HLI_OFFSET + 0x15] = activated
        # btn_coli: three groups, two words each, right after the header.
        for index, (selection, action) in enumerate(colour_sets[:3]):
            base = HLI_OFFSET + 22 + index * 8
            struct.pack_into(">I", payload, base, selection)
            struct.pack_into(">I", payload, base + 4, action)
        for index, button in enumerate(buttons):
            base = BTNI_OFFSET + index * BTNI_SIZE
            payload[base : base + BTNI_SIZE] = build_button(button)
    return bytes(payload)


def build_dsi(*, sector: int, vobu_sectors: int, vob_id: int = 1, cell_id: int = 1) -> bytes:
    payload = bytearray(DSI_PES_LENGTH - 1)
    struct.pack_into(">I", payload, 0x04, sector)
    struct.pack_into(">I", payload, 0x08, vobu_sectors)
    struct.pack_into(">H", payload, 0x18, vob_id)
    payload[0x1B] = cell_id
    return bytes(payload)


def build_nav_pack(
    *,
    sector: int,
    start_pts: int,
    end_pts: int,
    vobu_sectors: int,
    buttons: tuple[ButtonSpec, ...] = (),
    selected: int = 1,
    vob_id: int = 1,
    cell_id: int = 1,
    colour_sets: tuple[tuple[int, int], ...] = ((SELECTED_COLOURS, ACTION_COLOURS),),
) -> bytes:
    """One 2048-byte NAV pack, the way a real VOBU starts."""
    out = bytearray()
    # Pack header: the start code, an SCR of zero with its marker bits, a mux
    # rate, and no stuffing.
    out += b"\x00\x00\x01\xba"
    out += bytes((0x44, 0x00, 0x04, 0x00, 0x04, 0x01))
    out += bytes((0x01, 0x89, 0xC3))
    out += bytes((0xF8,))
    # System header.
    system = bytes(18)
    out += b"\x00\x00\x01\xbb" + struct.pack(">H", len(system)) + system

    pci = build_pci(
        start_pts=start_pts,
        end_pts=end_pts,
        buttons=buttons,
        selected=selected,
        colour_sets=colour_sets,
    )
    out += b"\x00\x00\x01\xbf" + struct.pack(">H", PCI_PES_LENGTH) + b"\x00" + pci

    dsi = build_dsi(sector=sector, vobu_sectors=vobu_sectors, vob_id=vob_id, cell_id=cell_id)
    out += b"\x00\x00\x01\xbf" + struct.pack(">H", DSI_PES_LENGTH) + b"\x01" + dsi

    if len(out) != SECTOR:
        raise ValueError(f"a NAV pack is one sector, built {len(out)} bytes")
    return bytes(out)


# --------------------------------------------------------------------------
# Menu tables
#
# A disc's menus live in a table indexed by language, then by what kind of
# menu each chain is. Writing one lets the Player's menu reader be tested
# without a pressed disc.
# --------------------------------------------------------------------------

MENU_IDS = {
    "title": 2,
    "root": 3,
    "subtitle": 4,
    "audio": 5,
    "angle": 6,
    "chapter": 7,
}


def build_pgci_ut(menus: dict[str, TitleSpec], language: str = "en") -> bytes:
    """One language unit holding a chain per menu kind."""
    kinds = list(menus)
    chains = [build_pgc(menus[kind]) for kind in kinds]

    unit_header = 8 + len(chains) * 8
    unit_body = bytearray()
    offsets: list[int] = []
    for chain in chains:
        offsets.append(unit_header + len(unit_body))
        unit_body += chain

    unit = bytearray()
    unit += struct.pack(">HH", len(chains), 0)
    unit += struct.pack(">I", unit_header + len(unit_body) - 1)
    for kind, offset in zip(kinds, offsets, strict=True):
        # The top bit marks an entry point; the low nibble says which menu.
        unit += bytes((0x80 | MENU_IDS[kind], 0))
        unit += struct.pack(">H", 0)
        unit += struct.pack(">I", offset)
    unit += unit_body

    table_header = 8 + 8
    out = bytearray()
    out += struct.pack(">HH", 1, 0)  # one language unit
    out += struct.pack(">I", table_header + len(unit) - 1)
    out += language.encode("latin-1")[:2].ljust(2, b" ")
    out += bytes((0, 0x80 | MENU_IDS["root"]))
    out += struct.pack(">I", table_header)
    out += unit
    return bytes(out)
