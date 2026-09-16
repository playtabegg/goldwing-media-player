"""Read the navigation packets buried in a DVD's video.

A DVD's menus are not in its IFO files. The IFOs say which program chains are
menus; the *buttons* — where they are on screen, which one is selected first,
what each one does, and which button is up, down, left and right of it — live
in a NAV pack at the head of every VOBU, inside the video stream itself.

So a player that wants to show a DVD menu has to read the video looking for
these. That is what this does. It is the first half of driving a DVD menu
without a third-party navigator; the second half is drawing the highlight.

Layouts follow libdvdread's ``nav_types.h``. A NAV pack is one 2048-byte
sector: a pack header, a system header, then two private-stream-2 packets —
PCI (substream 0x00) with the presentation and highlight information, and DSI
(substream 0x01) with the seek pointers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .bitreader import BitReader, TruncatedError

SECTOR = 2048

PACK_START = b"\x00\x00\x01\xba"
SYSTEM_HEADER_START = b"\x00\x00\x01\xbb"
PRIVATE_STREAM_2 = b"\x00\x00\x01\xbf"

SUBSTREAM_PCI = 0x00
SUBSTREAM_DSI = 0x01

#: A DVD menu can carry this many buttons, and no more.
MAX_BUTTONS = 36

#: Where the highlight information starts in a PCI payload.
_HLI_OFFSET = 0x60
_BTN_COLIT_OFFSET = _HLI_OFFSET + 22
_BTNI_OFFSET = _BTN_COLIT_OFFSET + 24
_BTNI_SIZE = 18

#: "No neighbour that way" — the button stays put.
NO_BUTTON = 0


@dataclass(frozen=True)
class Button:
    """One button on a DVD menu, as the disc describes it."""

    number: int
    x_start: int
    y_start: int
    x_end: int
    y_end: int
    up: int
    down: int
    left: int
    right: int
    #: True when moving onto this button runs it, without a second press.
    auto_action: bool
    #: Which of the four highlight colour sets this button uses.
    colour_set: int
    #: The eight raw bytes of the DVD command this button runs.
    command: bytes

    @property
    def width(self) -> int:
        return max(0, self.x_end - self.x_start)

    @property
    def height(self) -> int:
        return max(0, self.y_end - self.y_start)

    @property
    def is_real(self) -> bool:
        """A button with no area is a slot the disc left empty."""
        return self.width > 0 and self.height > 0

    def contains(self, x: int, y: int) -> bool:
        """Is this point inside the button? Used to click a menu with a mouse."""
        return self.x_start <= x < self.x_end and self.y_start <= y < self.y_end

    def neighbour(self, direction: str) -> int:
        return {
            "up": self.up,
            "down": self.down,
            "left": self.left,
            "right": self.right,
        }.get(direction, NO_BUTTON)


@dataclass(frozen=True)
class ColourSet:
    """How one group of buttons is coloured while it is lit.

    A DVD highlight is not a fifth thing drawn over the menu. It is the same
    subpicture pixels pointed at four *different* entries of the program
    chain's palette, at four different opacities. Change the four indices and
    the words on a button light up. That indirection is the whole trick.

    Each set has two states: ``selected`` for the button under the cursor and
    ``action`` for the instant it is pressed.
    """

    #: Palette indices for background, pattern, emphasis 1, emphasis 2.
    selected_palette: tuple[int, int, int, int] = (0, 0, 0, 0)
    #: 0-15 per slot. 0 is invisible, 15 is solid.
    selected_alpha: tuple[int, int, int, int] = (0, 0, 0, 0)
    action_palette: tuple[int, int, int, int] = (0, 0, 0, 0)
    action_alpha: tuple[int, int, int, int] = (0, 0, 0, 0)

    @property
    def is_set(self) -> bool:
        """A disc that left this group empty gives an all-zero entry."""
        return any(self.selected_alpha)


def _colour_set(selection: int, action: int) -> ColourSet:
    """One ``btn_coli`` entry: two 32-bit words, eight nibbles each way.

    The top sixteen bits are palette indices and the bottom sixteen are
    opacities, both ordered emphasis 2, emphasis 1, pattern, background —
    which is the reverse of the slot order everything downstream uses, so
    they are turned round here rather than at every call site.
    """

    def split(word: int) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
        palette = (
            (word >> 16) & 0x0F,          # background
            (word >> 20) & 0x0F,          # pattern
            (word >> 24) & 0x0F,          # emphasis 1
            (word >> 28) & 0x0F,          # emphasis 2
        )
        alpha = (word & 0x0F, (word >> 4) & 0x0F, (word >> 8) & 0x0F, (word >> 12) & 0x0F)
        return palette, alpha

    selected_palette, selected_alpha = split(selection)
    action_palette, action_alpha = split(action)
    return ColourSet(
        selected_palette=selected_palette,
        selected_alpha=selected_alpha,
        action_palette=action_palette,
        action_alpha=action_alpha,
    )


@dataclass(frozen=True)
class Highlight:
    """The menu that is up right now, and for how long."""

    #: 90 kHz. The window this highlight is valid for.
    start_pts: int
    end_pts: int
    #: 1-based. Zero means nothing is selected to begin with.
    selected_button: int
    #: 1-based. A button that acts as if activated when the menu appears.
    activated_button: int
    buttons: tuple[Button, ...]
    #: Three of them, one per button group. A button says which it uses.
    colour_sets: tuple[ColourSet, ...] = ()

    @property
    def has_buttons(self) -> bool:
        return any(button.is_real for button in self.buttons)

    def button(self, number: int) -> Button | None:
        for entry in self.buttons:
            if entry.number == number:
                return entry
        return None

    def at(self, x: int, y: int) -> Button | None:
        for entry in self.buttons:
            if entry.is_real and entry.contains(x, y):
                return entry
        return None

    def colours_for(self, button: Button | None) -> ColourSet | None:
        """The colour set this button lights up in, if the disc gave one."""
        if button is None or not self.colour_sets:
            return None
        index = min(button.colour_set, len(self.colour_sets) - 1)
        chosen = self.colour_sets[index]
        return chosen if chosen.is_set else None


@dataclass(frozen=True)
class NavPack:
    """One VOBU's navigation packet."""

    #: Sector of this NAV pack, as the disc numbers it.
    sector: int
    #: Byte offset of this NAV pack in the file we read it from.
    offset: int
    #: 90 kHz presentation window of the VOBU this heads.
    start_pts: int
    end_pts: int
    #: How many sectors this VOBU runs for, from the NAV pack.
    vobu_sectors: int
    vob_id: int
    cell_id: int
    highlight: Highlight | None = None

    @property
    def has_menu(self) -> bool:
        return self.highlight is not None and self.highlight.has_buttons


