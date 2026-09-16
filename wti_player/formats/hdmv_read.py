"""Read a Blu-ray menu back out of the disc it was written onto.

The Player does not need this to play a disc: libbluray runs HDMV menus, and
that is what the day-one spike settled. What nobody had was a way to check
that a menu we authored is on the disc and says what we meant, without
watching it on a television.

That gap is not academic. ``libvlc_video_take_snapshot`` returns the video
plane and nothing composited above it, so a menu photographed that way is the
background with no buttons on it — which looks exactly like a menu that
failed. This reads the interactive-graphics stream out of the clip and says
how many buttons are in it, where they are and what each one runs.

It is the other half of ``tests/fixtures/authoring/hdmv.py``: what that
writes, this reads.
"""

from __future__ import annotations

from dataclasses import dataclass

#: One transport packet.
TS_PACKET = 188
#: The PID every Blu-ray carries interactive graphics on.
IG_PID = 0x1400

#: Segment types in an interactive-graphics stream.
SEGMENT_PDS = 0x14
SEGMENT_ODS = 0x15
SEGMENT_ICS = 0x18
SEGMENT_END = 0x80

#: A menu with more buttons than this is not a menu anybody navigates.
#: Counted across the page, not per group: the per-group count is a u8
#: and cannot exceed 255, so a check against 255 there never fires.
MAX_BUTTONS = 255
#: And a segment longer than its own length field can express is corrupt.
MAX_SEGMENT = 0xFFFF
#: How many PES packets to unwrap before deciding this is not a menu.
#: A menu clip has tens. The cap is what stops a crafted stream from
#: becoming a list of sixty thousand slices.
MAX_SEGMENTS = 4096

#: What a private-stream-1 PES packet starts with, and so where every
#: interactive-graphics segment begins.
PES_START = b"\x00\x00\x01\xbd"


class StreamError(ValueError):
    """The interactive stream is not one we can read."""


@dataclass(frozen=True)
class Button:
    """One button, as the disc carries it."""

    button_id: int
    x: int
    y: int
    normal_object: int
    selected_object: int
    activated_object: int
    upper: int
    lower: int
    left: int
    right: int
    commands: int

    @property
    def has_three_states(self) -> bool:
        """Normal, selected and activated all point somewhere different."""
        return len({self.normal_object, self.selected_object, self.activated_object}) == 3


@dataclass(frozen=True)
class Menu:
    """What an interactive-graphics stream turned out to contain."""

    width: int
    height: int
    buttons: tuple[Button, ...]
    #: How many distinct graphic objects the stream defines (by object id,
    #: not by segment: an object split across segments is one object).
    objects: int
    #: How many palette entries, across every palette segment.
    palette_entries: int
    default_selected: int = 0
    #: The object ids the stream actually defines, and the palette ids.
    object_ids: frozenset[int] = frozenset()
    palette_ids: frozenset[int] = frozenset()
    #: The palette the first page asks for.
    palette_id_ref: int = 0

    @property
    def usable(self) -> bool:
        """Every button's normal picture is an object the stream defines, the
        page's palette is one the stream defines, and there is a button.

        ``normal_object != 0xFFFF`` was the whole check until 28 Aug 2026,
        which passed a menu that named pictures the stream never carried;
        a player would have shown nothing and called it a menu.
        """
        if not self.buttons:
            return False
        if self.palette_id_ref not in self.palette_ids:
            return False
        return all(button.normal_object in self.object_ids for button in self.buttons)


def payload_of(m2ts: bytes, pid: int = IG_PID) -> bytes:
    """Every payload byte carried on ``pid``, in order.

    A BDMV ``.m2ts`` is 192-byte source packets: a four-byte arrival
    timestamp then a 188-byte transport packet. A plain ``.ts`` is 188. Both
    are accepted, because the fixtures write one and a real disc carries the
    other.
    """
    stride = 192 if _looks_like_m2ts(m2ts) else TS_PACKET
    offset = stride - TS_PACKET
    out = bytearray()
    for start in range(offset, len(m2ts) - TS_PACKET + 1, stride):
        packet = m2ts[start : start + TS_PACKET]
        if packet[0] != 0x47:
            continue
        if ((packet[1] & 0x1F) << 8 | packet[2]) != pid:
            continue
        control = packet[3]
        body = 4
        if control & 0x20:  # an adaptation field, whose length is its first byte
            body += 1 + packet[4]
        if control & 0x10 and body < TS_PACKET:
            out += packet[body:]
    return bytes(out)


def _looks_like_m2ts(data: bytes) -> bool:
    return len(data) >= 192 and data[4] == 0x47 and (len(data) % 192 == 0 or data[0] != 0x47)


