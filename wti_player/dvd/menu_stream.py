"""Pull a DVD menu's picture out of its VOB.

The last reader. A menu VOB is an MPEG program stream, and the menu's
graphics are not video — they are a **subpicture**: a run-length-encoded
two-bit bitmap carried in private stream 1, alongside the still or short loop
the menu sits on. That bitmap is the words on the buttons. Without it a menu
is a background with invisible hot spots.

Getting at it means walking the program stream by hand:

* pack headers (``00 00 01 BA``) say where a pack starts and are skipped;
* PES packets (``00 00 01 xx``) carry a length, so the walk is a hop;
* stream ``0xBD`` is private stream 1, which carries subpictures *and* AC-3
  *and* DTS *and* LPCM, told apart by a sub-stream byte at the front of the
  payload: ``0x20`` to ``0x3F`` is a subpicture, and the low five bits are which
  one of the thirty-two;
* one subpicture is assembled from however many PES packets it takes, and
  says its own total length in its first two bytes.

Everything here is bounded. A menu VOB is a few megabytes; a *title* VOB is a
gigabyte, and a caller who points this at the wrong file should wait a moment
and get nothing, not wait a minute.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..formats import dvd_spu

#: A DVD sector, and the unit a program stream is written in.
SECTOR = 2048

#: How much of a VOB to walk. A menu's first subpicture is in the first few
#: hundred kilobytes of any disc ever pressed; this is generous by a lot.
MAX_SCAN_BYTES = 32 * 1024 * 1024

#: No subpicture is bigger than this. The format's own length field is 16
#: bits, so nothing legitimate can be.
MAX_SPU_BYTES = 0xFFFF

#: Private stream 1: subpictures, and also every non-MPEG audio format.
PRIVATE_STREAM_1 = 0xBD

#: The sub-stream ids that mean "this is a subpicture".
SPU_FIRST = 0x20
SPU_LAST = 0x3F


@dataclass(frozen=True)
class MenuPicture:
    """One menu's graphics, decoded."""

    subpicture: dvd_spu.Subpicture
    #: Which of the disc's 32 subpicture streams it came from.
    stream: int
    #: Where in the file it started, for an inspector to report.
    offset: int


def read_menu_picture(
    path: Path,
    *,
    stream: int | None = None,
    max_bytes: int = MAX_SCAN_BYTES,
) -> MenuPicture | None:
    """The first complete subpicture in ``path``, decoded. ``None`` if none.

    ``stream`` picks one of the disc's 32 subpicture streams; left off, the
    first one that yields a picture with anything visible in it wins — which
    on a menu VOB is the menu, because a menu VOB has one subpicture and it
    is the menu.

    Never raises for a bad disc. A VOB that is truncated, scrambled, or not a
    VOB at all reads as "no menu picture", because from where a person is
    sitting those are the same thing.
    """
    try:
        for candidate in _subpicture_packets(path, stream, max_bytes):
            try:
                decoded = dvd_spu.decode(candidate.data)
            except (dvd_spu.SpuError, ValueError, IndexError):
                continue
            if decoded.is_blank:
                # A blank subpicture is a real thing — it is what a menu
                # shows between highlights — but it is not the menu.
                continue
            return MenuPicture(subpicture=decoded, stream=candidate.stream,
                               offset=candidate.offset)
    except OSError:
        return None
    return None


@dataclass
class _Packet:
    stream: int
    offset: int
    data: bytes


