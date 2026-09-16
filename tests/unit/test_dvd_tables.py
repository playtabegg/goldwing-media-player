"""The DVD tables nothing was checking.

A mutation audit on 2026-08-23 found four pieces of the DVD reader that could
be emptied, moved or reversed with the whole suite still green. Each of these
tests exists to kill one of those mutations, and each names it.

The general lesson, which is worth more than the four fixes: a test that
asserts a list has the right *shape* does not test the code that fills it.
``len(palette) == 16`` passes whatever sixteen numbers you read.
"""

from __future__ import annotations

import pytest

from tests.fixtures.authoring import videots
from wti_player.formats import dvd_spu, ifo


class TestTheStreamTables:
    """Mutation killed: ``return tuple(audio), tuple(subtitles)`` -> ``return (), ()``.

    A DVD's audio and subtitle lists were parsed and never looked at. Every
    disc could have shown an empty track picker with the suite green.
    """

    def test_the_audio_languages_are_the_ones_on_the_disc(self, dvd_disc):
        # The fixture is written with audio_languages=("en",).
        read = ifo.read(dvd_disc)
        feature = read.main_feature
        assert [stream.language for stream in feature.audio] == ["en"]

    def test_the_subtitle_languages_are_the_ones_on_the_disc(self, dvd_disc):
        # ...and subtitle_languages=("en", "fr").
        read = ifo.read(dvd_disc)
        assert [stream.language for stream in read.main_feature.subtitles] == ["en", "fr"]

    def test_an_audio_stream_can_be_named(self, dvd_disc):
        read = ifo.read(dvd_disc)
        name = read.main_feature.audio[0].name
        assert "EN" in name
        assert "AC-3" in name

    def test_the_counts_are_read_from_where_the_format_puts_them(self, dvd_disc):
        """Moving either offset by sixteen bytes has to fail something."""
        read = ifo.read(dvd_disc)
        assert len(read.main_feature.audio) == 1
        assert len(read.main_feature.subtitles) == 2


class TestThePalette:
    """Mutation killed: ``_PGC_PALETTE = 0xA4`` -> ``0xB4``.

    Reading sixteen bytes further into the chain still yields sixteen
    entries with more than one distinct value, so a shape assertion passes
    and every DVD menu is drawn in whatever happened to be there.
    """

    @pytest.fixture
    def menu_chain(self, generated_dir):
        path = generated_dir / "dvd_menu_disc"
        if not (path / "VIDEO_TS" / "VTS_01_0.VOB").is_file():
            pytest.skip("run: python tools/make_fixtures.py")
        from wti_player.dvd import menu

        found = menu.read(path)
        assert found is not None
        return found

    def test_the_colours_are_the_ones_written_onto_the_disc(self, menu_chain):
        # The authoring module's own palette, round-tripped. Y in the top
        # byte, both chroma channels at 0x80, which is what a grey is.
        expected = tuple(
            ((entry >> 16) & 0xFF) << 16 | 0x8080 for entry in videots.DEFAULT_PALETTE
        )
        assert menu_chain.palette == expected

    def test_the_first_entry_is_video_black(self, menu_chain):
        assert (menu_chain.palette[0] >> 16) & 0xFF == 16

    def test_the_last_entry_is_not_black(self, menu_chain):
        """Index 15 is the white a menu's text is drawn in."""
        assert (menu_chain.palette[15] >> 16) & 0xFF > 200