def segments(payload: bytes) -> list[tuple[int, bytes]]:
    """The PES packets in ``payload``, unwrapped into ``(type, body)``."""
    found: list[tuple[int, bytes]] = []
    position = 0
    end = len(payload)
    while position + 9 <= end:
        # find() rather than a byte-at-a-time walk. The walk was a Python
        # loop over every byte of the payload — 4.4 MB a second, so four
        # minutes for a gigabyte and an hour and a half for a BD50 clip.
        # This is the same search, in C.
        position = payload.find(PES_START, position)
        if position < 0 or position + 9 > end:
            break
        length = int.from_bytes(payload[position + 4 : position + 6], "big")
        if not 0 < length <= MAX_SEGMENT:
            position += 4
            continue
        header = payload[position + 8]
        body_start = position + 9 + header
        body_end = position + 6 + length
        if body_end > end or body_start + 3 > body_end:
            break
        segment_type = payload[body_start]
        size = int.from_bytes(payload[body_start + 1 : body_start + 3], "big")
        # Clamped to what the packet actually holds. A segment header can
        # claim 65535 bytes inside a 16-byte packet, and Python will hand
        # back a slice that size in a list that keeps every one of them.
        body = payload[body_start + 3 : min(body_end, body_start + 3 + size)]
        found.append((segment_type, body))
        position = body_end
        if len(found) >= MAX_SEGMENTS:
            break
    return found


