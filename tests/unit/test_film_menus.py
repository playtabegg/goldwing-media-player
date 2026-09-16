"""The six film-menu designs, and the four ways the last set failed.

Those four are the reason this file exists, so they are named:

* Five of the six themes ignored the artwork. A valid still went into all
  six and one of them composited it; the rest drew the same flat ground they
  drew with nothing.
* One theme drew no title at all, so a disc arrived as a black screen with a
  list of words floating in it.
* One shipped grey type on a grey photograph while its own contrast check
  reported that no correction was needed.
* One truncated its labels: "AUDIO AND SU...", "ABOUT THIS D...".

A rendered menu cannot be checked by looking at a palette, and the failures
above were all invisible in one. So these read pixels.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PIL")

from PIL import Image, ImageChops, ImageDraw

from wti_player.menu import (
    BUTTON_STATES,
    MIN_CONTRAST,
    MIN_LARGE_CONTRAST,
    THEMES,
    Button,
    ContrastFailure,
    contrast_ratio,
    fonts,
    render_menu,
    safe_box,
)
from wti_player.menu import contrast as measure
from wti_player.menu.designs import base
from wti_player.menu.surface import Surface

KEYS = list(THEMES)

BUTTONS = [
    Button("play", "Play"),
    Button("chapters", "Chapters"),
    Button("audio", "Audio and subtitles"),
    Button("extras", "Extras"),
    Button("about", "About this disc"),
]

LONG_TITLE = "The Cabinet of Dr. Caligari and Other Expressionist Nightmares"


@pytest.fixture(scope="module")
def hostile_still(tmp_path_factory) -> object:
    """A still designed to break a menu: one half near-white, one near-black.

    Real artwork is rarely this cruel, but every failure mode lives in it. A
    label that lands on the wrong half of a photograph is exactly what the
    averaged contrast check used to miss.
    """
    path = tmp_path_factory.mktemp("art") / "hostile.png"
    art = Image.new("RGB", (1920, 1080), (250, 248, 244))
    draw = ImageDraw.Draw(art)
    draw.rectangle([960, 0, 1920, 1080], fill=(8, 9, 11))
    for step in range(0, 1080, 24):
        draw.line([(0, step), (1920, step + 60)], fill=(128, 40, 190), width=6)
    art.save(path)
    return path


@pytest.fixture(scope="module")
def bare(tmp_path_factory):
    """Every theme rendered with no artwork at all."""
    root = tmp_path_factory.mktemp("bare")
    return {key: render_menu(BUTTONS, root / key, theme_key=key, title="Nosferatu") for key in KEYS}


@pytest.fixture(scope="module")
def with_art(tmp_path_factory, hostile_still):
    """Every theme rendered with the same still handed to all of them."""
    root = tmp_path_factory.mktemp("art")
    return {
        key: render_menu(
            BUTTONS,
            root / key,
            theme_key=key,
            title="Nosferatu",
            still=hostile_still,
            poster=hostile_still,
        )
        for key in KEYS
    }


def different_pixels(first: Image.Image, second: Image.Image) -> float:
    """Fraction of pixels whose brightness moved by more than a little."""
    a = first.convert("L")
    b = second.convert("L")
    changed = ImageChops.difference(a, b).point(lambda v: 255 if v > 24 else 0)
    return sum(changed.getdata()) / 255 / (a.width * a.height)


class TestTheArtworkIsUsed:
    """The bug: a valid still went to all six and five ignored it."""

    @pytest.mark.parametrize("key", KEYS)
    def test_every_design_says_it_used_the_artwork(self, key, with_art):
        assert with_art[key].used_artwork, f"{key} was handed a still and did not use it"

    @pytest.mark.parametrize("key", KEYS)
    def test_and_the_pixels_agree(self, key, bare, with_art):
        """Saying so is not enough. The old renderer produced identical files."""
        blank = Image.open(bare[key].background)
        arted = Image.open(with_art[key].background)
        moved = different_pixels(blank, arted)
        assert moved > 0.04, f"{key} drew the same background with and without a still ({moved:.3%})"

    @pytest.mark.parametrize("key", KEYS)
    def test_with_nothing_it_still_looks_like_something(self, key, bare):
        """A design with no artwork must be deliberate, not an empty ground.

        Measured as tonal variety: a flat fill has one or two values and a
        composition has many.
        """
        shades = Image.open(bare[key].background).convert("L").getcolors(maxcolors=256)
        assert shades is None or len(shades) > 12, f"{key} with no artwork is a flat fill"


class TestTheTitleIsDrawn:
    """The bug: one theme drew no title, and nothing noticed."""

    @pytest.mark.parametrize("key", KEYS)
    def test_the_title_changes_the_picture(self, key, tmp_path):
        named = render_menu(BUTTONS, tmp_path / f"{key}-named", theme_key=key, title="Nosferatu")
        blank = render_menu(BUTTONS, tmp_path / f"{key}-blank", theme_key=key, title="")
        moved = different_pixels(Image.open(named.background), Image.open(blank.background))
        assert moved > 0.001, f"{key} draws nothing for the title it was given"

    @pytest.mark.parametrize("key", KEYS)
    def test_display_type_is_readable(self, key, bare, with_art):
        for label, menu in (("bare", bare[key]), ("art", with_art[key])):
            assert menu.display_contrast >= MIN_LARGE_CONTRAST, (
                f"{key} {label}: display type at {menu.display_contrast}:1"
            )


class TestNothingIsTruncated:
    """The bug: "AUDIO AND SU..." on a menu with room to spare."""

    @pytest.mark.parametrize("key", KEYS)
    def test_labels_come_back_whole(self, key, bare):
        shown = [label.upper() for label in bare[key].labels]
        for button in BUTTONS:
            assert button.label.upper() in shown, f"{key} did not draw {button.label!r} in full"

    @pytest.mark.parametrize("key", KEYS)
    def test_no_ellipsis_anywhere(self, key, bare):
        assert not any("\u2026" in label or "..." in label for label in bare[key].labels)

    @pytest.mark.parametrize("key", KEYS)
    def test_a_label_nobody_should_have_written(self, key, tmp_path):
        """An author naming an extra is not doing anything wrong."""
        awkward = Button("extras", "Behind the scenes with the cast and crew, part two")
        menu = render_menu(
            [BUTTONS[0], awkward], tmp_path / key, theme_key=key, title="Nosferatu"
        )
        drawn = " ".join(menu.labels).upper()
        assert "PART TWO" in drawn, f"{key} lost the end of a long label: {menu.labels}"

    @pytest.mark.parametrize("key", KEYS)
    def test_a_title_nobody_should_have_written(self, key, tmp_path):
        menu = render_menu(BUTTONS, tmp_path / key, theme_key=key, title=LONG_TITLE)
        assert menu.display_contrast >= MIN_LARGE_CONTRAST
        assert len(menu.buttons) == len(BUTTONS)

    def test_wrapping_never_drops_a_word(self):
        font = fonts.face("ui", 30, 400)
        words = "Behind the scenes with the cast and crew".split()
        lines = fonts.wrap(" ".join(words), font, 0.1, 200)
        assert " ".join(lines).split() == words


class TestContrastIsMeasuredNotGuessed:
    """The bug: local_scrim 0.00 on a menu with four unreadable buttons."""

    @pytest.mark.parametrize("key", KEYS)
    def test_every_button_clears_the_bar(self, key, bare, with_art):
        for label, menu in (("bare", bare[key]), ("art", with_art[key])):
            for button in menu.buttons:
                assert button.contrast >= MIN_CONTRAST, (
                    f"{key} {label}: {button.label!r} at {button.contrast}:1"
                )

    def test_the_check_can_actually_fail(self):
        """White on white has to come out at 1.0, or nothing else here means anything."""
        surface = Surface((200, 60), (255, 255, 255, 255))
        surface.text((10, 10), "PLAY", fonts.face("ui", 24, 400), (252, 252, 252))
        assert measure.measure(surface.inks[0], None) < 1.2

    def test_and_pass_when_it_should(self):
        surface = Surface((200, 60), (255, 255, 255, 255))
        surface.text((10, 10), "PLAY", fonts.face("ui", 24, 400), (0, 0, 0))
        assert measure.measure(surface.inks[0], None) > 20

    def test_it_reads_the_pixels_behind_the_glyphs_not_the_average(self):
        """The failure that shipped, in miniature.

        A button box that is mostly very dark with a bright corner averages
        to something white type passes against. The glyphs that land on the
        bright corner are the ones nobody can read, and averaging is what
        hides them.
        """
        ground = Image.new("RGBA", (400, 60), (255, 255, 255, 255))
        ImageDraw.Draw(ground).rectangle([0, 0, 280, 60], fill=(20, 20, 20, 255))
        surface = Surface((400, 60), (0, 0, 0, 0))
        surface.image.alpha_composite(ground)
        surface.text((20, 12), "PLAY CHAPTERS EXTRAS", fonts.face("ui", 26, 400), (255, 255, 255))

        bands = ground.convert("RGB").split()
        average = tuple(
            sum(band.getdata()) // (ground.width * ground.height) for band in bands
        )
        assert contrast_ratio((255, 255, 255), average) > MIN_CONTRAST, "the average passes"
        assert measure.measure(surface.inks[0], None) < 1.5, "and the glyphs do not"

    def test_a_menu_that_cannot_be_read_raises(self, tmp_path):
        """Rather than returning and reporting 0.00, which is what used to happen."""

        class Invisible(base.Design):
            key = "invisible"
            name = "Invisible"
            description = "A design that puts white on white. Only ever built here."
            backing = "#ffffff"

            def compose(self, scene):
                surface = Surface((1920, 1080), (255, 255, 255, 255))
                surface.text((200, 200), "A FILM", fonts.face("ui", 90, 700), (10, 10, 10), large=True)

                def painter(tile, state):
                    tile.text((10, 10), "PLAY", fonts.face("ui", 30, 400), (254, 254, 254))

                return base.Composition(
                    surface,
                    (base.Slot("play", "Play", 200, 500, 300, 70, painter),),
                    False,
                )

        from wti_player.menu import designs

        designs.DESIGNS["invisible"] = Invisible()
        try:
            with pytest.raises(ContrastFailure) as failure:
                render_menu([Button("play", "Play")], tmp_path, theme_key="invisible")
            assert "Play" in str(failure.value)
        finally:
            del designs.DESIGNS["invisible"]


class TestTheThreeStates:
    """A person navigates this from a sofa with a remote."""

    @pytest.mark.parametrize("key", KEYS)
    def test_all_three_are_the_same_size(self, key, bare):
        """The HDMV writer positions one rectangle and swaps the picture in it."""
        for button in bare[key].buttons:
            sizes = {Image.open(button.images[state]).size for state in BUTTON_STATES}
            assert len(sizes) == 1, f"{key} {button.key}: states differ in size {sizes}"
            assert sizes.pop() == (button.width, button.height)

    @pytest.mark.parametrize("key", KEYS)
    def test_they_look_different_from_across_a_room(self, key, bare):
        """A tint is not a state. This is why music_film shipped normal and
        activated as identical pictures: the palette said they differed."""
        background = Image.open(bare[key].background).convert("RGBA")
        for button in bare[key].buttons:
            box = (button.x, button.y, button.x + button.width, button.y + button.height)
            seen = {}
            for state in BUTTON_STATES:
                over = background.crop(box).copy()
                with Image.open(button.images[state]) as tile:
                    over.alpha_composite(tile.convert("RGBA"))
                seen[state] = over
            for first, second in (
                ("normal", "selected"),
                ("selected", "activated"),
                ("normal", "activated"),
            ):
                moved = different_pixels(seen[first], seen[second])
                assert moved > 0.15, (
                    f"{key} {button.key}: {first} and {second} differ over "
                    f"{moved:.1%} of the button, which is not a state change"
                )


class TestTheFrame:
    @pytest.mark.parametrize("key", KEYS)
    def test_the_background_is_the_size_a_disc_wants(self, key, bare):
        assert Image.open(bare[key].background).size == (1920, 1080)

    @pytest.mark.parametrize("key", KEYS)
    def test_nothing_pressable_is_where_a_television_crops(self, key, bare):
        left, top, right, bottom = safe_box()
        for button in bare[key].buttons:
            assert button.x >= left and button.y >= top
            assert button.x + button.width <= right
            assert button.y + button.height <= bottom

    @pytest.mark.parametrize("key", KEYS)
    def test_two_renders_are_the_same_file(self, key, tmp_path):
        """Textures are seeded, not random. A visual diff is useless otherwise."""
        first = render_menu(BUTTONS, tmp_path / "a", theme_key=key, title="Nosferatu")
        second = render_menu(BUTTONS, tmp_path / "b", theme_key=key, title="Nosferatu")
        assert first.background.read_bytes() == second.background.read_bytes()


class TestTheAwkwardInput:
    def test_a_menu_with_no_buttons_is_not_a_menu(self, tmp_path):
        with pytest.raises(ValueError):
            render_menu([], tmp_path, theme_key="classic_cinema")

    def test_a_pasted_line_break_does_not_kill_the_render(self, tmp_path):
        """Pillow refuses to measure multi-line text and says so in metrics terms."""
        menu = render_menu(
            [Button("play", "Play\nnow"), Button("about", "About  this   disc")],
            tmp_path,
            theme_key="documentary",
            title="Two\nLines",
        )
        assert menu.labels[0].upper() == "PLAY NOW"

    def test_a_blank_label_falls_back_to_its_key(self, tmp_path):
        menu = render_menu([Button("play", "   ")], tmp_path, theme_key="animation")
        assert menu.labels[0].lower() == "play"

    def test_artwork_that_is_not_a_picture_is_not_fatal(self, tmp_path):
        """A .png that is really a renamed .txt arrives off a web form."""
        fake = tmp_path / "poster.png"
        fake.write_text("not a picture", encoding="utf-8")
        menu = render_menu(BUTTONS, tmp_path / "out", theme_key="poster_art", still=fake)
        assert not menu.used_artwork

    def test_a_retired_theme_name_falls_back_rather_than_stopping_a_press(self, tmp_path):
        menu = render_menu(BUTTONS, tmp_path, theme_key="no_such_theme", title="Nosferatu")
        assert menu.theme_key == "classic_cinema"


class TestTheType:
    def test_only_the_vendored_faces_are_used(self):
        """The old renderer walked C:/Windows/Fonts, so a theme rendered
        differently on two machines and nobody could say which was right."""
        assert set(fonts.FILES) == {"display", "display-italic", "ui"}
        for filename in fonts.FILES.values():
            assert (fonts.FONT_DIR / filename).is_file()

    def test_the_weight_axis_moves(self):
        """Both files are variable. If instancing silently failed, a design's
        light and heavy type would render as the same picture."""
        light = fonts.width("Chapters", fonts.face("ui", 60, 200))
        heavy = fonts.width("Chapters", fonts.face("ui", 60, 900))
        assert heavy > light * 1.03

    def test_one_size_is_chosen_for_all_the_labels(self):
        """Buttons set at different sizes read as broken rather than as full."""
        chosen = base.set_labels(
            ["Play", "Behind the scenes with the cast and crew"],
            family="ui",
            weight=400,
            max_width=420,
            size=34,
            min_size=18,
        )
        assert chosen.size <= 34
        assert " ".join(chosen.lines[1]) == "Behind the scenes with the cast and crew"


class TestItReachesADisc:
    """The round trip is the proof it is a menu and not a picture."""

    @pytest.mark.parametrize("key", KEYS)
    def test_the_stream_comes_back_off_the_clip(self, key, tmp_path):
        import tools.theme_menu as theme_menu
        from tests.fixtures.authoring import hdmv
        from wti_player.formats import hdmv_read

        built = theme_menu.build(tmp_path / key, theme_key=key, title="Nosferatu")
        stream = b"".join(hdmv.ts_packets(hdmv.pes_packets(built.segments, 0)))
        read = hdmv_read.read(stream)
        assert (read.width, read.height) == (1920, 1080)
        assert len(read.buttons) == len(theme_menu.DEFAULT_BUTTONS)
        assert all(button.has_three_states for button in read.buttons)
