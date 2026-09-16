"""Decode a DVD subpicture — the graphics a menu is drawn with.

A DVD menu is a still frame of video with a *subpicture* on top: a two-bit
indexed bitmap, run-length encoded, with its own four-colour palette and four
alpha values. The words on the buttons are in there. So are the boxes.

The highlight works by swapping the palette inside a button's rectangle
rather than by drawing anything new. Same pixels, different colours — which
is why a DVD menu highlight is always a flat colour change and never a glow.
That means a player draws the menu once and, when the selection moves,
re-colours two rectangles.

Subtitles use exactly the same format, so this is also what will draw a DVD's
subtitles when that comes.
"""

from __future__ import annotations

from dataclasses import dataclass

#: A subpicture's pixel values index four entries, not sixteen.
COLOURS = 4

#: Display control commands.
CMD_FORCE_DISPLAY = 0x00
CMD_START_DISPLAY = 0x01
CMD_STOP_DISPLAY = 0x02
CMD_SET_COLOUR = 0x03
CMD_SET_ALPHA = 0x04
CMD_SET_AREA = 0x05
CMD_SET_OFFSETS = 0x06
CMD_END = 0xFF


#: The largest picture a DVD has. PAL is 720x576, NTSC 720x480; the area
#: field can say 4095x4095, and a disc that does is not a disc.
MAX_WIDTH = 720
MAX_HEIGHT = 576


class SpuError(ValueError):
    """This is not a subpicture we can read."""


@dataclass(frozen=True)
class Area:
    """Where on the frame the subpicture sits, in the video's own pixels."""

    x_start: int
    y_start: int
    x_end: int
    y_end: int

    @property
    def width(self) -> int:
        return max(0, self.x_end - self.x_start + 1)

    @property
    def height(self) -> int:
        return max(0, self.y_end - self.y_start + 1)

    @property
    def is_empty(self) -> bool:
        return self.width <= 0 or self.height <= 0


@dataclass(frozen=True)
class Subpicture:
    """One decoded subpicture: its area, its pixels, and how to colour them."""

    area: Area
    #: One row per line, each value 0-3, indexing the palette.
    rows: tuple[tuple[int, ...], ...]
    #: Indices into the program chain's sixteen-colour palette.
    palette: tuple[int, int, int, int]
    #: 0 is invisible, 15 is opaque.
    alpha: tuple[int, int, int, int]
    #: 90 kHz, relative to the subpicture's own presentation time.
    start_delay: int = 0
    stop_delay: int = 0

    @property
    def width(self) -> int:
        return self.area.width

    @property
    def height(self) -> int:
        return self.area.height

    def pixel(self, x: int, y: int) -> int:
        if 0 <= y < len(self.rows) and 0 <= x < len(self.rows[y]):
            return self.rows[y][x]
        return 0

    @property
    def is_blank(self) -> bool:
        """True when every pixel is transparent, so there is nothing to draw."""
        visible = {index for index in range(COLOURS) if self.alpha[index]}
        if not visible:
            return True
        return not any(value in visible for row in self.rows for value in row)


class _Nibbles:
    """A nibble reader, because the run lengths are 4, 8, 12 or 16 bits."""

    __slots__ = ("_data", "_position")

    def __init__(self, data: bytes, start_nibble: int) -> None:
        self._data = data
        self._position = start_nibble

    @property
    def position(self) -> int:
        return self._position

    def align(self) -> None:
        if self._position % 2:
            self._position += 1

    def read(self) -> int:
        index = self._position // 2
        if index >= len(self._data):
            raise SpuError("the subpicture's pixel data ends early")
        byte = self._data[index]
        value = (byte >> 4) if self._position % 2 == 0 else (byte & 0x0F)
        self._position += 1
        return value


def _decode_field(data: bytes, start: int, width: int, lines: int) -> list[list[int]]:
    """One field of the interlaced bitmap: every other line of the picture."""
    nibbles = _Nibbles(data, start * 2)
    rows: list[list[int]] = []
    for _ in range(lines):
        row: list[int] = []
        while len(row) < width:
            value = nibbles.read()
            if value < 0x4:
                value = (value << 4) | nibbles.read()
                if value < 0x10:
                    value = (value << 4) | nibbles.read()
                    if value < 0x40:
                        value = (value << 4) | nibbles.read()
                        if value < 0x100:
                            # Nothing but zeros: this run is the rest of the
                            # line, which is how a line of background ends.
                            value |= (width - len(row)) << 2
            run = value >> 2
            colour = value & 0x03
            row.extend([colour] * min(run, width - len(row)))
        rows.append(row[:width])
        nibbles.align()
    return rows


def _interlace(top: list[list[int]], bottom: list[list[int]], height: int, width: int):
    """Weave the two fields back into a picture, top field first."""
    rows: list[tuple[int, ...]] = []
    blank = tuple([0] * width)
    for line in range(height):
        field = top if line % 2 == 0 else bottom
        index = line // 2
        rows.append(tuple(field[index]) if index < len(field) else blank)
    return tuple(rows)


