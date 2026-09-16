"""P6 (28 Aug 2026): ``Menu.usable`` resolves ids instead of trusting them.

A button that names picture 7 in a stream that defines pictures 0..2 is a
button with no picture; a page that asks for palette 3 in a stream with
palette 0 has no colours. Both used to count as usable.
"""

from __future__ import annotations

import pytest

from tests.fixtures.authoring import hdmv
from tests.unit.test_hdmv_round_trip import a_menu, as_stream
from wti_player.formats import hdmv_read


class TestResolvingIds:
    def test_a_real_menu_is_usable_and_counts_its_content(self) -> None:
        menu = hdmv_read.read(as_stream(a_menu()))
        assert menu.usable
        assert menu.objects == len(menu.object_ids)
        assert menu.objects >= len(menu.buttons)
        assert 0 in menu.palette_ids
        assert menu.palette_id_ref in menu.palette_ids

    def test_a_button_pointing_at_a_picture_the_stream_does_not_carry_is_not_usable(self) -> None:
        stream = a_menu()
        page = stream.pages[0]
        broken = hdmv.Button(
            button_id=page.buttons[0].button_id,
            x=page.buttons[0].x,
            y=page.buttons[0].y,
            normal_object=250,
            selected_object=page.buttons[0].selected_object,
            activated_object=page.buttons[0].activated_object,
            upper=page.buttons[0].upper,
            lower=page.buttons[0].lower,
            commands=page.buttons[0].commands,
        )
        stream.pages[0] = hdmv.Page(
            page_id=0, palette_id=0, buttons=(broken, *page.buttons[1:]), default_selected=0
        )
        menu = hdmv_read.read(as_stream(stream))
        assert 250 not in menu.object_ids
        assert not menu.usable

    def test_a_page_asking_for_a_palette_the_stream_does_not_define_is_not_usable(self) -> None:
        stream = a_menu()
        page = stream.pages[0]
        stream.pages[0] = hdmv.Page(
            page_id=0, palette_id=5, buttons=page.buttons, default_selected=0
        )
        menu = hdmv_read.read(as_stream(stream))
        assert menu.palette_id_ref == 5
        assert 5 not in menu.palette_ids
        assert not menu.usable

    def test_objects_are_counted_by_id_not_by_segment(self) -> None:
        # The same stream twice over: every ODS repeats, the ids do not.
        stream = a_menu()
        segments = stream.segments()
        doubled = b"".join(hdmv.ts_packets(hdmv.pes_packets(segments + segments, 0)))
        once = hdmv_read.read(as_stream(stream))
        twice = hdmv_read.read(doubled)
        assert twice.objects == once.objects


class TestALyingCommandCount:
    def test_a_button_claiming_more_commands_than_the_segment_holds_does_not_swallow_the_rest(
        self,
    ) -> None:
        menu = a_menu(labels=("PLAY", "CHAPTERS", "EXTRAS"))
        stream = as_stream(menu)
        parts = hdmv_read.segments(hdmv_read.payload_of(stream))
        ics = next(body for kind, body in parts if kind == hdmv_read.SEGMENT_ICS)
        # Find the first button and inflate its command count, which sits
        # 33 bytes in: button_id(2) numeric(2) auto(1) x(2) y(2) up down
        # left right(8) normal(2) start end flags(5) sound(1) selected(2)
        # start end flags(5) sound(1) activated(2) start end(4).
        first = menu.pages[0].buttons[0]
        # Its x and y are distinctive; the id sits five bytes before them.
        x_bytes = first.x.to_bytes(2, "big") + first.y.to_bytes(2, "big")
        at = ics.find(x_bytes) - 5
        assert at > 0, "the first button was not where expected"
        assert ics[at : at + 2] == first.button_id.to_bytes(2, "big")
        # The truthful page has three buttons.
        _width, _height, buttons, _selected, _palette = hdmv_read._read_composition(ics)
        assert len(buttons) == 3
        assert buttons[0].button_id == first.button_id
        # A count the segment cannot hold is a lie about the page's own
        # size. Before 28 Aug 2026 the cursor was clamped to the end and
        # the two buttons after it were quietly lost while the menu still
        # read as usable; now the page is refused and the caller hears why.
        lying = bytearray(ics)
        lying[at + 33 : at + 35] = (0xFFFF).to_bytes(2, "big")
        with pytest.raises(hdmv_read.StreamError, match="claims 65535"):
            hdmv_read._read_composition(bytes(lying))
