"""Encode a DVD subpicture, so the decoder has something to read.

The Player only ever needs to *read* these. Writing one exists so the reader
can be tested against a known picture rather than against itself — the run
lengths are variable-width nibbles and the two fields are interlaced, which
is exactly the sort of thing a decoder can get consistently wrong.
"""

from __future__ import annotations

from dataclasses import dataclass


class _NibbleWriter:
    def __init__(self) -> None:
        self._nibbles: list[int] = []

    @property
    def count(self) -> int:
        return len(self._nibbles)

    def write(self, value: int) -> None:
        self._nibbles.append(value & 0x0F)

    def align(self) -> None:
        if len(self._nibbles) % 2:
            self._nibbles.append(0)

    def to_bytes(self) -> bytes:
        self.align()
        out = bytearray()
        for index in range(0, len(self._nibbles), 2):
            out.append((self._nibbles[index] << 4) | self._nibbles[index + 1])
        return bytes(out)


def _write_run(writer: _NibbleWriter, run: int, colour: int, *, to_end: bool) -> None:
    """One run, in the shortest of the four widths that will hold it.

    A run that reaches the end of a line can be written as all zeros, which is
    how a real disc ends a line of background — so that case is exercised too.
    """
    if to_end:
        writer.write(0)
        writer.write(0)
        writer.write(0)
        writer.write(colour)
        return
    # The width is chosen so the decoder stops on the right nibble: it keeps
    # reading while the accumulated value is below 0x4, 0x10 and 0x40 in turn.
    # Writing a run one nibble wider than it needs makes the decoder read past
    # its terminator and treat the run as "the rest of the line".
    value = (run << 2) | colour
    if run < 0x4:
        writer.write(value)
    elif run < 0x10:
        writer.write(value >> 4)
        writer.write(value & 0x0F)
    elif run < 0x40:
        writer.write(0)
        writer.write(value >> 4)
        writer.write(value & 0x0F)
    else:
        writer.write(0)
        writer.write(value >> 8)
        writer.write((value >> 4) & 0x0F)
        writer.write(value & 0x0F)


def encode_field(rows: list[list[int]], width: int) -> bytes:
    writer = _NibbleWriter()
    for row in rows:
        index = 0
        while index < width:
            colour = row[index] if index < len(row) else 0
            run = 1
            while (
                index + run < width
                and (row[index + run] if index + run < len(row) else 0) == colour
            ):
                run += 1
            reaches_end = index + run >= width
            remaining = run
            while remaining:
                take = min(remaining, 0xFF)
                _write_run(
                    writer,
                    take,
                    colour,
                    to_end=reaches_end and take == remaining and colour == 0,
                )
                remaining -= take
            index += run
        writer.align()
    return writer.to_bytes()


@dataclass(frozen=True)
class SpuSpec:
    """A picture to encode: one value 0-3 per pixel."""

    x_start: int
    y_start: int
    rows: list[list[int]]
    palette: tuple[int, int, int, int] = (0, 1, 2, 3)
    alpha: tuple[int, int, int, int] = (0, 0xF, 0xF, 0xF)

    @property
    def width(self) -> int:
        return max((len(row) for row in self.rows), default=0)

    @property
    def height(self) -> int:
        return len(self.rows)


def build_subpicture(spec: SpuSpec) -> bytes:
    """One complete subpicture unit, the way a disc carries it."""
    width, height = spec.width, spec.height
    top = encode_field([spec.rows[line] for line in range(0, height, 2)], width)
    bottom = encode_field([spec.rows[line] for line in range(1, height, 2)], width)

    header_size = 4
    top_offset = header_size
    bottom_offset = top_offset + len(top)
    control_start = bottom_offset + len(bottom)

    x_end = spec.x_start + width - 1
    y_end = spec.y_start + height - 1
    control = bytearray()
    control += (0).to_bytes(2, "big")  # no delay
    control_self = control_start
    control += (control_self).to_bytes(2, "big")  # a block that ends the chain
    control += bytes((0x03, (spec.palette[3] << 4) | spec.palette[2],
                      (spec.palette[1] << 4) | spec.palette[0]))
    control += bytes((0x04, (spec.alpha[3] << 4) | spec.alpha[2],
                      (spec.alpha[1] << 4) | spec.alpha[0]))
    control += bytes(
        (
            0x05,
            spec.x_start >> 4,
            ((spec.x_start & 0x0F) << 4) | (x_end >> 8),
            x_end & 0xFF,
            spec.y_start >> 4,
            ((spec.y_start & 0x0F) << 4) | (y_end >> 8),
            y_end & 0xFF,
        )
    )
    control += bytes((0x06,)) + top_offset.to_bytes(2, "big") + bottom_offset.to_bytes(2, "big")
    control += bytes((0x01,))  # start displaying
    control += bytes((0xFF,))

    total = control_start + len(control)
    out = bytearray()
    out += total.to_bytes(2, "big")
    out += control_start.to_bytes(2, "big")
    out += top
    out += bottom
    out += control
    return bytes(out)


