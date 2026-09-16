"""What we write onto a disc, read back off it.

The authoring side and the reading side were written from the same reading
of the specification, so agreeing with each other proves less than it looks.
What it does prove, and what nothing else could, is that the menu is really
in the clip: the right size, the right number of buttons, at the right
coordinates, with three distinct pictures each and neighbours that wrap.

That is worth having because a menu cannot be checked by looking at one.
``libvlc_video_take_snapshot`` returns the video plane and nothing above it,
so a working menu and a broken one photograph identically — which is how a
themed menu could have shipped with no buttons on it and nobody the wiser.
"""

from __future__ import annotations

import pytest

from tests.fixtures.authoring import graphics, hdmv
from wti_player.formats import hdmv_read


def a_menu(labels=("PLAY", "CHAPTERS", "EXTRAS"), width=1920, height=1080):
    """A menu with three pictures per button, the way a theme renders one."""
    palette = graphics.MenuPalette()
    for index, label in enumerate(labels):
        palette.add(index * 3, graphics.button_bitmap(label))
        palette.add(index * 3 + 1, graphics.button_bitmap(label, selected=True))
        palette.add(index * 3 + 2, graphics.button_bitmap(label, selected=True))
    palette.build()

    count = len(labels)
    buttons = tuple(
        hdmv.Button(
            button_id=index,
            x=96,
            y=630 + index * 83,
            normal_object=index * 3,
            selected_object=index * 3 + 1,
            activated_object=index * 3 + 2,
            upper=(index - 1) % count,
            lower=(index + 1) % count,
            commands=(hdmv.cmd_jump_title(1),) if index == 0 else (),
        )
        for index in range(count)
    )
    return hdmv.Menu(
        width=width,
        height=height,
        frame_rate_code=hdmv.FRAME_RATE_23_976,
        palette=palette.palette(0),
        objects=palette.objects(),
        pages=[hdmv.Page(page_id=0, palette_id=0, buttons=buttons, default_selected=0)],
    )


def as_stream(menu: hdmv.Menu) -> bytes:
    return b"".join(hdmv.ts_packets(hdmv.pes_packets(menu.segments(), 0)))


class TestTheRoundTrip:
    def test_the_menu_comes_back_the_size_it_went_in(self):
        read = hdmv_read.read(as_stream(a_menu()))
        assert (read.width, read.height) == (1920, 1080)

    def test_every_button_comes_back(self):
        read = hdmv_read.read(as_stream(a_menu()))
        assert len(read.buttons) == 3

    def test_they_come_back_where_they_were_put(self):
        read = hdmv_read.read(as_stream(a_menu()))
        assert [(b.x, b.y) for b in read.buttons] == [(96, 630), (96, 713), (96, 796)]

    def test_each_has_three_pictures_of_itself(self):
        """Normal, selected, activated. A theme renders all three."""
        read = hdmv_read.read(as_stream(a_menu()))
        assert all(button.has_three_states for button in read.buttons)

    def test_the_column_wraps_top_to_bottom(self):
        read = hdmv_read.read(as_stream(a_menu()))
        assert read.buttons[0].upper == 2
        assert read.buttons[2].lower == 0

    def test_only_the_first_button_does_anything(self):
        read = hdmv_read.read(as_stream(a_menu()))
        assert [button.commands for button in read.buttons] == [1, 0, 0]

    def test_the_pictures_are_all_there(self):
        read = hdmv_read.read(as_stream(a_menu()))
        assert read.objects == 9
        assert read.usable

    def test_the_palette_travels_with_it(self):
        read = hdmv_read.read(as_stream(a_menu()))
        assert read.palette_entries == 256

    @pytest.mark.parametrize("count", [1, 2, 5, 8])
    def test_any_number_of_buttons_survives(self, count):
        menu = a_menu(labels=tuple(f"BUTTON {n}" for n in range(count)))
        assert len(hdmv_read.read(as_stream(menu)).buttons) == count

    @pytest.mark.parametrize(("width", "height"), [(1920, 1080), (1280, 720), (720, 480)])
    def test_any_menu_size_survives(self, width, height):
        read = hdmv_read.read(as_stream(a_menu(width=width, height=height)))
        assert (read.width, read.height) == (width, height)


class TestOnARealDisc:
    def test_the_fixture_disc_has_the_menu_it_claims(self, menu_disc):
        clip = menu_disc / "BDMV" / "STREAM" / "00000.m2ts"
        read = hdmv_read.read(clip.read_bytes())
        assert len(read.buttons) == 2
        assert read.usable
        assert (read.width, read.height) == (1280, 720)

    def test_the_stream_is_on_the_pid_a_player_looks_at(self, menu_disc):
        clip = (menu_disc / "BDMV" / "STREAM" / "00000.m2ts").read_bytes()
        assert hdmv_read.payload_of(clip, hdmv_read.IG_PID)
        assert not hdmv_read.payload_of(clip, 0x1401), "nothing should be on a neighbour PID"


class TestNotBeingFooled:
    def test_a_clip_with_no_menu_says_so(self, feature_disc):
        clip = (feature_disc / "BDMV" / "STREAM" / "00000.m2ts").read_bytes()
        with pytest.raises(hdmv_read.StreamError):
            hdmv_read.read(clip)

    def test_rubbish_says_so(self):
        with pytest.raises(hdmv_read.StreamError):
            hdmv_read.read(b"\x47" + b"\x00" * 20_000)

    def test_nothing_says_so(self):
        with pytest.raises(hdmv_read.StreamError):
            hdmv_read.read(b"")

    @pytest.mark.parametrize("keep", [0.02, 0.05, 0.12, 0.35, 0.6, 0.9])
    def test_a_truncated_stream_never_invents_a_button(self, keep):
        """Cutting the stream short must lose buttons, never add or move them.

        It does NOT have to raise. The composition is the first segment in a
        display set, so a stream cut after it carries a complete and correct
        menu with its pictures missing — which is a true answer, and the one
        a decoder gets when a disc is scratched further in.
        """
        menu = a_menu()
        stream = as_stream(menu)
        cut = stream[: max(1, int(len(stream) * keep))]
        try:
            read = hdmv_read.read(cut)
        except hdmv_read.StreamError:
            return  # also a fine answer

        assert len(read.buttons) <= 3
        for button in read.buttons:
            assert button.x == 96
            assert button.y in (630, 713, 796)
            assert button.commands <= 1