def _parse_buttons(payload: bytes, count: int) -> tuple[Button, ...]:
    buttons: list[Button] = []
    for index in range(min(count, MAX_BUTTONS)):
        base = _BTNI_OFFSET + index * _BTNI_SIZE
        if base + _BTNI_SIZE > len(payload):
            break
        reader = BitReader(payload, base)
        colour_set = reader.bits(2)
        x_start = reader.bits(10)
        reader.bits(2)
        x_end = reader.bits(10)
        auto_action = reader.bits(2)
        y_start = reader.bits(10)
        reader.bits(2)
        y_end = reader.bits(10)
        reader.bits(2)
        up = reader.bits(6)
        reader.bits(2)
        down = reader.bits(6)
        reader.bits(2)
        left = reader.bits(6)
        reader.bits(2)
        right = reader.bits(6)
        command = reader.read(8)
        buttons.append(
            Button(
                number=index + 1,
                x_start=x_start,
                y_start=y_start,
                x_end=x_end,
                y_end=y_end,
                up=up,
                down=down,
                left=left,
                right=right,
                auto_action=bool(auto_action),
                colour_set=colour_set,
                command=command,
            )
        )
    return tuple(buttons)


def parse_pci(payload: bytes) -> tuple[int, int, Highlight | None]:
    """Presentation control information: the VOBU's times and its menu."""
    reader = BitReader(payload)
    reader.u32()  # nv_pck_lbn
    reader.u16()  # vobu_cat
    reader.u16()  # reserved
    reader.u32()  # vobu_uop_mask
    start_pts = reader.u32()
    end_pts = reader.u32()

    if len(payload) < _BTNI_OFFSET:
        return start_pts, end_pts, None

    reader.seek(_HLI_OFFSET)
    hli_ss = reader.u16()
    highlight_start = reader.u32()
    highlight_end = reader.u32()
    reader.u32()  # btn_se_e_ptm
    reader.u16()  # button groups and their display types
    reader.u8()  # btn_ofn: where this group's buttons start
    button_count = reader.u8()
    reader.u8()  # nsl_btn_ns
    reader.u8()  # reserved
    selected = reader.u8()
    activated = reader.u8()

    # hli_ss 0 means this VOBU carries no highlight at all.
    if (hli_ss & 0x03) == 0 or button_count == 0:
        return start_pts, end_pts, None

    return (
        start_pts,
        end_pts,
        Highlight(
            start_pts=highlight_start,
            end_pts=highlight_end,
            selected_button=selected,
            activated_button=activated,
            buttons=_parse_buttons(payload, button_count),
            colour_sets=_parse_colour_sets(payload),
        ),
    )