def box(width: int, height: int, *, border: int = 1, fill: int = 2) -> list[list[int]]:
    """A filled rectangle with a border — what a menu button looks like."""
    rows: list[list[int]] = []
    for y in range(height):
        row: list[int] = []
        for x in range(width):
            edge = x < border or y < border or x >= width - border or y >= height - border
            row.append(1 if edge else fill)
        rows.append(row)
    return rows


# --------------------------------------------------------------------------
# Carrying one into a program stream
#
# A subpicture does not sit in a VOB on its own. It rides in private stream 1,
# split across as many PES packets as it takes, each one prefixed with the
# sub-stream byte that says which of the disc's 32 subpicture streams it
# belongs to. This writes that, so the Player's reader can be tested against
# the shape a disc actually has rather than against a bare blob.
# --------------------------------------------------------------------------

#: Private stream 1. Subpictures share it with AC-3, DTS and LPCM.
PRIVATE_STREAM_1 = 0xBD

#: Sub-stream ids 0x20-0x3F are subpictures; the low five bits pick which.
SPU_SUBSTREAM_BASE = 0x20

#: How much payload goes in one packet. Real discs use whatever fits the
#: sector; a smaller number here means more packets, which is the case worth
#: testing — a reader that only works when a picture fits in one packet works
#: on almost no discs.
PES_PAYLOAD = 512


def spu_pes_packets(
    payload: bytes, *, stream: int = 0, pts: int = 0, chunk: int = PES_PAYLOAD
) -> bytes:
    """One subpicture, split across private-stream-1 PES packets."""
    out = bytearray()
    first = True
    for start in range(0, len(payload), chunk):
        piece = payload[start : start + chunk]
        # An MPEG-2 PES header: two flag bytes, a header length, and a PTS on
        # the first packet only — which is exactly what a disc writes.
        if first:
            optional = bytes((0x81, 0xC0, 0x05)) + _pts_field(pts)
        else:
            optional = bytes((0x81, 0x00, 0x00))
        prefix = bytes((SPU_SUBSTREAM_BASE + stream,))
        body = optional + prefix + piece
        out += b"\x00\x00\x01" + bytes((PRIVATE_STREAM_1,))
        out += len(body).to_bytes(2, "big")
        out += body
        first = False
    return bytes(out)


def _pts_field(pts: int) -> bytes:
    """A 33-bit presentation timestamp, in the five bytes MPEG spreads it over."""
    value = pts & 0x1FFFFFFFF
    return bytes(
        (
            0x21 | ((value >> 29) & 0x0E),
            (value >> 22) & 0xFF,
            0x01 | ((value >> 14) & 0xFE),
            (value >> 7) & 0xFF,
            0x01 | ((value << 1) & 0xFE),
        )
    )


def pack_header() -> bytes:
    """The 14-byte pack header every DVD sector starts with."""
    return (
        b"\x00\x00\x01\xba"
        + bytes((0x44, 0x00, 0x04, 0x00, 0x04, 0x01))
        + bytes((0x01, 0x89, 0xC3))
        + bytes((0xF8,))
    )


def sector_with(payload: bytes, size: int = 2048) -> bytes:
    """One DVD sector: a pack header, the payload, then padding to fill it.

    Padding is a real PES packet of stream 0xBE, which is what a muxer writes
    and what a reader has to skip past without being confused by it.
    """
    body = pack_header() + payload
    if len(body) > size:
        raise ValueError(f"{len(body)} bytes will not fit in a {size}-byte sector")
    spare = size - len(body)
    if spare == 0:
        return body
    if spare < 6:
        raise ValueError("no room for the padding packet a real sector would carry")
    return body + b"\x00\x00\x01\xbe" + (spare - 6).to_bytes(2, "big") + b"\xff" * (spare - 6)
