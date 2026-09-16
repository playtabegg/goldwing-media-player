"""The bar along the bottom.

**The scrub bar spans the whole window**, above the controls rather than
wedged between them. It is the control people use most, and a disc is the
only medium that can put real chapter marks on it.

**One brass button.** Play is the thing to press; everything else is a line
drawing that lights up when the pointer is on it. A second accent would make
neither of them mean anything.

**It has three faces**, because a disc player is not always playing. Inside
a disc menu there is nothing to scrub, so the bar shows what the arrow keys
will do instead. While a disc is being read there is nothing to press at
all, and it says what it is waiting for.
"""

from __future__ import annotations

from enum import Enum
from itertools import pairwise

from PyQt6.QtCore import QPointF, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import strings
from ..engine.base import PlaybackState, Track
from . import icons, theme


class Mode(Enum):
    """What the bar is for at this moment."""

    #: Something is playing or paused, and can be scrubbed.
    PLAYBACK = "playback"
    #: A disc menu is on screen. The arrows move a highlight, not the film.
    MENU = "menu"
    #: The drive is being read. Nothing to press yet.
    READING = "reading"


class IconButton(QPushButton):
    """A control that is a drawing, not a word.

    Everything a person could press has a tooltip, because an icon-only
    control that cannot be named is a control that cannot be learned.
    """

    def __init__(
        self,
        name: str,
        tooltip: str,
        *,
        size: int = 20,
        box: int = 34,
        colour: str = theme.NEAR,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._name = name
        self._size = size
        self._colour = colour
        self.setObjectName("iconButton")
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setFixedSize(box, box)
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "QPushButton {"
            " background: transparent; border: none; border-radius: 5px;"
            " min-height: 0; max-height: none; padding: 0;"
            "}"
            f"QPushButton:hover {{ background: {theme.RAISED_HI}; }}"
            f"QPushButton:focus {{ border: 1px solid {theme.BRASS}; }}"
        )
        self._refresh()

    def set_glyph(self, name: str) -> None:
        if name != self._name:
            self._name = name
            self._refresh()

    def enterEvent(self, event) -> None:
        self._refresh(theme.BONE)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._refresh()
        super().leaveEvent(event)

    def _refresh(self, colour: str | None = None) -> None:
        self.setIcon(
            icons.icon(self._name, self._size, colour or self._colour, disabled=theme.FAINT)
        )
        self.setIconSize(icons.size_hint(self._size))