def _parse_colour_sets(payload: bytes) -> tuple[ColourSet, ...]:
    """``btn_coli``: three groups, two words each, right after the HLI header."""
    end = _BTN_COLIT_OFFSET + 24
    if len(payload) < end:
        return ()
    reader = BitReader(payload)
    reader.seek(_BTN_COLIT_OFFSET)
    return tuple(_colour_set(reader.u32(), reader.u32()) for _ in range(3))


def parse_dsi(payload: bytes) -> tuple[int, int, int, int]:
    """Data search information: (sector, vobu length, vob id, cell id)."""
    reader = BitReader(payload)
    reader.u32()  # nv_pck_scr
    sector = reader.u32()
    vobu_end = reader.u32()
    reader.u32()  # vobu_1stref_ea
    reader.u32()  # vobu_2ndref_ea
    reader.u32()  # vobu_3rdref_ea
    vob_id = reader.u16()
    reader.u8()  # reserved
    cell_id = reader.u8()
    return sector, vobu_end, vob_id, cell_id


def parse_nav_sector(sector: bytes, offset: int = 0) -> NavPack | None:
    """Read one 2048-byte sector as a NAV pack, or ``None`` if it is not one."""
    if len(sector) < SECTOR or not sector.startswith(PACK_START):
        return None
    position = 14  # the pack header
    if sector[position : position + 4] == SYSTEM_HEADER_START:
        length = int.from_bytes(sector[position + 4 : position + 6], "big")
        position += 6 + length
    if sector[position : position + 4] != PRIVATE_STREAM_2:
        return None

    try:
        pci_length = int.from_bytes(sector[position + 4 : position + 6], "big")
        if sector[position + 6] != SUBSTREAM_PCI:
            return None
        pci = sector[position + 7 : position + 6 + pci_length]
        start_pts, end_pts, highlight = parse_pci(pci)

        position += 6 + pci_length
        vobu_sectors = vob_id = cell_id = 0
        sector_number = 0
        if (
            sector[position : position + 4] == PRIVATE_STREAM_2
            and sector[position + 6] == SUBSTREAM_DSI
        ):
            dsi_length = int.from_bytes(sector[position + 4 : position + 6], "big")
            dsi = sector[position + 7 : position + 6 + dsi_length]
            sector_number, vobu_sectors, vob_id, cell_id = parse_dsi(dsi)
    except (TruncatedError, IndexError):
        return None

    return NavPack(
        sector=sector_number,
        offset=offset,
        start_pts=start_pts,
        end_pts=end_pts,
        vobu_sectors=vobu_sectors,
        vob_id=vob_id,
        cell_id=cell_id,
        highlight=highlight,
    )


#: How far into a VOB to look before giving up. A menu VOB is small; a
#: feature's is gigabytes, and on an optical drive at a few megabytes a second
#: an unbounded scan is a hang rather than a search.
MAX_SCAN_BYTES = 64 * 1024 * 1024


def read_nav_packs(
    path: Path, *, limit: int | None = None, max_bytes: int = MAX_SCAN_BYTES
) -> list[NavPack]:
    """Every NAV pack in a VOB, in file order.

    A VOB's NAV packs sit at VOBU boundaries, and each one says how long its
    VOBU is, so this skips from one to the next rather than reading every
    sector. The byte bound is for the case where a disc has no valid NAV packs
    at all and there is nothing to skip by.
    """
    packs: list[NavPack] = []
    try:
        with path.open("rb") as handle:
            offset = 0
            while offset < max_bytes:
                sector = handle.read(SECTOR)
                if len(sector) < SECTOR:
                    break
                pack = parse_nav_sector(sector, offset)
                if pack is not None:
                    packs.append(pack)
                    if limit is not None and len(packs) >= limit:
                        break
                    # The DSI says how long this VOBU is, so the next NAV pack
                    # is exactly that far on. Skipping to it turns reading a
                    # feature-length VOB from minutes into moments.
                    if pack.vobu_sectors > 1:
                        skip = (pack.vobu_sectors - 1) * SECTOR
                        handle.seek(skip, 1)
                        offset += skip
                offset += SECTOR
    except OSError:
        return packs
    return packs


def first_menu(path: Path) -> Highlight | None:
    """The first menu found in a VOB, which for a menu VOB is *the* menu."""
    for pack in read_nav_packs(path, limit=64):
        if pack.has_menu:
            return pack.highlight
    return None