class TestWhichVobsAreTheFilm:
    """Mutation killed: the glob ``_[1-9].VOB`` -> ``_[0-9].VOB``.

    ``VTS_nn_0.VOB`` is the title set's MENU. Including it puts the menu in
    front of the film. The plain DVD fixture has no menu VOB at all, so the
    only fixture that can catch this is the one with a menu on it — and
    nothing was pointing this function at it.
    """

    @pytest.fixture
    def menu_dvd(self, generated_dir):
        path = generated_dir / "dvd_menu_disc"
        if not (path / "VIDEO_TS" / "VTS_01_0.VOB").is_file():
            pytest.skip("run: python tools/make_fixtures.py")
        return path

    def test_the_menu_vob_is_not_part_of_the_film(self, menu_dvd):
        read = ifo.read(menu_dvd)
        names = [path.name for path in read.vob_files(read.main_feature)]
        assert "VTS_01_0.VOB" not in names, "the menu would play before the film"

    def test_the_title_vob_is(self, menu_dvd):
        read = ifo.read(menu_dvd)
        names = [path.name for path in read.vob_files(read.main_feature)]
        assert "VTS_01_1.VOB" in names

    def test_the_menu_vob_is_there_to_be_excluded(self, menu_dvd):
        """Otherwise the test above passes for the wrong reason."""
        assert (menu_dvd / "VIDEO_TS" / "VTS_01_0.VOB").is_file()


class TestColour:
    """Mutation killed: ``yuv_to_rgb(y, cb, cr)`` -> ``(y, cr, cb)``.

    Every existing case had ``cb == cr == 128``, which multiplies all four
    chroma coefficients by zero. Swapping the two arguments, or deleting the
    chroma terms outright, passed. A red button would have rendered blue and
    a colour menu would have rendered grey.
    """

    @pytest.mark.parametrize(
        ("yuv", "rgb", "what"),
        [
            ((81, 90, 240), (255, 0, 0), "red"),
            ((145, 54, 34), (0, 255, 0), "green"),
            ((41, 240, 110), (0, 0, 255), "blue"),
            ((210, 16, 146), (255, 255, 0), "yellow"),
            ((235, 128, 128), (255, 255, 255), "white"),
            ((16, 128, 128), (0, 0, 0), "black"),
        ],
    )
    def test_bt601_primaries(self, yuv, rgb, what):
        """The standard's own values, within rounding."""
        got = dvd_spu.yuv_to_rgb(*yuv)
        assert all(abs(a - b) <= 6 for a, b in zip(got, rgb, strict=True)), f"{what}: {got}"

    def test_the_arguments_are_not_interchangeable(self):
        """Whatever else is true, y, cb, cr is not y, cr, cb."""
        assert dvd_spu.yuv_to_rgb(81, 90, 240) != dvd_spu.yuv_to_rgb(81, 240, 90)

    def test_chroma_actually_moves_the_answer(self):
        grey = dvd_spu.yuv_to_rgb(128, 128, 128)
        assert dvd_spu.yuv_to_rgb(128, 200, 128) != grey, "Cb does nothing"
        assert dvd_spu.yuv_to_rgb(128, 128, 200) != grey, "Cr does nothing"


class TestTheResolvedHighlight:
    """The four colours a lit button is painted in, by value.

    The existing test asserted four four-tuples with one alpha above zero,
    which a constant satisfies.
    """

    @pytest.fixture
    def lit(self, generated_dir):
        path = generated_dir / "dvd_menu_disc"
        if not (path / "VIDEO_TS" / "VTS_01_0.VOB").is_file():
            pytest.skip("run: python tools/make_fixtures.py")
        from wti_player.dvd import menu

        found = menu.read(path)
        assert found is not None
        return found

    def test_the_lit_colours_come_out_of_this_disc_s_own_palette(self, lit):
        colours = lit.colours(lit=True)
        assert colours is not None

        highlight = lit.navigator.highlight
        chosen = highlight.colours_for(lit.navigator.selected_button)
        expected = dvd_spu.resolve_palette(
            list(lit.palette), chosen.selected_palette, chosen.selected_alpha
        )
        assert colours == expected

    def test_the_visible_slot_is_the_one_the_disc_named(self, lit):
        """SELECTED_COLOURS lights emphasis 1 and the pattern, opaque."""
        colours = lit.colours(lit=True)
        opaque = [index for index, entry in enumerate(colours) if entry[3] > 200]
        assert opaque == [2, 3], opaque

    def test_a_lit_colour_is_not_the_same_as_an_unlit_one(self, lit):
        """Otherwise the highlight is there and nobody can see it."""
        colours = lit.colours(lit=True)
        assert len({entry[:3] for entry in colours}) > 1