class PrimaryButton(QPushButton):
    """The one brass control. Round, because it is the only round thing here."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._glyph = "play"
        self.setObjectName("playOrb")
        self.setFixedSize(42, 42)
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Play")
        self.setAccessibleName("Play")
        self._hover = False

    def set_glyph(self, name: str, tooltip: str) -> None:
        self._glyph = name
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.update()

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        area = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        fill = theme.BRASS_HI if (self._hover and self.isEnabled()) else theme.BRASS
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(fill) if self.isEnabled() else QColor(74, 66, 48))
        painter.drawEllipse(area)
        if self.hasFocus():
            painter.setPen(QPen(QColor(theme.BONE), 1.4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(area.adjusted(-1.4, -1.4, 1.4, 1.4))
        glyph = icons.pixmap(self._glyph, 18, theme.INK)
        size = glyph.deviceIndependentSize()
        painter.drawPixmap(
            QPointF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2),
            glyph,
        )
        painter.end()


class ScrubBar(QWidget):
    """Position, and the disc's chapters, across the whole window.

    Painted rather than assembled from a QSlider because of the ticks: a
    stylesheet cannot put a mark at 41.6% of a groove, and the marks are the
    reason this control exists in this shape.
    """

    #: Where the user let go, in milliseconds.
    seek = pyqtSignal(int)
    #: Live position while dragging, so the timecode beside it keeps up.
    scrubbed = pyqtSignal(int)

    HEIGHT = 26
    GROOVE = 3
    GROOVE_HOVER = 5

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._duration_ms = 0
        self._position_ms = 0
        self._chapters: list[tuple[int, str]] = []
        self._hover_x: int | None = None
        self._dragging = False
        self._enabled = False

    # -- what the window pushes in ----------------------------------------

    def set_position(self, position_ms: int, duration_ms: int) -> None:
        changed = (position_ms, duration_ms) != (self._position_ms, self._duration_ms)
        self._position_ms = max(0, position_ms)
        self._duration_ms = max(0, duration_ms)
        self._enabled = duration_ms > 0
        if changed and not self._dragging:
            self.update()

    def set_chapters(self, chapters: list[tuple[int, str]]) -> None:
        """``(start_ms, name)`` for each chapter. Names may be empty."""
        chapters = sorted(chapters)
        if chapters != self._chapters:
            self._chapters = chapters
            self.update()

    def chapter_at(self, position_ms: int) -> str:
        name = ""
        for index, (start, title) in enumerate(self._chapters):
            if start <= position_ms:
                name = title or f"Chapter {index + 1}"
            else:
                break
        return name

    # -- painting ----------------------------------------------------------

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        hovered = self._hover_x is not None or self._dragging
        thickness = self.GROOVE_HOVER if hovered else self.GROOVE
        top = (self.height() - thickness) / 2
        width = self.width()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(232, 226, 214, 28 if self._enabled else 16))
        painter.drawRoundedRect(
            QRectF(0, top, width, thickness), thickness / 2, thickness / 2
        )

        fraction = self._fraction()
        if self._enabled and fraction > 0:
            painter.setBrush(QColor(theme.BRASS))
            painter.drawRoundedRect(
                QRectF(0, top, width * fraction, thickness), thickness / 2, thickness / 2
            )

        self._paint_ticks(painter, top, thickness, width)

        if self._enabled:
            handle = 5.5 if hovered else 4.5
            painter.setBrush(QColor(theme.BONE))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(
                QRectF(
                    width * fraction - handle,
                    self.height() / 2 - handle,
                    handle * 2,
                    handle * 2,
                )
            )
        painter.end()

    def _paint_ticks(self, painter: QPainter, top: float, thickness: float, width: int) -> None:
        """A mark per chapter, the full height of the groove.

        Skipped when they would be closer together than three pixels: at that
        density they stop reading as marks and start reading as noise.
        """
        if not self._duration_ms or len(self._chapters) < 2:
            return
        positions = [
            width * (start / self._duration_ms)
            for start, _ in self._chapters
            if 0 < start < self._duration_ms
        ]
        if not positions:
            return
        gaps = [b - a for a, b in pairwise(positions)]
        if gaps and min(gaps) < 3.0:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        played = width * self._fraction()
        for x in positions:
            painter.setBrush(
                QColor(13, 15, 20, 190) if x <= played else QColor(232, 226, 214, 78)
            )
            painter.drawRect(QRectF(x - 0.75, top, 1.5, thickness))

    def _fraction(self) -> float:
        if not self._duration_ms:
            return 0.0
        return min(1.0, max(0.0, self._position_ms / self._duration_ms))

    # -- pointer -----------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._enabled:
            self._dragging = True
            self._scrub_to(event.position().x())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self._hover_x = int(event.position().x())
        if self._dragging:
            self._scrub_to(event.position().x())
        else:
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging:
            self._dragging = False
            self.seek.emit(self._position_ms)
            self.update()
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_x = None
        self.update()
        super().leaveEvent(event)

    def _scrub_to(self, x: float) -> None:
        fraction = min(1.0, max(0.0, x / max(1, self.width())))
        self._position_ms = int(self._duration_ms * fraction)
        self.scrubbed.emit(self._position_ms)
        self.update()

    def hover_readout(self) -> tuple[int, int, str] | None:
        """``(x, milliseconds, chapter)`` under the pointer, or ``None``."""
        if self._hover_x is None or not self._enabled:
            return None
        fraction = min(1.0, max(0.0, self._hover_x / max(1, self.width())))
        at = int(self._duration_ms * fraction)
        return self._hover_x, at, self.chapter_at(at)


class HoverReadout(QWidget):
    """The time and chapter under the pointer, floating above the scrub bar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFixedHeight(24)
        self._text = ""
        self._x = 0
        self.hide()

    def show_at(self, x: int, text: str) -> None:
        self._x, self._text = x, text
        self.setVisible(bool(text))
        self.update()

    def paintEvent(self, _event) -> None:
        if not self._text:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setFont(theme.ui_font(11, weight=300))
        metrics = QFontMetrics(painter.font())
        width = metrics.horizontalAdvance(self._text) + 18
        left = min(max(0, self._x - width / 2), self.width() - width)
        box = QRectF(left, 1, width, self.height() - 4)
        painter.setPen(QPen(QColor(232, 226, 214, 30), 1))
        painter.setBrush(QColor(18, 21, 29, 236))
        painter.drawRoundedRect(box, 4, 4)
        painter.setPen(QColor(theme.BONE))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, self._text)
        painter.end()