def read(m2ts: bytes, pid: int = IG_PID) -> Menu:
    """The menu inside a clip. Raises :class:`StreamError` if there is none."""
    parts = segments(payload_of(m2ts, pid))
    if not parts:
        raise StreamError("no interactive graphics on this stream")

    # Content, not segments: an ODS body starts with object_id(2), a PDS
    # body with palette_id(1). Counting segments called a two-part object
    # two objects and an empty palette segment a palette.
    object_ids = frozenset(
        int.from_bytes(body[0:2], "big") for kind, body in parts if kind == SEGMENT_ODS and len(body) >= 2
    )
    # A palette with no entries is no palette: 2 header bytes, then 5 per entry.
    palette_ids = frozenset(body[0] for kind, body in parts if kind == SEGMENT_PDS and len(body) >= 7)
    palette_entries = sum(
        max(0, (len(body) - 2) // 5) for kind, body in parts if kind == SEGMENT_PDS
    )
    for kind, body in parts:
        if kind == SEGMENT_ICS:
            width, height, buttons, selected, palette_id_ref = _read_composition(body)
            return Menu(
                width=width,
                height=height,
                buttons=buttons,
                objects=len(object_ids),
                palette_entries=palette_entries,
                default_selected=selected,
                object_ids=object_ids,
                palette_ids=palette_ids,
                palette_id_ref=palette_id_ref,
            )
    raise StreamError("the stream has no interactive composition in it")


def _read_composition(body: bytes) -> tuple[int, int, tuple[Button, ...], int, int]:
    """An ICS: the video size, then the composition, then the pages."""
    if len(body) < 11:
        raise StreamError("the composition segment is too short to be one")
    width = int.from_bytes(body[0:2], "big")
    height = int.from_bytes(body[2:4], "big")

    # video_descriptor is width(2) height(2) frame_rate(1); then the
    # composition_descriptor is number(2) state(1); then a one-byte sequence
    # descriptor; then the interactive composition's own 24-bit length.
    cursor = 2 + 2 + 1 + 2 + 1 + 1 + 3
    if cursor + 5 > len(body):
        raise StreamError("the composition ends before it begins")

    # stream_model(1) user_interface_model(1) reserved(6). The two 33-bit
    # timeouts after it are there only when the menu is multiplexed into the
    # clip. A pop-up menu comes out of a separate stream and does not carry
    # them, so skipping them unconditionally reads a pop-up menu's pages ten
    # bytes early — which is not a parse failure, it is a menu with the wrong
    # buttons in the wrong places.
    out_of_mux = bool(body[cursor] & 0x80)
    cursor += 1
    if not out_of_mux:
        cursor += 5 + 5  # composition and selection timeouts
    cursor += 3  # user_timeout_duration
    if cursor >= len(body):
        raise StreamError("the composition ends before its pages")

    pages = body[cursor]
    cursor += 1
    if pages == 0:
        return width, height, (), 0, 0

    return (width, height, *_read_page(body, cursor))


def _skip_effect_sequence(body: bytes, cursor: int) -> int:
    """Step over a page's in or out animation.

    Every menu we make has none of this, and an empty sequence is two zero
    bytes — which is why reading it as a fixed two bytes worked for years and
    on every disc we made. It is not two bytes on a disc that animates its
    menu in, and there the two zero bytes are read out of the middle of a
    window rectangle.
    """
    if cursor >= len(body):
        return cursor
    windows = body[cursor]
    cursor += 1 + windows * 9  # id(1) x(2) y(2) width(2) height(2)
    if cursor >= len(body):
        return len(body)

    effects = body[cursor]
    cursor += 1
    for _ in range(effects):
        if cursor + 5 > len(body):
            return len(body)
        # duration(3) palette_id_ref(1) number_of_composition_objects(1)
        objects = body[cursor + 4]
        cursor += 5
        for _ in range(objects):
            if cursor + 8 > len(body):
                return len(body)
            cropped = bool(body[cursor + 3] & 0x80)
            cursor += 16 if cropped else 8
    return cursor


def _read_page(body: bytes, cursor: int) -> tuple[tuple[Button, ...], int, int]:
    """The first page: its default button, then its button overlap groups."""
    if cursor + 18 > len(body):
        raise StreamError("the page header is truncated")
    cursor += 1  # page_id
    cursor += 1  # page_version_number
    cursor += 8  # UO_mask_table: a fixed 64 bits, not a length-prefixed list
    cursor = _skip_effect_sequence(body, cursor)  # in_effects
    cursor = _skip_effect_sequence(body, cursor)  # out_effects
    cursor += 1  # animation_frame_rate
    if cursor + 6 > len(body):
        raise StreamError("the page header is truncated")
    default_selected = int.from_bytes(body[cursor : cursor + 2], "big")
    cursor += 2
    cursor += 2  # default_activated_button_id_ref
    palette_id_ref = body[cursor]
    cursor += 1
    if cursor >= len(body):
        raise StreamError("the page ends before its buttons")

    groups = body[cursor]
    cursor += 1

    buttons: list[Button] = []
    for _ in range(groups):
        # One button overlap group: a default reference, a count, then the
        # buttons themselves.
        if cursor + 3 > len(body) or len(buttons) >= MAX_BUTTONS:
            break
        cursor += 2  # default_valid_button_id_ref
        in_group = body[cursor]
        cursor += 1
        for _button in range(in_group):
            if len(buttons) >= MAX_BUTTONS:
                break
            button, cursor = _read_button(body, cursor)
            if button is None:
                break
            buttons.append(button)
    return tuple(buttons), default_selected, palette_id_ref


def _read_button(body: bytes, cursor: int) -> tuple[Button | None, int]:
    if cursor + 25 > len(body):
        return None, cursor
    read = int.from_bytes
    button_id = read(body[cursor : cursor + 2], "big")
    x = read(body[cursor + 5 : cursor + 7], "big")
    y = read(body[cursor + 7 : cursor + 9], "big")
    upper = read(body[cursor + 9 : cursor + 11], "big")
    lower = read(body[cursor + 11 : cursor + 13], "big")
    left = read(body[cursor + 13 : cursor + 15], "big")
    right = read(body[cursor + 15 : cursor + 17], "big")
    # button_id(2) numeric_select(2) auto_action(1) x(2) y(2)
    # up(2) down(2) left(2) right(2) = 17 bytes so far.
    normal = read(body[cursor + 17 : cursor + 19], "big")
    cursor += 17 + 2 + 2 + 1          # normal: start, end, flags
    cursor += 1                       # selected_state_sound_id_ref
    selected = read(body[cursor : cursor + 2], "big")
    cursor += 2 + 2 + 1               # selected: start, end, flags
    cursor += 1                       # activated_state_sound_id_ref
    activated = read(body[cursor : cursor + 2], "big")
    cursor += 2 + 2                   # activated: start, end
    if cursor + 2 > len(body):
        return None, cursor
    commands = read(body[cursor : cursor + 2], "big")
    # Sixteen bits of command count is up to 786 KB of navigation commands
    # claimed by a button in a segment that may be forty bytes long. A
    # count the segment cannot hold is a lie, and a lie about one button
    # used to swallow every button after it (the cursor was clamped to the
    # end). Now the page is refused: a segment that lies about its own
    # size is not one to draw buttons from.
    remaining = max(0, len(body) - (cursor + 2))
    if commands * 12 > remaining:
        raise StreamError(
            f"button {button_id} claims {commands} navigation commands and only "
            f"{remaining} bytes remain in its segment; refusing a page that lies "
            f"about its own size"
        )
    cursor = cursor + 2 + commands * 12
    return (
        Button(
            button_id=button_id,
            x=x,
            y=y,
            normal_object=normal,
            selected_object=selected,
            activated_object=activated,
            upper=upper,
            lower=lower,
            left=left,
            right=right,
            commands=commands,
        ),
        cursor,
    )


__all__ = ["IG_PID", "Button", "Menu", "StreamError", "payload_of", "read", "segments"]