def decode(data: bytes) -> Subpicture:
    """Decode one complete subpicture unit."""
    if len(data) < 4:
        raise SpuError("a subpicture is at least four bytes")
    total = int.from_bytes(data[0:2], "big")
    control_start = int.from_bytes(data[2:4], "big")
    if control_start < 4 or control_start > len(data):
        raise SpuError("the subpicture's control block is not where it says")
    if total and total < len(data):
        data = data[:total]

    palette = (0, 1, 2, 3)
    alpha = (0, 0xF, 0xF, 0xF)
    area = Area(0, 0, -1, -1)
    top_offset = bottom_offset = 0
    start_delay = stop_delay = 0

    position = control_start
    seen: set[int] = set()
    while position + 4 <= len(data):
        if position in seen:  # a control block that points at itself
            break
        seen.add(position)
        delay = int.from_bytes(data[position : position + 2], "big") * 1024
        next_block = int.from_bytes(data[position + 2 : position + 4], "big")
        cursor = position + 4

        while cursor < len(data):
            command = data[cursor]
            cursor += 1
            if command == CMD_END:
                break
            if command in (CMD_FORCE_DISPLAY, CMD_START_DISPLAY):
                start_delay = delay
            elif command == CMD_STOP_DISPLAY:
                stop_delay = delay
            elif command == CMD_SET_COLOUR and cursor + 2 <= len(data):
                packed = data[cursor : cursor + 2]
                palette = (
                    packed[1] & 0x0F,
                    packed[1] >> 4,
                    packed[0] & 0x0F,
                    packed[0] >> 4,
                )
                cursor += 2
            elif command == CMD_SET_ALPHA and cursor + 2 <= len(data):
                packed = data[cursor : cursor + 2]
                alpha = (
                    packed[1] & 0x0F,
                    packed[1] >> 4,
                    packed[0] & 0x0F,
                    packed[0] >> 4,
                )
                cursor += 2
            elif command == CMD_SET_AREA and cursor + 6 <= len(data):
                block = data[cursor : cursor + 6]
                area = Area(
                    x_start=(block[0] << 4) | (block[1] >> 4),
                    x_end=((block[1] & 0x0F) << 8) | block[2],
                    y_start=(block[3] << 4) | (block[4] >> 4),
                    y_end=((block[4] & 0x0F) << 8) | block[5],
                )
                cursor += 6
            elif command == CMD_SET_OFFSETS and cursor + 4 <= len(data):
                top_offset = int.from_bytes(data[cursor : cursor + 2], "big")
                bottom_offset = int.from_bytes(data[cursor + 2 : cursor + 4], "big")
                cursor += 4
            else:
                # An unrecognised command has no length we can trust, so the
                # only safe thing is to stop reading this block.
                break

        if next_block == position or next_block < control_start:
            break
        position = next_block

    if area.is_empty:
        raise SpuError("the subpicture never says where on screen it goes")

    # SET_AREA is twelve bits per edge, so a disc can declare 4095x4095 and
    # a six-kilobyte unit becomes a seventeen-megapixel bitmap. A DVD's
    # picture is 720x576 at the largest there has ever been.
    if area.width > MAX_WIDTH or area.height > MAX_HEIGHT:
        raise SpuError(
            f"the subpicture claims to be {area.width}x{area.height}, "
            f"larger than a DVD frame"
        )

    width, height = area.width, area.height
    top = _decode_field(data, top_offset, width, (height + 1) // 2)
    bottom = _decode_field(data, bottom_offset, width, height // 2)
    return Subpicture(
        area=area,
        rows=_interlace(top, bottom, height, width),
        palette=palette,
        alpha=alpha,
        start_delay=start_delay,
        stop_delay=stop_delay,
    )


def yuv_to_rgb(y: int, cb: int, cr: int) -> tuple[int, int, int]:
    """A DVD palette entry is YCbCr. BT.601, which is what SD video is."""
    y_scaled = 1.164 * (y - 16)
    red = y_scaled + 1.596 * (cr - 128)
    green = y_scaled - 0.813 * (cr - 128) - 0.391 * (cb - 128)
    blue = y_scaled + 2.018 * (cb - 128)
    return (
        max(0, min(255, round(red))),
        max(0, min(255, round(green))),
        max(0, min(255, round(blue))),
    )


def resolve_palette(
    chain_palette: list[int],
    indices: tuple[int, int, int, int],
    alpha: tuple[int, int, int, int],
) -> tuple[tuple[int, int, int, int], ...]:
    """Turn the four indices into four RGBA colours ready to paint with.

    ``chain_palette`` is the sixteen YCbCr entries the program chain carries;
    ``indices`` picks four of them; ``alpha`` says how solid each one is. That
    indirection is the whole trick behind a DVD highlight: change the four
    indices and the same pixels become a lit button.
    """
    out: list[tuple[int, int, int, int]] = []
    for slot in range(COLOURS):
        entry = chain_palette[indices[slot]] if indices[slot] < len(chain_palette) else 0
        red, green, blue = yuv_to_rgb(
            (entry >> 16) & 0xFF, (entry >> 8) & 0xFF, entry & 0xFF
        )
        out.append((red, green, blue, min(255, alpha[slot] * 17)))
    return tuple(out)