class KeyCap(QWidget):
    """One key, drawn as a key. Used where a timeline would be a lie."""

    def __init__(self, glyph: str, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._glyph = glyph
        self._caption = caption
        metrics = QFontMetrics(theme.ui_font(11, weight=300))
        self._cap_w = max(24, metrics.horizontalAdvance(glyph) + 16)
        self._text_w = metrics.horizontalAdvance(caption)
        self.setFixedSize(self._cap_w + 8 + self._text_w, 26)

    def sizeHint(self) -> QSize:
        return QSize(self.width(), self.height())

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cap = QRectF(0, 2, self._cap_w, 22)
        painter.setPen(QPen(QColor(232, 226, 214, 38), 1))
        painter.setBrush(QColor(232, 226, 214, 12))
        painter.drawRoundedRect(cap, 4, 4)
        painter.setFont(theme.ui_font(11, weight=400))
        painter.setPen(QColor(theme.NEAR))
        painter.drawText(cap, Qt.AlignmentFlag.AlignCenter, self._glyph)
        painter.setFont(theme.ui_font(11, weight=300))
        painter.setPen(QColor(theme.MUTED))
        painter.drawText(
            QRect(self._cap_w + 8, 0, self._text_w + 2, self.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self._caption,
        )
        painter.end()


class TransportBar(QWidget):
    """Transport controls. Emits intent; the window decides what to do."""

    play_pause = pyqtSignal()
    stop = pyqtSignal()
    seek = pyqtSignal(int)
    step = pyqtSignal(int)
    top_menu = pyqtSignal()
    previous_chapter = pyqtSignal()
    next_chapter = pyqtSignal()
    volume_changed = pyqtSignal(int)
    mute_toggled = pyqtSignal()
    audio_track_chosen = pyqtSignal(int)
    subtitle_track_chosen = pyqtSignal(int)
    fullscreen = pyqtSignal()
    eject = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("transport")
        self._duration_ms = 0
        self._mode = Mode.PLAYBACK
        self._muted = False
        self._volume = 100

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._readout = HoverReadout()
        outer.addWidget(self._readout)

        self.scrub = ScrubBar()
        self.scrub.seek.connect(self.seek.emit)
        self.scrub.scrubbed.connect(self._on_scrubbed)
        outer.addWidget(self.scrub)

        self._controls = QWidget()
        row = QHBoxLayout(self._controls)
        row.setContentsMargins(14, 2, 14, 12)
        row.setSpacing(4)

        self._primary = PrimaryButton()
        self._primary.clicked.connect(self.play_pause.emit)

        self._stop = IconButton("stop", "Stop")
        self._stop.clicked.connect(self.stop.emit)
        self._back = IconButton("back", strings.SKIP_BACK)
        self._back.clicked.connect(lambda: self.step.emit(-1))
        self._forward = IconButton("forward", strings.SKIP_FORWARD)
        self._forward.clicked.connect(lambda: self.step.emit(1))
        self._previous = IconButton("previous", "Previous chapter")
        self._previous.clicked.connect(self.previous_chapter.emit)
        self._next = IconButton("next", "Next chapter")
        self._next.clicked.connect(self.next_chapter.emit)
        self._menu = IconButton("menu", strings.BACK_TO_MENU)
        self._menu.clicked.connect(self.top_menu.emit)

        self._elapsed = QLabel("0:00")
        self._elapsed.setObjectName("timecode")
        self._elapsed.setFont(theme.tabular(theme.ui_font(12)))
        self._chapter = QLabel("")
        self._chapter.setObjectName("note")
        self._remaining = QLabel("0:00")
        self._remaining.setObjectName("timecodeMuted")
        self._remaining.setFont(theme.tabular(theme.ui_font(12)))
        self._remaining.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        row.addWidget(self._previous)
        row.addWidget(self._back)
        row.addSpacing(4)
        row.addWidget(self._primary)
        row.addSpacing(4)
        row.addWidget(self._forward)
        row.addWidget(self._next)
        row.addSpacing(8)
        row.addWidget(self._stop)
        row.addSpacing(12)
        row.addWidget(self._elapsed)
        row.addSpacing(8)
        row.addWidget(self._chapter, 1)

        # The keycaps live in the same row and swap in for the timecodes when
        # a disc menu is up. Same bar, different job.
        self._keys = QWidget()
        keys = QHBoxLayout(self._keys)
        keys.setContentsMargins(0, 0, 0, 0)
        keys.setSpacing(16)
        for glyph, caption in (
            ("← ↑ ↓ →", "move"),
            ("Enter", "choose"),
            ("Esc", "leave the menu"),
        ):
            keys.addWidget(KeyCap(glyph, caption))
        keys.addStretch(1)
        self._keys.hide()
        row.addWidget(self._keys, 1)

        row.addWidget(self._remaining)
        row.addSpacing(6)
        row.addWidget(self._menu)

        self._audio = QComboBox()
        self._audio.setToolTip(strings.AUDIO_TRACK)
        self._audio.activated.connect(self._on_audio)
        self._audio.hide()
        row.addWidget(self._audio)

        self._subtitles = QComboBox()
        self._subtitles.setToolTip(strings.SUBTITLES)
        self._subtitles.activated.connect(self._on_subtitles)
        self._subtitles.hide()
        row.addWidget(self._subtitles)

        self._volume_button = IconButton("volume", "Mute")
        self._volume_button.clicked.connect(self.mute_toggled.emit)
        row.addWidget(self._volume_button)

        self._volume_bar = VolumeBar()
        self._volume_bar.changed.connect(self._on_volume)
        row.addWidget(self._volume_bar)

        self._full = IconButton("fullscreen", strings.FULL_SCREEN)
        self._full.clicked.connect(self.fullscreen.emit)
        row.addWidget(self._full)

        outer.addWidget(self._controls)

        self._waiting = QLabel("")
        self._waiting.setObjectName("note")
        self._waiting.setContentsMargins(18, 12, 18, 16)
        self._waiting.hide()
        outer.addWidget(self._waiting)

        self._tick = None
        self.set_mode(Mode.PLAYBACK)

    # -- what the window pushes in ----------------------------------------

    def set_mode(self, mode: Mode, *, waiting_for: str = "") -> None:
        self._mode = mode
        playback = mode is Mode.PLAYBACK
        self.scrub.setVisible(playback)
        self._controls.setVisible(mode is not Mode.READING)
        self._waiting.setVisible(mode is Mode.READING)
        if mode is Mode.READING:
            self._waiting.setText(waiting_for or strings.READING_DISC)
            self._readout.hide()
            return

        in_menu = mode is Mode.MENU
        self._keys.setVisible(in_menu)
        for widget in (self._elapsed, self._chapter, self._remaining):
            widget.setVisible(not in_menu)
        for widget in (self._back, self._forward, self._previous, self._next):
            widget.setEnabled(not in_menu)
        for widget in (self._audio, self._subtitles):
            # Inside a disc menu there is no film to pick a track for, and a
            # dropdown that changes nothing is a control that lies.
            widget.setVisible(not in_menu and widget.count() > 1)
        if in_menu:
            self._readout.hide()

    def set_state(self, state: PlaybackState) -> None:
        playing = state is PlaybackState.PLAYING
        self._primary.set_glyph("pause" if playing else "play", "Pause" if playing else "Play")

    def set_position(self, position_ms: int, duration_ms: int) -> None:
        self._duration_ms = duration_ms
        self.scrub.set_position(position_ms, duration_ms)
        self._elapsed.setText(strings.timecode(position_ms))
        self._remaining.setText(
            "-" + strings.timecode(max(0, duration_ms - position_ms)) if duration_ms else ""
        )
        self._chapter.setText(self.scrub.chapter_at(position_ms))
        self._sync_readout()

    def set_chapters(self, chapters: list[tuple[int, str]]) -> None:
        self.scrub.set_chapters(chapters)
        self.set_skip_available(len(chapters) > 1)

    @property
    def mode(self) -> Mode:
        return self._mode

    def set_skip_available(self, available: bool) -> None:
        """Show or hide the two skip buttons.

        Chapters are the usual reason to have them, but not the only one: an
        audio CD has tracks and no chapters at all, and hiding the skip
        buttons on the one kind of disc where skipping is the whole point
        left the track list as the only way to reach track two.
        """
        self._previous.setVisible(available)
        self._next.setVisible(available)

    def set_menu_available(self, available: bool) -> None:
        self._menu.setEnabled(available)

    def set_tracks(self, audio: list[Track], subtitles: list[Track]) -> None:
        self._fill(self._audio, audio, strings.AUDIO)
        self._fill(self._subtitles, subtitles, strings.SUBTITLES)

    @staticmethod
    def _fill(box: QComboBox, tracks: list[Track], kind: str = "") -> None:
        box.clear()
        for track in tracks:
            # A control reading just "Off" says nothing about what is off.
            name = track.name
            if kind and name.strip().lower() in ("off", "disable", "disabled"):
                name = kind + " off"
            box.addItem(name, track.identifier)
        # One track is not a choice, so it is not shown as one.
        box.setVisible(len(tracks) > 1)

    def set_volume(self, percent: int) -> None:
        self._volume = percent
        self._volume_bar.set_value(percent)
        self._muted = percent == 0
        self._volume_button.set_glyph("muted" if self._muted else "volume")
        action = "Unmute" if self._muted else "Mute"
        self._volume_button.setToolTip(action)
        self._volume_button.setAccessibleName(action)

    def set_fullscreen(self, on: bool) -> None:
        self._full.set_glyph("restore" if on else "fullscreen")
        self._full.setToolTip(strings.LEAVE_FULL_SCREEN if on else strings.FULL_SCREEN)

    # -- internals ---------------------------------------------------------

    def _on_scrubbed(self, position_ms: int) -> None:
        self._elapsed.setText(strings.timecode(position_ms))
        self._remaining.setText(
            "-" + strings.timecode(max(0, self._duration_ms - position_ms))
            if self._duration_ms
            else ""
        )
        self._chapter.setText(self.scrub.chapter_at(position_ms))

    def _sync_readout(self) -> None:
        if self._mode is not Mode.PLAYBACK:
            self._readout.hide()
            return
        hover = self.scrub.hover_readout()
        if hover is None:
            self._readout.hide()
            return
        x, at, chapter = hover
        text = strings.timecode(at)
        if chapter:
            text += "   " + chapter
        self._readout.show_at(x, text)

    def mouseMoveEvent(self, event) -> None:
        self._sync_readout()
        super().mouseMoveEvent(event)

    def enterEvent(self, event) -> None:
        self._sync_readout()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._readout.hide()
        super().leaveEvent(event)

    def _on_volume(self, percent: int) -> None:
        self.volume_changed.emit(percent)

    def _on_audio(self, index: int) -> None:
        self.audio_track_chosen.emit(int(self._audio.itemData(index)))

    def _on_subtitles(self, index: int) -> None:
        self.subtitle_track_chosen.emit(int(self._subtitles.itemData(index)))


class VolumeBar(QWidget):
    """Volume, as a short bar. Same drawing language as the scrub bar."""

    changed = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(74, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Volume")
        self._value = 100
        self._hover = False

    def set_value(self, percent: int) -> None:
        percent = max(0, min(100, percent))
        if percent != self._value:
            self._value = percent
            self.update()

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._set_from(event.position().x())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._set_from(event.position().x())
        super().mouseMoveEvent(event)

    def _set_from(self, x: float) -> None:
        percent = round(100 * min(1.0, max(0.0, x / max(1, self.width()))))
        self.set_value(percent)
        self.changed.emit(percent)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        thickness = 4.0 if self._hover else 3.0
        top = (self.height() - thickness) / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(232, 226, 214, 28))
        painter.drawRoundedRect(
            QRectF(0, top, self.width(), thickness), thickness / 2, thickness / 2
        )
        filled = self.width() * self._value / 100
        if filled > 0:
            painter.setBrush(QColor(theme.MUTED if not self._hover else theme.NEAR))
            painter.drawRoundedRect(QRectF(0, top, filled, thickness), thickness / 2, thickness / 2)
        painter.end()

    def sizeHint(self) -> QSize:
        return QSize(74, 30)


__all__ = ["IconButton", "KeyCap", "Mode", "PrimaryButton", "ScrubBar", "TransportBar", "VolumeBar"]
