"""Author an HDMV interactive-graphics (menu) stream.

No open tool writes these — libbluray is a reader — so the Player's only way
to get a disc with a *real* Blu-ray menu on it, to prove the engine can drive
one, is to write the menu itself. That is what this module does. It is test
scaffolding, not product code: it makes the smallest thing that is a genuine
HDMV menu, not an authoring suite.

An IG display set is four kinds of segment, in this order:

    ICS   what the pages and buttons are, and what each button does
    PDS   the palette the button bitmaps index into
    ODS   the button bitmaps themselves, run-length encoded
    END   that is the whole display set

They go out as PES packets on PID 0x1400 inside the clip's M2TS, and
libbluray's graphics controller decodes them and composes the overlay.

Reference for the byte layouts: the Blu-ray "System Description" part 3, and
libbluray's own parsers (``hdmv/ig_decoder.c``), which are the practical
authority on what a player will actually accept.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Segment types.
SEG_PDS = 0x14
SEG_ODS = 0x15
SEG_ICS = 0x18
SEG_END = 0x80

#: PID the Blu-ray spec reserves for the first interactive-graphics stream.
IG_PID = 0x1400
#: PMT stream type for interactive graphics.
IG_STREAM_TYPE = 0x91

#: Frame-rate codes as they appear in a video descriptor.
FRAME_RATE_23_976 = 1
FRAME_RATE_24 = 2
FRAME_RATE_25 = 3
FRAME_RATE_29_97 = 4
FRAME_RATE_50 = 6
FRAME_RATE_59_94 = 7

#: "no button" / "no page" references.
NONE_REF = 0xFFFF


# --------------------------------------------------------------------------
# HDMV navigation commands
#
# Each command is 12 bytes: a 4-byte opcode then two 4-byte operands. The
# opcode's bit layout, MSB first, is
#
#   op_cnt(3) grp(2) sub_grp(3) | imm_op1(1) imm_op2(1) _(2) branch_opt(4)
#   _(4) cmp_opt(4)             | _(3) set_opt(5)
#
# which is exactly how libbluray reads it, and how tsMuxeR writes it — the
# commands in a tsMuxeR MovieObject.bdmv decode correctly under this layout,
# which is the check that made these safe to write by hand.
# --------------------------------------------------------------------------

GRP_BRANCH = 0
SUB_GOTO = 0
SUB_JUMP = 1
SUB_PLAY = 2


def _command(
    op_count: int,
    group: int,
    sub_group: int,
    *,
    branch_opt: int = 0,
    cmp_opt: int = 0,
    set_opt: int = 0,
    imm1: bool = False,
    imm2: bool = False,
    dst: int = 0,
    src: int = 0,
) -> bytes:
    byte0 = ((op_count & 0x07) << 5) | ((group & 0x03) << 3) | (sub_group & 0x07)
    byte1 = (0x80 if imm1 else 0) | (0x40 if imm2 else 0) | (branch_opt & 0x0F)
    byte2 = cmp_opt & 0x0F
    byte3 = set_opt & 0x1F
    return bytes((byte0, byte1, byte2, byte3)) + dst.to_bytes(4, "big") + src.to_bytes(4, "big")


def cmd_nop() -> bytes:
    return _command(0, GRP_BRANCH, SUB_GOTO, branch_opt=0)


def cmd_jump_object(object_id: int) -> bytes:
    """Jump to a movie object. The classic end-of-program command."""
    return _command(1, GRP_BRANCH, SUB_JUMP, branch_opt=1, imm1=True, dst=object_id)


def cmd_jump_title(title: int) -> bytes:
    """Jump to a title, numbered as the index numbers them (1-based)."""
    return _command(1, GRP_BRANCH, SUB_JUMP, branch_opt=2, imm1=True, dst=title)


def cmd_play_playlist(playlist: int) -> bytes:
    return _command(1, GRP_BRANCH, SUB_PLAY, branch_opt=1, imm1=True, dst=playlist)


def cmd_play_playlist_at_mark(playlist: int, mark: int) -> bytes:
    """Play a playlist starting at one of its marks — i.e. jump to a chapter."""
    return _command(
        2, GRP_BRANCH, SUB_PLAY, branch_opt=3, imm1=True, imm2=True, dst=playlist, src=mark
    )


# --------------------------------------------------------------------------
# Run-length encoding
# --------------------------------------------------------------------------


def encode_rle(rows: list[list[int]]) -> bytes:
    """Encode palette-indexed rows into the HDMV graphics RLE.

    Colour 0 is the transparent entry by convention, and gets the shorter
    codes, which is why menus with a lot of transparency compress so well.
    """
    out = bytearray()
    for row in rows:
        index = 0
        width = len(row)
        while index < width:
            colour = row[index]
            run = 1
            while index + run < width and row[index + run] == colour and run < 16383:
                run += 1
            index += run
            if colour == 0:
                while run:
                    take = min(run, 16383)
                    run -= take
                    if take <= 63:
                        out += bytes((0x00, take))
                    else:
                        out += bytes((0x00, 0x40 | (take >> 8), take & 0xFF))
            else:
                while run:
                    take = min(run, 16383)
                    run -= take
                    if take <= 2:
                        out += bytes((colour,)) * take
                    elif take <= 63:
                        out += bytes((0x00, 0x80 | take, colour))
                    else:
                        out += bytes((0x00, 0xC0 | (take >> 8), take & 0xFF, colour))
        out += b"\x00\x00"  # end of line
    return bytes(out)


# --------------------------------------------------------------------------
# The menu model
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GraphicObject:
    """One button bitmap: palette indices, one row per line."""

    object_id: int
    width: int
    height: int
    rows: list[list[int]]

    def to_segment(self) -> bytes:
        rle = encode_rle(self.rows)
        body = bytearray()
        body += self.object_id.to_bytes(2, "big")
        body += b"\x00"  # object_version_number
        body += b"\xc0"  # first_in_sequence + last_in_sequence
        body += (len(rle) + 4).to_bytes(3, "big")  # object_data_length
        body += self.width.to_bytes(2, "big")
        body += self.height.to_bytes(2, "big")
        body += rle
        return _segment(SEG_ODS, bytes(body))


@dataclass(frozen=True)
class Palette:
    """YCbCr + alpha entries. Entry 0 is left fully transparent."""

    palette_id: int
    entries: dict[int, tuple[int, int, int, int]]

    def to_segment(self) -> bytes:
        body = bytearray()
        body += bytes((self.palette_id, 0))  # id, version
        for entry_id in sorted(self.entries):
            y, cr, cb, alpha = self.entries[entry_id]
            body += bytes((entry_id, y, cr, cb, alpha))
        return _segment(SEG_PDS, bytes(body))


@dataclass(frozen=True)
class Button:
    """One button, its four neighbours, its three states, and what it does."""

    button_id: int
    x: int
    y: int
    normal_object: int
    selected_object: int
    numeric_select: int = 0xFFFF
    activated_object: int = NONE_REF
    upper: int = NONE_REF
    lower: int = NONE_REF
    left: int = NONE_REF
    right: int = NONE_REF
    auto_action: bool = False
    commands: tuple[bytes, ...] = ()

    def to_bytes(self) -> bytes:
        out = bytearray()
        out += self.button_id.to_bytes(2, "big")
        out += self.numeric_select.to_bytes(2, "big")
        out += bytes((0x80 if self.auto_action else 0x00,))
        out += self.x.to_bytes(2, "big")
        out += self.y.to_bytes(2, "big")
        for neighbour in (self.upper, self.lower, self.left, self.right):
            out += neighbour.to_bytes(2, "big")
        # normal state
        out += self.normal_object.to_bytes(2, "big")
        out += self.normal_object.to_bytes(2, "big")
        out += b"\x00"  # repeat / complete flags
        # selected state
        out += b"\xff"  # selected_state_sound_id_ref: none
        out += self.selected_object.to_bytes(2, "big")
        out += self.selected_object.to_bytes(2, "big")
        out += b"\x00"
        # activated state
        out += b"\xff"  # activated_state_sound_id_ref: none
        activated = self.activated_object if self.activated_object != NONE_REF else self.selected_object
        out += activated.to_bytes(2, "big")
        out += activated.to_bytes(2, "big")
        out += len(self.commands).to_bytes(2, "big")
        for command in self.commands:
            out += command
        return bytes(out)


@dataclass(frozen=True)
class Page:
    """A menu page: a set of button overlap groups sharing one palette."""

    page_id: int
    palette_id: int
    buttons: tuple[Button, ...]
    default_selected: int = 0
    default_activated: int = NONE_REF
    #: 0xFF means "do not animate", which is what a still menu wants.
    animation_frame_rate: int = 0xFF

    def to_bytes(self) -> bytes:
        out = bytearray()
        out += bytes((self.page_id, 0))  # page_id, page_version_number
        out += b"\x00" * 8  # UO_mask_table: a fixed 64 bits, not a length-prefixed list
        out += b"\x00\x00"  # in_effects: no windows, no effects
        out += b"\x00\x00"  # out_effects: no windows, no effects
        out += bytes((self.animation_frame_rate,))
        out += self.default_selected.to_bytes(2, "big")
        out += self.default_activated.to_bytes(2, "big")
        out += bytes((self.palette_id,))
        out += bytes((len(self.buttons),))  # one button overlap group per button
        for button in self.buttons:
            out += button.button_id.to_bytes(2, "big")  # default_valid_button_id_ref
            out += b"\x01"  # number_of_buttons in this group
            out += button.to_bytes()
        return bytes(out)


@dataclass
class Menu:
    """Everything needed to emit one interactive composition."""

    width: int
    height: int
    frame_rate_code: int
    palette: Palette
    objects: list[GraphicObject]
    pages: list[Page]
    #: 90 kHz. Zero means "the menu never times out", which is what we want.
    composition_timeout_pts: int = 0
    selection_timeout_pts: int = 0
    #: Seconds of no input before the menu hides itself. Zero means never.
    user_timeout_seconds: int = 0
    composition_number: int = 0
    _: dict = field(default_factory=dict, repr=False)

    def interactive_composition(self) -> bytes:
        body = bytearray()
        # stream_model 0 = multiplexed with the AV clip.
        # user_interface_model 0 = always-on (a pop-up menu would be 1).
        body += bytes((0x00,))
        body += _pts_field(self.composition_timeout_pts)
        body += _pts_field(self.selection_timeout_pts)
        body += (self.user_timeout_seconds * 45000).to_bytes(3, "big")
        body += bytes((len(self.pages),))
        for page in self.pages:
            body += page.to_bytes()
        return bytes(body)

    def ics_segment(self) -> bytes:
        composition = self.interactive_composition()
        body = bytearray()
        # video_descriptor
        body += self.width.to_bytes(2, "big")
        body += self.height.to_bytes(2, "big")
        body += bytes(((self.frame_rate_code & 0x0F) << 4,))
        # composition_descriptor: composition_number, state 2 = epoch start
        body += self.composition_number.to_bytes(2, "big")
        body += bytes((0x80,))
        # sequence_descriptor: first and last in sequence
        body += bytes((0xC0,))
        # interactive_composition() opens with its own 24-bit length, counting
        # only what follows it. A decoder that reads a length longer than
        # the bytes it has treats the segment as corrupt and drops the menu.
        body += len(composition).to_bytes(3, "big")
        body += composition
        return _segment(SEG_ICS, bytes(body))

    def segments(self) -> list[bytes]:
        """The whole display set, in the order a decoder expects it."""
        return [
            self.ics_segment(),
            self.palette.to_segment(),
            *(obj.to_segment() for obj in self.objects),
            _segment(SEG_END, b""),
        ]


def _segment(segment_type: int, body: bytes) -> bytes:
    return bytes((segment_type,)) + len(body).to_bytes(2, "big") + body


def _pts_field(pts: int) -> bytes:
    """7 reserved bits then a 33-bit PTS, as the composition packs them."""
    return (pts & ((1 << 33) - 1)).to_bytes(5, "big")


# --------------------------------------------------------------------------
# Turning segments into a transport stream
# --------------------------------------------------------------------------


def pes_packets(segments: list[bytes], pts_90khz: int) -> list[bytes]:
    """Wrap each segment in a PES packet, stream_id 0xBD, with a PTS and DTS.

    Interactive graphics carry both timestamps. Giving them the same value is
    legal and says "decode and present at the same instant", which is right
    for a menu that is up from the first frame.
    """
    out: list[bytes] = []
    for segment in segments:
        header = bytearray()
        header += b"\x00\x00\x01\xbd"  # packet_start_code_prefix + private_stream_1
        payload_len = len(segment) + 3 + 10  # flags(3) + PTS(5) + DTS(5)
        header += payload_len.to_bytes(2, "big")
        header += b"\x81"  # '10' marker, no scrambling, original
        header += b"\xc0"  # PTS and DTS both present
        header += b"\x0a"  # PES_header_data_length
        header += _timestamp(pts_90khz, 0b0011)
        header += _timestamp(pts_90khz, 0b0001)
        out.append(bytes(header) + segment)
    return out


def _timestamp(value: int, prefix: int) -> bytes:
    value &= (1 << 33) - 1
    byte0 = (prefix << 4) | (((value >> 30) & 0x07) << 1) | 1
    byte1 = (value >> 22) & 0xFF
    byte2 = (((value >> 15) & 0x7F) << 1) | 1
    byte3 = (value >> 7) & 0xFF
    byte4 = ((value & 0x7F) << 1) | 1
    return bytes((byte0, byte1, byte2, byte3, byte4))


def ts_packets(pes: list[bytes], pid: int = IG_PID) -> list[bytes]:
    """Chop PES packets into 188-byte transport packets."""
    packets: list[bytes] = []
    counter = 0
    for payload in pes:
        offset = 0
        first = True
        while offset < len(payload):
            header = bytearray(4)
            header[0] = 0x47
            header[1] = (0x40 if first else 0x00) | ((pid >> 8) & 0x1F)
            header[2] = pid & 0xFF
            remaining = len(payload) - offset
            if remaining >= 184:
                header[3] = 0x10 | (counter & 0x0F)
                body = payload[offset : offset + 184]
                offset += 184
            else:
                # Pad the tail out with an adaptation field of stuffing bytes.
                header[3] = 0x30 | (counter & 0x0F)
                stuffing = 184 - remaining
                if stuffing == 1:
                    adaptation = b"\x00"
                else:
                    adaptation = bytes((stuffing - 1, 0x00)) + b"\xff" * (stuffing - 2)
                body = adaptation + payload[offset:]
                offset = len(payload)
            counter = (counter + 1) & 0x0F
            first = False
            packets.append(bytes(header) + body)
    return packets
