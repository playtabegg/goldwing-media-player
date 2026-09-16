"""The look: typefaces, icons, artwork, and the controls they are used in.

These are not pixel comparisons — a screenshot test on a program that is
still being designed fails every time somebody moves something 2px and tells
you nothing. They check the things that can silently break: a font file that
did not ship, an icon that draws nothing, a picture off a disc that is not a
picture, and a control that reports the wrong number back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QImage

from wti_player.engine.base import PlaybackState, Track
from wti_player.ui import artwork, icons, theme
from wti_player.ui.transport import Mode, ScrubBar, TransportBar, VolumeBar


def ink(image: QImage) -> int:
    """How many pixels the drawing actually touched."""
    return sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 10
    )


class TestTypefaces:
    def test_the_gold_bird_is_bundled(self):
        assert theme.MARK_FILE.is_file()

    def test_both_families_are_bundled(self):
        names = {path.name for path in theme.FONT_DIR.glob("*.ttf")}
        assert "Outfit.ttf" in names
        assert "PlayfairDisplay-Italic.ttf" in names

    def test_the_licence_ships_with_them(self):
        # The OFL permits bundling and asks for exactly one thing in return.
        licences = list(theme.FONT_DIR.glob("OFL*.txt"))
        assert licences, "the fonts ship without the licence they are under"
        for licence in licences:
            assert "SIL OPEN FONT LICENSE" in licence.read_text(encoding="utf-8").upper()

    def test_they_load(self, qapp):
        report = theme.load_fonts()
        assert report.complete, report.describe()
        assert "Outfit" in report.families
        assert "Playfair Display" in report.families

    def test_the_weight_axis_actually_moves(self, qapp):
        """A variable font Qt cannot instance renders every weight the same."""
        theme.load_fonts()
        widths = {
            weight: QFontMetrics(theme.ui_font(40, weight=weight)).boundingRect("Weight").width()
            for weight in (200, 400, 600)
        }
        assert len(set(widths.values())) > 1, widths

    def test_interface_text_never_goes_below_the_readable_size(self, qapp):
        """Outfit's word space rounds to nothing below 12px.

        The rule this guards: sentence-case interface text sits at
        ``MIN_TEXT_PX`` or above. Tracked-out uppercase may go smaller,
        because the tracking does the separating there.
        """
        theme.load_fonts()
        metrics = QFontMetrics(theme.ui_font(theme.MIN_TEXT_PX, weight=300))
        assert metrics.horizontalAdvance("3 chapters") > metrics.horizontalAdvance("3chapters")


class TestIcons:
    def test_every_icon_draws_something(self, qapp):
        for name in icons.names():
            drawn = icons.pixmap(name, 20, theme.BONE).toImage()
            assert ink(drawn) > 12, f"{name} draws nothing"

    def test_an_unknown_icon_is_an_error_rather_than_a_blank(self, qapp):
        with pytest.raises(KeyError):
            icons.pixmap("teapot", 16, theme.BONE)

    def test_colour_is_honoured(self, qapp):
        gold = icons.pixmap("play", 24, theme.BRASS).toImage()
        bone = icons.pixmap("play", 24, theme.BONE).toImage()
        assert gold.pixelColor(12, 12) != bone.pixelColor(12, 12)

    def test_asking_twice_returns_the_same_object(self, qapp):
        assert icons.pixmap("play", 18, theme.BONE) is icons.pixmap("play", 18, theme.BONE)


class TestArtwork:
    def test_a_disc_with_no_art_still_draws_a_disc(self, qapp):
        face = artwork.DiscFace(size=160)
        face.set_face(None, "Nocturnes")
        drawn = face.grab().toImage()
        # The rim is painted and the centre hole is not.
        assert drawn.pixelColor(80, 8).alpha() == 255
        assert drawn.pixelColor(80, 80) == QColor(theme.INK)

    def test_the_same_album_is_always_the_same_colour(self):
        assert artwork.tint_for("Nocturnes") == artwork.tint_for("Nocturnes")

    def test_different_albums_are_different_colours(self):
        assert artwork.tint_for("Nocturnes") != artwork.tint_for("Preludes")

    def test_a_generated_tint_is_never_bright(self):
        """A drawn disc belongs to this palette. It never becomes the subject."""
        for name in ("Nocturnes", "The General", "", "x" * 200, "🎵"):
            colour = artwork.tint_for(name)
            assert colour.valueF() < 0.32, name
            assert colour.saturationF() < 0.34, name

    def test_the_resting_disc_is_not_tinted_like_an_album(self):
        assert artwork.tint_for(artwork.NEUTRAL).saturationF() <= 0.12

    def test_real_art_is_loaded(self, qapp, tmp_path):
        source = QImage(40, 40, QImage.Format.Format_RGB32)
        source.fill(QColor("#c04030"))
        path = tmp_path / "cover.jpg"
        assert source.save(str(path), "JPEG", 90)

        artwork.forget()
        loaded = artwork.load(path)
        assert loaded is not None
        assert loaded.width() == 40

    def test_a_file_that_is_not_a_picture_reads_as_no_picture(self, qapp, tmp_path):
        path = tmp_path / "cover.jpg"
        path.write_bytes(b"this is not a JPEG, whatever it is called")
        artwork.forget()
        assert artwork.load(path) is None

    def test_an_enormous_scan_is_scaled_on_the_way_in(self, qapp, tmp_path):
        source = QImage(3000, 2000, QImage.Format.Format_RGB32)
        source.fill(QColor("#203040"))
        path = tmp_path / "huge.png"
        assert source.save(str(path))

        artwork.forget()
        loaded = artwork.load(path, max_edge=400)
        assert loaded is not None
        assert max(loaded.width(), loaded.height()) <= 400

    def test_missing_art_is_not_an_error(self, qapp):
        assert artwork.load(None) is None
        assert artwork.load(Path("nowhere") / "nothing.jpg") is None

    def test_forgetting_one_disc_leaves_the_others(self, qapp, tmp_path):
        source = QImage(8, 8, QImage.Format.Format_RGB32)
        source.fill(QColor("#ffffff"))
        first, second = tmp_path / "a.png", tmp_path / "b.png"
        source.save(str(first))
        source.save(str(second))
        artwork.forget()
        artwork.load(first)
        artwork.load(second)

        artwork.forget(first)
        assert not any(key[0] == str(first) for key in artwork._cache)
        assert any(key[0] == str(second) for key in artwork._cache)


class TestScrubBar:
    def test_a_chapter_is_named_from_the_position(self, qapp):
        bar = ScrubBar()
        bar.set_chapters([(0, "Opening"), (60_000, "The audition"), (120_000, "Curtain")])
        assert bar.chapter_at(0) == "Opening"
        assert bar.chapter_at(59_999) == "Opening"
        assert bar.chapter_at(60_000) == "The audition"
        assert bar.chapter_at(500_000) == "Curtain"

    def test_a_chapter_with_no_name_is_numbered(self, qapp):
        bar = ScrubBar()
        bar.set_chapters([(0, ""), (60_000, "")])
        assert bar.chapter_at(60_000) == "Chapter 2"

    def test_chapters_out_of_order_are_sorted(self, qapp):
        bar = ScrubBar()
        bar.set_chapters([(60_000, "Second"), (0, "First")])
        assert bar.chapter_at(10) == "First"

    def test_a_disc_with_no_chapters_names_nothing(self, qapp):
        assert ScrubBar().chapter_at(1000) == ""

    def test_dragging_reports_where_it_was_let_go(self, qapp):
        bar = ScrubBar()
        bar.resize(400, ScrubBar.HEIGHT)
        bar.set_position(0, 100_000)

        seen: list[int] = []
        bar.seek.connect(seen.append)
        bar._dragging = True
        bar._scrub_to(200)          # halfway across 400px
        bar.mouseReleaseEvent(_release())

        assert seen == [50_000]

    def test_a_disc_with_no_length_cannot_be_scrubbed(self, qapp):
        bar = ScrubBar()
        bar.resize(400, ScrubBar.HEIGHT)
        bar.set_position(0, 0)
        assert bar.hover_readout() is None

    def test_the_readout_says_the_time_and_the_chapter(self, qapp):
        bar = ScrubBar()
        bar.resize(400, ScrubBar.HEIGHT)
        bar.set_position(0, 100_000)
        bar.set_chapters([(0, "Opening"), (50_000, "The audition")])
        bar._hover_x = 300

        readout = bar.hover_readout()
        assert readout is not None
        x, at, chapter = readout
        assert x == 300
        assert at == 75_000
        assert chapter == "The audition"


class TestVolumeBar:
    def test_a_click_reports_a_percentage(self, qapp):
        bar = VolumeBar()
        seen: list[int] = []
        bar.changed.connect(seen.append)
        bar._set_from(bar.width() / 4)
        assert seen == [25]

    def test_it_cannot_go_past_either_end(self, qapp):
        bar = VolumeBar()
        seen: list[int] = []
        bar.changed.connect(seen.append)
        bar._set_from(-40)
        bar._set_from(9999)
        assert seen == [0, 100]


class TestTransportModes:
    def test_a_disc_menu_hides_the_timeline(self, qapp):
        bar = TransportBar()
        bar.set_mode(Mode.MENU)
        assert not bar.scrub.isVisible()

    def test_reading_a_disc_shows_neither_controls_nor_timeline(self, qapp):
        bar = TransportBar()
        bar.set_mode(Mode.READING)
        assert not bar.scrub.isVisible()
        assert not bar._controls.isVisible()

    def test_playing_shows_both(self, qapp):
        bar = TransportBar()
        bar.show()
        bar.set_mode(Mode.PLAYBACK)
        assert bar.scrub.isVisible()
        assert bar._controls.isVisible()
        bar.hide()

    def test_the_primary_button_says_what_it_will_do(self, qapp):
        bar = TransportBar()
        bar.set_state(PlaybackState.PLAYING)
        assert bar._primary.toolTip() == "Pause"
        bar.set_state(PlaybackState.PAUSED)
        assert bar._primary.toolTip() == "Play"

    def test_one_track_is_not_offered_as_a_choice(self, qapp):
        bar = TransportBar()
        bar.show()
        bar.set_tracks([Track(0, "English")], [Track(-1, "Off"), Track(1, "English")])
        assert not bar._audio.isVisible()
        assert bar._subtitles.isVisible()
        bar.hide()

    def test_off_says_what_is_off(self, qapp):
        bar = TransportBar()
        bar.set_tracks([], [Track(-1, "Off"), Track(1, "English")])
        assert bar._subtitles.itemText(0) == "Subtitles off"

    def test_chapter_controls_appear_only_with_chapters(self, qapp):
        bar = TransportBar()
        bar.show()
        bar.set_chapters([])
        assert not bar._next.isVisible()
        bar.set_chapters([(0, "One"), (1000, "Two")])
        assert bar._next.isVisible()
        bar.hide()

    def test_every_icon_control_can_be_named(self, qapp):
        """An icon nobody can name is a control nobody can learn."""
        bar = TransportBar()
        for control in (
            bar._stop, bar._back, bar._forward, bar._previous,
            bar._next, bar._menu, bar._volume_button, bar._full,
        ):
            assert control.toolTip()
            assert control.accessibleName()


def _release():
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QMouseEvent

    return QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(QPoint(0, 0)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