def _subpicture_packets(path: Path, want: int | None, max_bytes: int):
    """Assemble complete subpicture units out of a program stream.

    Yielded in the order they finish. A unit that never finishes — the file
    ran out, or the length was a lie — is dropped rather than guessed at.
    """
    pending: dict[int, _Packet] = {}
    with path.open("rb") as handle:
        data = handle.read(min(max_bytes, SECTOR * 512))
        base = 0
        while data:
            # How far _walk actually got. A PES packet that straddles the
            # boundary between two reads is abandoned, and advancing by the
            # whole chunk skipped it and started the next chunk in the middle
            # of it. The picture came back four pixels wide at one offset and
            # not at all eight bytes before the next — a menu that draws, takes
            # presses, and has no words on it.
            stopped = [0]
            for packet in _walk(data, base, stopped):
                if packet.stream not in range(SPU_FIRST, SPU_LAST + 1):
                    continue
                if want is not None and (packet.stream & 0x1F) != want:
                    continue
                unit = pending.get(packet.stream)
                if unit is None:
                    if len(packet.data) < 2:
                        continue
                    pending[packet.stream] = _Packet(
                        packet.stream, packet.offset, packet.data
                    )
                    unit = pending[packet.stream]
                else:
                    unit.data += packet.data
                declared = int.from_bytes(unit.data[:2], "big")
                if declared == 0 or declared > MAX_SPU_BYTES:
                    del pending[packet.stream]
                    continue
                if len(unit.data) >= declared:
                    del pending[packet.stream]
                    yield _Packet(unit.stream, unit.offset, unit.data[:declared])

            consumed = stopped[0] if stopped[0] > 0 else len(data)
            if consumed <= 0 or consumed > len(data):
                consumed = len(data)
            base += consumed
            if base >= max_bytes:
                return
            handle.seek(base)
            data = handle.read(min(max_bytes - base, SECTOR * 512))


def _walk(data: bytes, base: int, stopped: list[int] | None = None):
    """Every PES packet in ``data``, as (sub-stream, offset, payload).

    ``stopped`` is filled in with how far the walk got, so the caller can
    carry on from there rather than from the end of the buffer. A packet
    that runs past the end of this chunk is left for the next one.
    """
    position = 0
    end = len(data)

    def stop_at(where: int) -> None:
        if stopped is not None:
            stopped[0] = where
    while position + 6 <= end:
        if data[position] != 0 or data[position + 1] != 0 or data[position + 2] != 1:
            position += 1
            continue
        marker = data[position + 3]

        if marker == 0xBA:  # pack header
            position += _pack_header_length(data, position)
            continue
        if marker == 0xB9:  # end of stream
            stop_at(end)
            return
        if marker < 0xBC:  # a start code that is not a PES packet
            position += 4
            continue

        length = int.from_bytes(data[position + 4 : position + 6], "big")
        if length == 0:
            position += 6
            continue
        payload_end = position + 6 + length
        if payload_end > end:
            # This packet is split across the read boundary. Leave it whole
            # for the next chunk rather than dropping it.
            stop_at(position)
            return

        if marker == PRIVATE_STREAM_1:
            header = _pes_header_length(data, position)
            start = position + 6 + header
            if start < payload_end:
                sub = data[start]
                if SPU_FIRST <= sub <= SPU_LAST:
                    # Subpictures carry only the sub-stream byte, then the
                    # SPU bitstream. The three-byte "units in this packet"
                    # prefix is the AC-3/DTS private-stream-1 header, not
                    # ours — skipping it ate the first three bytes of every
                    # picture, which on a real disc is the size and the
                    # start of the display-control sequence.
                    yield _Packet(sub, base + position, data[start + 1 : payload_end])
        position = payload_end
        stop_at(position)


def _pack_header_length(data: bytes, position: int) -> int:
    """A pack header is 14 bytes plus however much stuffing it declares."""
    if position + 14 > len(data):
        return 4
    stuffing = data[position + 13] & 0x07
    return 14 + stuffing


def _pes_header_length(data: bytes, position: int) -> int:
    """The bytes between the PES length field and the payload.

    MPEG-2 says so in a field; MPEG-1 makes you count stuffing bytes and then
    read a variable-length timestamp. Both are on real discs.
    """
    if position + 9 > len(data):
        return 3
    if data[position + 6] & 0xC0 == 0x80:  # MPEG-2
        return 3 + data[position + 8]

    # MPEG-1: up to 16 stuffing bytes, then optionally a buffer size, then
    # a PTS and maybe a DTS.
    index = position + 6
    stuffing = 0
    while index < len(data) and data[index] == 0xFF and stuffing < 16:
        index += 1
        stuffing += 1
    if index + 1 < len(data) and data[index] & 0xC0 == 0x40:
        index += 2
    if index < len(data):
        flag = data[index] & 0xF0
        if flag == 0x20:
            index += 5
        elif flag == 0x30:
            index += 10
        else:
            index += 1
    return index - (position + 6)


__all__ = [
    "MAX_SCAN_BYTES",
    "PRIVATE_STREAM_1",
    "SPU_FIRST",
    "SPU_LAST",
    "MenuPicture",
    "read_menu_picture",
]
