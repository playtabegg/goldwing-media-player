"""The panels the main window switches between.

Each one is a plain widget that knows nothing about drives or the engine —
the window wires them up. That keeps them cheap to look at and cheap to
change, which for the bits a person actually sees matters more than for the
bits underneath.

The shape they share: the disc is the subject. Its own name is set as a
name, with its artwork beside it where it has any, and the list of what is
on it reads as titles rather than as numbers. Everything else is smaller and
further down.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QModelIndex, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPalette
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import shelf, strings
from ..optical import edition as disc_edition
from ..optical.identify import DiscProfile
from . import artwork, icons, theme
from .transport import IconButton

#: Item data slots on a title row. The delegate reads these; nothing else does.
ROLE_NUMBER = int(Qt.ItemDataRole.UserRole)
ROLE_DETAIL = ROLE_NUMBER + 1
ROLE_DURATION = ROLE_NUMBER + 2
ROLE_PLAYING = ROLE_NUMBER + 3
ROLE_INDEX = ROLE_NUMBER + 4


def section_label(text: str) -> QLabel:
    """A small tracked-out heading. The only uppercase in the program."""
    label = QLabel(text.upper())
    label.setObjectName("sectionLabel")
    label.setFont(theme.ui_font(10, weight=500, tracking=20))
    return label


def rule() -> QFrame:
    line = QFrame()
    line.setObjectName("rule")
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {theme.HAIRLINE};")
    return line


class VideoSurface(QWidget):
    """The window libvlc draws into.

    It is deliberately empty of Qt painting: once the engine has the window
    handle, anything Qt draws here fights with the video. Everything on top —
    the transport bar, the banner — is a sibling widget, not a child.
    """

    clicked = pyqtSignal()
    double_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stage")
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0))
        self.setPalette(palette)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(320, 180)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def native_handle(self) -> int:
        return int(self.winId())

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class TitleDelegate(QStyledItemDelegate):
    """One row of a disc's contents.

    Two lines and a duration: what the thing is called, what it is made of,
    and how long it runs — the duration right-aligned in tabular figures so a
    column of them lines up and can be compared at a glance.

    The row that is playing is marked with a brass rule down its left edge
    and the title set in bone rather than a shade under it. No icon, no
    badge: at this size a marker that has to be recognised is worse than one
    that is brighter.
    """

    HEIGHT = 46
    PAD_X = 12
    ORDINAL_W = 30

    def sizeHint(self, option, index: QModelIndex) -> QSize:
        detail = index.data(ROLE_DETAIL)
        return QSize(option.rect.width(), self.HEIGHT if detail else 34)

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = option.rect
        playing = bool(index.data(ROLE_PLAYING))
        selected = bool(option.state & option.state.__class__.State_Selected)
        hovered = bool(option.state & option.state.__class__.State_MouseOver)

        if playing:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(201, 169, 97, 26))
            painter.drawRoundedRect(rect.adjusted(0, 1, 0, -1), 5, 5)
            painter.setBrush(QColor(theme.BRASS))
            painter.drawRoundedRect(QRect(rect.left(), rect.top() + 6, 2, rect.height() - 12), 1, 1)
        elif selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(232, 226, 214, 20))
            painter.drawRoundedRect(rect.adjusted(0, 1, 0, -1), 5, 5)
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(232, 226, 214, 10))
            painter.drawRoundedRect(rect.adjusted(0, 1, 0, -1), 5, 5)

        duration = index.data(ROLE_DURATION) or ""
        detail = index.data(ROLE_DETAIL) or ""
        title = index.data(Qt.ItemDataRole.DisplayRole) or ""
        ordinal = index.data(ROLE_INDEX) or ""

        duration_font = theme.tabular(theme.ui_font(12))
        duration_width = QFontMetrics(duration_font).horizontalAdvance(duration) if duration else 0

        left = rect.left() + self.PAD_X
        right = rect.right() - self.PAD_X

        if ordinal and playing:
            glyph = icons.pixmap("bars", 13, theme.BRASS)
            painter.drawPixmap(
                left, rect.top() + (rect.height() - glyph.height()) // 2, glyph
            )
            left += self.ORDINAL_W
        elif ordinal:
            painter.setFont(theme.tabular(theme.ui_font(12, weight=300)))
            painter.setPen(QColor(theme.MUTED if playing else theme.FAINT))
            painter.drawText(
                QRect(left, rect.top(), self.ORDINAL_W, rect.height()),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                str(ordinal),
            )
            left += self.ORDINAL_W
        text_right = right - (duration_width + 14 if duration_width else 0)

        title_font = theme.ui_font(13, weight=400 if playing else 300)
        painter.setFont(title_font)
        painter.setPen(QColor(theme.BONE if playing or selected else theme.NEAR))
        title_metrics = QFontMetrics(title_font)
        title_rect = QRect(
            left, rect.top() + (8 if detail else 0), max(20, text_right - left),
            title_metrics.height() if detail else rect.height(),
        )
        painter.drawText(
            title_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            title_metrics.elidedText(str(title), Qt.TextElideMode.ElideRight, title_rect.width()),
        )

        if detail:
            detail_font = theme.ui_font(theme.MIN_TEXT_PX, weight=300)
            painter.setFont(detail_font)
            painter.setPen(QColor(theme.BRASS_DIM if playing else theme.DIM))
            detail_metrics = QFontMetrics(detail_font)
            detail_rect = QRect(
                left, title_rect.bottom() + 1, max(20, text_right - left), detail_metrics.height()
            )
            painter.drawText(
                detail_rect,
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                detail_metrics.elidedText(
                    str(detail), Qt.TextElideMode.ElideRight, detail_rect.width()
                ),
            )

        if duration:
            painter.setFont(duration_font)
            painter.setPen(QColor(theme.MUTED if playing else theme.DIM))
            painter.drawText(
                QRect(right - duration_width, rect.top(), duration_width, rect.height()),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                duration,
            )

        painter.restore()


class DiscHeader(QWidget):
    """The disc's name, who made it, and its cover.

    The subject of the whole window. A film's name is set as a name, which
    is the change that stops this looking like a utility.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)

        self.cover = artwork.CoverPlate(width=92)
        self.cover.hide()
        row.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignTop)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        self.kind = section_label("")
        column.addWidget(self.kind)

        self.name = QLabel("")
        self.name.setObjectName("discName")
        self.name.setFont(theme.display_font(31))
        self.name.setWordWrap(True)
        column.addWidget(self.name)

        self.by = QLabel("")
        self.by.setObjectName("discBy")
        self.by.setWordWrap(True)
        self.by.hide()
        column.addWidget(self.by)

        self.facts = QLabel("")
        self.facts.setObjectName("note")
        self.facts.setWordWrap(True)
        self.facts.hide()
        column.addWidget(self.facts)

        row.addLayout(column, 1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

    @staticmethod
    def _name_size(name: str) -> int:
        """Long names are set smaller. A title should not need four lines."""
        length = len(name)
        if length <= 22:
            return 31
        if length <= 40:
            return 27
        return 23

    def show_disc(self, profile: DiscProfile) -> None:
        self.kind.setText(strings.KIND_NAMES.get(profile.kind.value, "Disc").upper())
        name = profile.display_name
        # Playfair is for a name a person chose. Everything else — a volume
        # label, a folder — is set in the interface face.
        chosen = profile.meta is not None and bool(profile.meta.title)
        self.name.setObjectName("discName" if chosen else "discLabel")
        font = (
            theme.display_font(self._name_size(name))
            if chosen
            else theme.ui_font(25, weight=300)
        )
        font.setItalic(chosen)
        self.name.setFont(font)
        self.name.style().unpolish(self.name)
        self.name.style().polish(self.name)
        self.name.setText(name)

        by: list[str] = []
        facts: list[str] = []
        meta = profile.meta
        if meta is not None:
            if meta.author:
                by.append(meta.author)
            if meta.year:
                by.append(meta.year)
            if meta.movie is not None:
                if meta.movie.runtime_minutes:
                    facts.append(f"{meta.movie.runtime_minutes} min")
                # The factory writes a ratio, never a word: its shape list
                # once ended in "other" and an Academy-ratio film (1.37:1)
                # reached the disc as that word. The list was widened on
                # 29 Aug 2026 and the schema now refuses anything that is
                # not a ratio; the guard stays for a disc built before that.
                if meta.movie.aspect_ratio and meta.movie.aspect_ratio != "other":
                    facts.append(meta.movie.aspect_ratio)
                for label in meta.movie.audio_tracks:
                    facts.append(label)
                if meta.movie.rating_text:
                    facts.append(meta.movie.rating_text)
        # L4 (30 Aug 2026): the edition record, on every kind of disc that
        # carries one, and "signed by We The Indies" only when it verifies.
        record = disc_edition.read(profile.root)
        if record is not None and record.line:
            facts.append(record.line)
            if record.signed_by_us:
                facts.append(shelf.SIGNED_BY_US)
        self.by.setText(" · ".join(by))
        self.by.setVisible(bool(by))
        self.facts.setText(" · ".join(facts))
        self.facts.setVisible(bool(facts))

        cover = profile.art.cover
        self.cover.setVisible(cover is not None)
        if cover is not None:
            self.cover.set_cover(cover, profile.display_name)


class WelcomeView(QWidget):
    """What the Player shows with nothing in the drive."""

    open_folder = pyqtSignal()
    open_image = pyqtSignal()
    open_drive = pyqtSignal(str)
    #: W2: a copy on the shelf, by its root; and the button that adds one.
    open_shelf_entry = pyqtSignal(str)
    add_to_shelf = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        across = QHBoxLayout(self)
        across.setContentsMargins(theme.EDGE, theme.EDGE, theme.EDGE, theme.EDGE)
        across.setSpacing(0)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch(2)

        column = QVBoxLayout()
        column.setSpacing(0)
        column.setContentsMargins(0, 0, 0, 0)

        title = QLabel(strings.WELCOME_TITLE)
        title.setObjectName("discNameLarge")
        title.setFont(theme.display_font(44))
        column.addWidget(title)

        body = QLabel(strings.WELCOME_BODY)
        body.setObjectName("body")
        body.setWordWrap(True)
        body.setMaximumWidth(560)
        body.setContentsMargins(0, 12, 0, 0)
        column.addWidget(body)

        promise = QLabel(strings.WELCOME_PROMISE)
        promise.setObjectName("promise")
        promise.setWordWrap(True)
        promise.setMaximumWidth(560)
        promise.setContentsMargins(0, 10, 0, 0)
        column.addWidget(promise)

        column.addSpacing(30)
        self._drives_label = section_label("Drives")
        column.addWidget(self._drives_label)
        column.addSpacing(10)

        self._drives = QVBoxLayout()
        self._drives.setSpacing(2)
        self._drives.setContentsMargins(0, 0, 0, 0)
        column.addLayout(self._drives)

        # W2: the shelf, under the drives. Local copies of discs, read from
        # their own documents each time this screen shows.
        column.addSpacing(26)
        self._shelf_label = section_label(strings.SHELF_TITLE)
        column.addWidget(self._shelf_label)
        column.addSpacing(10)
        self._shelf = QVBoxLayout()
        self._shelf.setSpacing(2)
        self._shelf.setContentsMargins(0, 0, 0, 0)
        column.addLayout(self._shelf)
        self.set_shelf([])

        column.addSpacing(26)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        folder = QPushButton(strings.OPEN_FOLDER)
        folder.setIcon(icons.icon("folder", 16, theme.MUTED))
        folder.clicked.connect(self.open_folder.emit)
        image = QPushButton(strings.OPEN_IMAGE)
        image.setIcon(icons.icon("image", 16, theme.MUTED))
        image.clicked.connect(self.open_image.emit)
        shelf = QPushButton(strings.ADD_TO_SHELF)
        shelf.setIcon(icons.icon("disc", 16, theme.MUTED))
        shelf.setToolTip(strings.ADD_TO_SHELF_TIP)
        shelf.clicked.connect(self.add_to_shelf.emit)
        buttons.addWidget(folder)
        buttons.addWidget(image)
        buttons.addWidget(shelf)
        buttons.addStretch(1)
        column.addLayout(buttons)

        layout.addLayout(column)
        layout.addStretch(3)
        across.addLayout(layout, 3)

        # An empty drive is still a disc player, and the shape says so before
        # the words do. At this opacity it never competes with them.
        self._resting = artwork.DiscFace(size=380)
        self._resting.set_face(None, artwork.NEUTRAL)
        effect = QGraphicsOpacityEffect(self._resting)
        effect.setOpacity(0.22)
        self._resting.setGraphicsEffect(effect)
        across.addWidget(self._resting, 2, Qt.AlignmentFlag.AlignCenter)

    def set_drives(self, drives: list) -> None:
        """Redraw the drive list. One row per drive; the ones with a disc lead."""
        while self._drives.count():
            item = self._drives.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not drives:
            empty = QLabel(strings.NO_DRIVE)
            empty.setObjectName("note")
            self._drives.addWidget(empty)
            return

        for drive in sorted(drives, key=lambda d: not d.has_media):
            self._drives.addWidget(_DriveRow(drive, self.open_drive))

    def set_shelf(self, entries: list) -> None:
        """Redraw the shelf: films, then albums, then games, as ``shelf.scan`` orders them."""
        while self._shelf.count():
            item = self._shelf.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Out of the tree now, not on the next tick: a deferred delete
                # left the empty note painted under the first rows.
                widget.setParent(None)
                widget.deleteLater()
        if not entries:
            empty = QLabel(strings.SHELF_EMPTY)
            empty.setObjectName("note")
            empty.setWordWrap(True)
            empty.setMaximumWidth(520)
            self._shelf.addWidget(empty)
            return
        for entry in entries:
            self._shelf.addWidget(_ShelfRow(entry, self.open_shelf_entry))


class _ShelfRow(QWidget):
    """One copy on the shelf: its title, then what it is and whose. Pressable."""

    def __init__(self, entry, signal, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hover = False
        self._title = entry.title
        self._line = entry.describe()
        self._root = str(entry.root)
        self._kind = entry.kind
        self._signal = signal
        self.setFixedHeight(44)
        self.setMaximumWidth(520)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(self._root)
        self.setAccessibleName(f"{self._title}, {self._line}")

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._signal.emit(self._root)
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._hover:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(232, 226, 214, 12))
            painter.drawRoundedRect(self.rect().adjusted(-8, 0, 8, 0), 5, 5)
        glyph_name = "menu" if self._kind == "game" else "disc"
        glyph = icons.pixmap(glyph_name, 17, theme.BRASS)
        painter.drawPixmap(0, 6, glyph)
        painter.setFont(theme.ui_font(13, weight=400))
        painter.setPen(QColor(theme.BONE))
        painter.drawText(
            QRect(28, 2, self.width() - 28, 20),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self._title,
        )
        painter.setFont(theme.ui_font(11, weight=300))
        painter.setPen(QColor(theme.MUTED))
        painter.drawText(
            QRect(28, 22, self.width() - 28, 18),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self._line,
        )
        painter.end()


class _DriveRow(QWidget):
    """One drive. Pressable when it has something in it, quiet when it does not."""

    def __init__(self, drive, signal, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._live = bool(drive.has_media)
        self._hover = False
        self._text = drive.describe()
        self._mount = drive.mount
        self._signal = signal
        self.setFixedHeight(38)
        self.setMaximumWidth(520)
        if self._live:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(self._text if self._live else strings.DRIVE_EMPTY)

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._live and event.button() == Qt.MouseButton.LeftButton:
            self._signal.emit(self._mount)
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._live and self._hover:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(232, 226, 214, 12))
            painter.drawRoundedRect(self.rect().adjusted(-8, 0, 8, 0), 5, 5)

        colour = theme.BONE if self._live else theme.FAINT
        glyph = icons.pixmap("disc", 17, theme.BRASS if self._live else theme.FAINT)
        painter.drawPixmap(0, (self.height() - glyph.height()) // 2, glyph)

        painter.setFont(theme.ui_font(13, weight=300))
        painter.setPen(QColor(colour))
        painter.drawText(
            QRect(28, 0, self.width() - 28, self.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self._text,
        )
        painter.end()


class TitleListView(QWidget):
    """A disc, its contents, and one button that starts the main thing on it."""

    play_title = pyqtSignal(int)
    play_main_feature = pyqtSignal()
    open_menu = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.PANEL_EDGE, theme.PANEL_EDGE, theme.PANEL_EDGE, theme.PANEL_EDGE
        )
        layout.setSpacing(0)

        self.header = DiscHeader()
        layout.addWidget(self.header)
        layout.addSpacing(24)

        self._note = QLabel("")
        self._note.setObjectName("note")
        self._note.setWordWrap(True)
        self._note.hide()
        layout.addWidget(self._note)
        self._note_gap = 14

        self._section = section_label(strings.ON_THIS_DISC)
        layout.addWidget(self._section)
        layout.addSpacing(8)

        self._list = QListWidget()
        self._list.setItemDelegate(TitleDelegate(self._list))
        self._list.setMouseTracking(True)
        self._list.setSpacing(0)
        self._list.setUniformItemSizes(False)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.itemActivated.connect(self._on_activated)
        self._list.itemClicked.connect(self._on_activated)
        layout.addWidget(self._list, 1)

        layout.addSpacing(10)
        self._extras_section = section_label(strings.EXTRAS)
        self._extras_section.hide()
        layout.addWidget(self._extras_section)
        layout.addSpacing(6)
        self._extras = QLabel("")
        self._extras.setObjectName("note")
        self._extras.setWordWrap(True)
        self._extras.hide()
        layout.addWidget(self._extras)

        layout.addSpacing(18)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._feature_button = QPushButton(strings.PLAY_MAIN_FEATURE)
        self._feature_button.setObjectName("primary")
        self._feature_button.clicked.connect(self.play_main_feature.emit)
        self._menu_button = QPushButton(strings.BACK_TO_MENU)
        self._menu_button.setObjectName("compact")
        self._menu_button.clicked.connect(self.open_menu.emit)
        buttons.addWidget(self._feature_button, 1)
        buttons.addWidget(self._menu_button)
        layout.addLayout(buttons)

        self._small_print = QLabel("")
        self._small_print.setObjectName("smallPrint")
        self._small_print.setWordWrap(True)
        self._small_print.setContentsMargins(0, 14, 0, 0)
        self._small_print.hide()
        layout.addWidget(self._small_print)

        self._chapter_names: tuple[str, ...] = ()
        self._playing: int | None = None

    # -- what the window pushes in ----------------------------------------

    def show_profile(self, profile: DiscProfile) -> None:
        """What the disc's own files say, before the engine has opened it."""
        self.header.show_disc(profile)
        notes = list(profile.notes)
        if profile.needs_bdj:
            notes.insert(0, strings.NEEDS_JAVA)
        meta = profile.meta
        if meta is not None and meta.newer_than_us:
            notes.append(strings.DISC_FROM_A_NEWER_FACTORY)
        self._chapter_names = meta.chapter_names() if meta is not None else ()

        rows = [
            (title.number, title.name, title.duration_ms, title.chapters, title.is_menu)
            for title in profile.titles
        ]
        self._show(rows, profile.main_feature, notes, profile.has_menu)
        self._show_extras(profile)
        self._show_small_print(profile)

    def show_engine_titles(self, titles: list, main_feature: int | None) -> None:
        """What the engine found once the disc is open.

        These replace the ones read from the files, because the numbers here
        are the numbers ``select_title`` takes — a disc's playlists and a
        player's titles are not the same list, and picking a title with the
        wrong numbering plays the wrong thing.
        """
        self._show(
            [
                (title.number, title.name, title.duration_ms, title.chapters, title.is_menu)
                for title in titles
                if not _is_first_play(title)
            ],
            main_feature,
            [],
            any(title.is_menu for title in titles),
        )

    def set_playing(self, number: int | None) -> None:
        """Mark which row is on screen, so the list says what is happening."""
        if number == self._playing:
            return
        self._playing = number
        for row in range(self._list.count()):
            item = self._list.item(row)
            item.setData(ROLE_PLAYING, item.data(ROLE_NUMBER) == number)
        self._list.viewport().update()

    def chapter_names(self) -> tuple[str, ...]:
        return self._chapter_names

    # -- internals ---------------------------------------------------------

    def _show(
        self,
        rows: list[tuple[int, str, int, int, bool]],
        selected: int | None,
        notes: list[str],
        has_menu: bool,
    ) -> None:
        self._note.setText("  ".join(notes))
        self._note.setVisible(bool(notes))
        self._menu_button.setVisible(has_menu)
        self._feature_button.setEnabled(selected is not None or bool(rows))
        self._section.setVisible(bool(rows))

        self._list.clear()
        for number, name, duration_ms, chapters, is_menu in rows:
            item = QListWidgetItem(self._title_name(name, number, is_menu, selected))
            item.setData(ROLE_NUMBER, number)
            item.setData(ROLE_DETAIL, self._detail(chapters, is_menu))
            item.setData(ROLE_DURATION, strings.timecode(duration_ms) if duration_ms else "")
            item.setData(ROLE_PLAYING, number == self._playing)
            self._list.addItem(item)
        if selected is not None:
            for row in range(self._list.count()):
                if self._list.item(row).data(ROLE_NUMBER) == selected:
                    self._list.setCurrentRow(row)
                    break

    @staticmethod
    def _title_name(name: str, number: int, is_menu: bool, feature: int | None) -> str:
        """A title reads as a title.

        "Title 2" is what a file says; it is not what anything is called. When
        the disc gives no better name, the one thing we do know — that this is
        the feature, or a menu — is worth more than a number.
        """
        generic = name.strip().lower().startswith("title ") or not name.strip()
        if not generic:
            return name
        if is_menu:
            return "Disc menu"
        if feature is not None and number == feature:
            return "Feature"
        return name or f"Title {number + 1}"

    @staticmethod
    def _detail(chapters: int, is_menu: bool) -> str:
        parts = []
        if is_menu:
            parts.append("menu")
        if chapters:
            parts.append(f"{chapters} chapter" + ("" if chapters == 1 else "s"))
        return " · ".join(parts)

    def _show_extras(self, profile: DiscProfile) -> None:
        meta = profile.meta
        extras = meta.movie.extras if meta is not None and meta.movie is not None else ()
        if not extras:
            self._extras_section.hide()
            self._extras.hide()
            return
        lines = [
            entry.title + (f": {entry.description}" if entry.description else "")
            for entry in extras
        ]
        self._extras.setText("\n".join(lines))
        self._extras_section.show()
        self._extras.show()

    def _show_small_print(self, profile: DiscProfile) -> None:
        meta = profile.meta
        if meta is None:
            self._small_print.hide()
            return
        text = meta.publisher_text or (meta.movie.copyright_text if meta.movie else "")
        self._small_print.setText(text)
        self._small_print.setVisible(bool(text))

    def _on_activated(self, item: QListWidgetItem) -> None:
        self.play_title.emit(int(item.data(ROLE_NUMBER)))


def keep_labels_plain(root: QWidget) -> int:
    """Stop every label under ``root`` from rendering markup.

    ``QLabel`` defaults to ``AutoText``, which sniffs its own content and
    turns anything that looks like markup into a rich-text document. That
    document loads external resources, so a disc whose title is
    ``<img src="file:///C:/Users/…/private.png">`` had that file read off the
    machine and drawn in the Player's headline — straight past the path
    checks in ``optical/meta.py`` that exist to stop exactly that.

    Nothing in the Player needs a label to render markup. The one rich-text
    surface is the About box, which is ours and sets its own format.

    Returns how many labels were changed, so a test can tell whether it ran.
    """
    changed = 0
    for label in root.findChildren(QLabel):
        if label.textFormat() is not Qt.TextFormat.PlainText:
            label.setTextFormat(Qt.TextFormat.PlainText)
            changed += 1
    return changed


def _is_first_play(title) -> bool:
    """The disc's opening move, which nobody picks off a list.

    libbluray reports it as a title like any other — interactive, but not a
    menu, and carrying whatever length the clip it opens on happens to have.
    Every consumer player leaves it out of the contents, and so does this.
    """
    return bool(getattr(title, "is_interactive", False)) and not getattr(title, "is_menu", False)


#: What a file looks like, by what it is. Three answers is the right number:
#: a browser that draws a distinct icon for forty extensions is a browser
#: nobody reads, and one that draws none is a wall of text.
_PICTURE_SUFFIXES = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
)
_DISC_SUFFIXES = frozenset({".iso", ".img", ".bin", ".cue", ".mds", ".nrg"})


def _file_glyph(suffix: str) -> str:
    lowered = suffix.lower()
    if lowered in _PICTURE_SUFFIXES:
        return "image"
    if lowered in _DISC_SUFFIXES:
        return "disc"
    return "chapters"


class GameView(QWidget):
    """A game disc: ours, or someone else's.

    Two screens, one widget. Ours opens the disc menu. Someone else's shows
    the files if the path is a folder. Neither pretends Goldwing starts the
    game. The explanation sits under the title, not at the bottom of the
    window — a stretch in the header used to shove it there and clip it.
    """

    go_home = pyqtSignal()
    open_menu = pyqtSignal()
    open_file = pyqtSignal(Path)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.EDGE, 34, theme.EDGE, 30)
        layout.setSpacing(0)

        # The case, beside the name, the way a film's header shows it: a game
        # disc carries cover.jpg beside its document like any other.
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(16)
        self.cover = artwork.CoverPlate(width=92)
        self.cover.hide()
        header.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignTop)
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        self.kind = section_label("")
        column.addWidget(self.kind)

        self.name = QLabel("")
        self.name.setObjectName("discLabel")
        self.name.setFont(theme.ui_font(25, weight=300))
        self.name.setWordWrap(True)
        column.addWidget(self.name)

        self.body = QLabel("")
        self.body.setObjectName("body")
        self.body.setWordWrap(True)
        self.body.setMaximumWidth(560)
        self.body.setContentsMargins(0, 14, 0, 0)
        column.addWidget(self.body)
        header.addLayout(column, 1)
        # This page is wide and the text column stops at 560 px: without a stretch the spare width was shared out
        # between the cover and the name, and the cover sat alone in the middle of the page.
        header.addStretch(1)
        layout.addLayout(header)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 22, 0, 0)
        buttons.setSpacing(8)
        self.menu_button = QPushButton(strings.OPEN_GAME_MENU)
        self.menu_button.setObjectName("primary")
        self.menu_button.clicked.connect(self.open_menu.emit)
        self.home_button = QPushButton(strings.GO_HOME)
        self.home_button.clicked.connect(self.go_home.emit)
        buttons.addWidget(self.menu_button)
        buttons.addWidget(self.home_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._summary = QLabel("")
        self._summary.setObjectName("note")
        self._summary.setWordWrap(True)
        self._summary.setContentsMargins(0, 20, 0, 0)
        self._summary.hide()
        layout.addWidget(self._summary)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels([strings.FILES, "Size"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)
        self._tree.setRootIsDecorated(True)
        self._tree.setIndentation(16)
        self._tree.setMouseTracking(True)
        self._tree.itemActivated.connect(self._on_activated)
        self._tree.itemExpanded.connect(self._on_expanded)
        self._tree.hide()
        layout.addSpacing(18)
        layout.addWidget(self._tree, 1)
        self._tail = QWidget()
        self._tail.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._tail, 1)

    def show_disc(self, profile: DiscProfile) -> None:
        ours = profile.ours
        chosen = profile.meta is not None and bool(profile.meta.title)
        self.kind.setText(
            (strings.KIND_OURS_GAME if ours else strings.KIND_NAMES["game-disc"]).upper()
        )
        name = profile.display_name
        self.name.setObjectName("discName" if chosen else "discLabel")
        font = (
            theme.display_font(DiscHeader._name_size(name))
            if chosen
            else theme.ui_font(25, weight=300)
        )
        font.setItalic(chosen)
        self.name.setFont(font)
        self.name.style().unpolish(self.name)
        self.name.style().polish(self.name)
        self.name.setText(name)
        self.body.setText(strings.game_note(ours=ours, image=profile.root.is_file()))
        self.menu_button.setVisible(ours and shelf.menu_executable(profile.root) is not None)
        cover = profile.art.cover
        self.cover.setVisible(cover is not None)
        if cover is not None:
            self.cover.set_cover(cover, name)

        if profile.root.is_dir():
            parts = []
            if profile.file_count:
                parts.append(f"{profile.file_count:,} files")
            if profile.total_bytes:
                parts.append(strings.file_size(profile.total_bytes))
            self._summary.setText(" · ".join(parts))
            self._summary.setVisible(bool(parts))
            self._tree.clear()
            self._fill(self._tree.invisibleRootItem(), profile.root)
            self._tree.show()
            self._tail.hide()
        else:
            self._summary.hide()
            self._tree.clear()
            self._tree.hide()
            self._tail.show()

    def _fill(self, parent: QTreeWidgetItem, folder: Path) -> None:
        try:
            entries = sorted(
                folder.iterdir(), key=lambda path: (path.is_file(), path.name.lower())
            )
        except OSError:
            return
        for entry in entries:
            item = QTreeWidgetItem(parent)
            item.setText(0, entry.name)
            item.setData(0, Qt.ItemDataRole.UserRole, str(entry))
            item.setForeground(1, QColor(theme.DIM))
            if entry.is_dir():
                item.setForeground(0, QColor(theme.BONE))
                item.setIcon(0, icons.icon("folder", 15, theme.MUTED))
                QTreeWidgetItem(item)
            else:
                item.setForeground(0, QColor(theme.NEAR))
                item.setIcon(0, icons.icon(_file_glyph(entry.suffix), 15, theme.FAINT))
                try:
                    item.setText(1, strings.file_size(entry.stat().st_size))
                except OSError:
                    item.setText(1, "")

    def _on_expanded(self, item: QTreeWidgetItem) -> None:
        if item.childCount() == 1 and not item.child(0).text(0):
            item.takeChildren()
            self._fill(item, Path(item.data(0, Qt.ItemDataRole.UserRole)))

    def _on_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        path = Path(item.data(0, Qt.ItemDataRole.UserRole))
        if path.is_file():
            self.open_file.emit(path)


class BrowserView(QWidget):
    """A data or M-Disc archive, as a tree you can open things from."""

    open_file = pyqtSignal(Path)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.EDGE, 34, theme.EDGE, 30)
        layout.setSpacing(0)

        self.header = DiscHeader()
        layout.addWidget(self.header)
        layout.addSpacing(6)

        self._summary = QLabel("")
        self._summary.setObjectName("body")
        self._summary.setWordWrap(True)
        self._summary.setMaximumWidth(560)
        layout.addWidget(self._summary)
        layout.addSpacing(24)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels([strings.FILES, "Size"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.header().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)
        self._tree.setRootIsDecorated(True)
        self._tree.setIndentation(16)
        self._tree.setMouseTracking(True)
        self._tree.itemActivated.connect(self._on_activated)
        self._tree.itemExpanded.connect(self._on_expanded)
        layout.addWidget(self._tree, 1)

    def show_disc(self, profile: DiscProfile) -> None:
        self.header.show_disc(profile)
        if profile.root.is_file():
            # An image is not a folder we can walk. The note is the whole
            # listing: what this is, and what to do with it.
            self._summary.setText(" ".join(profile.notes) or strings.IMAGE_NOTE_DATA)
            self._summary.setVisible(True)
            self._tree.clear()
            self._tree.hide()
            return
        self._tree.show()
        parts = []
        if profile.file_count:
            parts.append(f"{profile.file_count:,} files")
        if profile.total_bytes:
            parts.append(strings.file_size(profile.total_bytes))
        if profile.label and profile.meta is not None and profile.meta.title:
            parts.append(f"volume {profile.label}")
        parts.extend(profile.notes)
        self._summary.setText(" · ".join(parts))
        self._summary.setVisible(bool(parts))
        self._tree.clear()
        self._fill(self._tree.invisibleRootItem(), profile.root)

    def _fill(self, parent: QTreeWidgetItem, folder: Path) -> None:
        try:
            entries = sorted(
                folder.iterdir(), key=lambda path: (path.is_file(), path.name.lower())
            )
        except OSError:
            return
        for entry in entries:
            item = QTreeWidgetItem(parent)
            item.setText(0, entry.name)
            item.setData(0, Qt.ItemDataRole.UserRole, str(entry))
            item.setForeground(1, QColor(theme.DIM))
            if entry.is_dir():
                item.setForeground(0, QColor(theme.BONE))
                item.setIcon(0, icons.icon("folder", 15, theme.MUTED))
                # A placeholder child makes the twisty appear; the real
                # children are read when it is opened, so a disc with tens of
                # thousands of files does not stall the window.
                QTreeWidgetItem(item)
            else:
                item.setForeground(0, QColor(theme.NEAR))
                item.setIcon(0, icons.icon(_file_glyph(entry.suffix), 15, theme.FAINT))
                try:
                    item.setText(1, strings.file_size(entry.stat().st_size))
                except OSError:
                    item.setText(1, "")

    def _on_expanded(self, item: QTreeWidgetItem) -> None:
        if item.childCount() == 1 and not item.child(0).text(0):
            item.takeChildren()
            self._fill(item, Path(item.data(0, Qt.ItemDataRole.UserRole)))

    def _on_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        path = Path(item.data(0, Qt.ItemDataRole.UserRole))
        if path.is_file():
            self.open_file.emit(path)


class AudioCdView(QWidget):
    """An audio CD.

    There is no video to show, so the disc itself becomes the picture. It is
    drawn rather than loaded, because a Red Book audio CD has no filesystem
    to keep a picture on — a table of contents and interleaved audio frames,
    and nowhere to put a JPEG. What it *can* carry is CD-TEXT, so the album's
    name is what the disc is tinted from, and the same record looks the same
    way every time it goes in.
    """

    play_track = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(theme.EDGE + 4, 52, theme.EDGE + 8, 30)
        row.setSpacing(48)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)

        self.face = artwork.DiscFace(size=286)
        left.addWidget(self.face, 0, Qt.AlignmentFlag.AlignLeft)
        left.addSpacing(40)

        self._kind = section_label(strings.AUDIO_CD)
        left.addWidget(self._kind)
        left.addSpacing(12)

        self._album = QLabel("")
        self._album.setObjectName("discName")
        self._album.setFont(theme.display_font(33))
        self._album.setWordWrap(True)
        self._album.setMaximumWidth(300)
        left.addWidget(self._album)

        self._artist = QLabel("")
        self._artist.setObjectName("discBy")
        self._artist.setContentsMargins(0, 9, 0, 0)
        self._artist.setWordWrap(True)
        left.addWidget(self._artist)

        self._summary = QLabel("")
        self._summary.setObjectName("note")
        self._summary.setContentsMargins(0, 5, 0, 0)
        left.addWidget(self._summary)

        left.addStretch(1)
        row.addLayout(left, 0)

        right = QVBoxLayout()
        right.setContentsMargins(0, 4, 0, 0)
        right.setSpacing(0)

        heading = QHBoxLayout()
        heading.setContentsMargins(theme.ROW_X, 0, theme.ROW_X, 14)
        number = section_label("#")
        number.setFixedWidth(26)
        heading.addWidget(number)
        heading.addWidget(section_label(strings.TRACKS), 1)
        length = section_label("Length")
        heading.addWidget(length)
        right.addLayout(heading)

        self._list = QListWidget()
        self._list.setItemDelegate(TitleDelegate(self._list))
        self._list.setMouseTracking(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.itemActivated.connect(self._emit)
        self._list.itemClicked.connect(self._emit)
        right.addWidget(self._list, 1)
        row.addLayout(right, 1)

        self._playing: int | None = None

    def show_disc(
        self,
        profile: DiscProfile,
        names: list[str] | None = None,
        *,
        album: str = "",
        artist: str = "",
    ) -> None:
        title = album or profile.display_name
        self._album.setText(title)
        self._artist.setText(artist)
        self._artist.setVisible(bool(artist))
        count = len(profile.titles)
        parts = [f"{count} track" + ("" if count == 1 else "s")]
        total = sum(entry.duration_ms for entry in profile.titles)
        if total:
            parts.append(strings.timecode(total))
        self._summary.setText(" · ".join(parts))
        self.face.set_face(profile.art.face, title)

        self._list.clear()
        for index, entry in enumerate(profile.titles):
            name = names[index] if names and index < len(names) else entry.name
            item = QListWidgetItem(name)
            item.setData(ROLE_NUMBER, index)
            item.setData(ROLE_INDEX, f"{index + 1:02d}")
            item.setData(ROLE_DETAIL, "")
            item.setData(ROLE_DURATION, strings.timecode(entry.duration_ms) if entry.duration_ms else "")
            item.setData(ROLE_PLAYING, index == self._playing)
            self._list.addItem(item)

    def set_playing(self, index: int | None) -> None:
        self._playing = index
        for row in range(self._list.count()):
            item = self._list.item(row)
            item.setData(ROLE_PLAYING, item.data(ROLE_NUMBER) == index)
        self._list.viewport().update()

    def _emit(self, item: QListWidgetItem) -> None:
        self.play_track.emit(int(item.data(ROLE_NUMBER)))


class Banner(QFrame):
    """One line of plain language across the top when something is worth saying."""

    dismissed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("banner")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 10, 10, 10)
        layout.setSpacing(11)

        self._icon = QLabel("")
        self._icon.setFixedWidth(15)
        layout.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)

        self._label = QLabel("")
        self._label.setWordWrap(True)
        layout.addWidget(self._label, 1)

        self._action = QPushButton("")
        self._action.setObjectName("bannerButton")
        self._action.hide()
        layout.addWidget(self._action)

        close = QPushButton("Dismiss")
        close.setObjectName("bannerButton")
        close.clicked.connect(self._dismiss)
        layout.addWidget(close)
        self.setMaximumHeight(0)
        self.hide()

    def show_message(
        self,
        text: str,
        *,
        tone: str = "problem",
        action: tuple[str, Callable] | None = None,
    ) -> None:
        self.setProperty("tone", tone)
        self.style().unpolish(self)
        self.style().polish(self)
        self._icon.setPixmap(
            icons.pixmap(
                "inspect" if tone == "notice" else "warn",
                14,
                theme.NOTICE_EDGE if tone == "notice" else "#e0a0a0",
            )
        )
        self._label.setText(text)
        try:
            self._action.clicked.disconnect()
        except TypeError:
            pass
        if action is not None:
            self._action.setText(action[0])
            self._action.clicked.connect(action[1])
            self._action.show()
        else:
            self._action.hide()
        self.setMaximumHeight(16777215)
        self.show()

    def message(self) -> str:
        """What is currently being said, or empty when nothing is.

        Read by tests. ``isVisible()`` is False on any widget whose window
        was never shown, so it cannot tell "we said nothing" from "the
        window is not on screen".
        """
        return self._label.text() if not self.isHidden() else ""

    def hide(self) -> None:
        self.setMaximumHeight(0)
        super().hide()

    def _dismiss(self) -> None:
        self.hide()
        self._label.setText("")
        self._icon.clear()
        self.dismissed.emit()


class _ElidedLabel(QLabel):
    """A label that shortens from the left, keeping the end that identifies it.

    A disc path is mostly prefix. What matters is the last folder, so that is
    the half that survives.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        # Without this the widget asks for the width of the text it is
        # currently showing, which is the text it shortened to fit the width
        # it was given — and it shrinks a little further on every layout pass
        # until there is nothing left but the last three characters.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def setText(self, text: str) -> None:
        self._full = text or ""
        super().setText(self._full)
        self._reflow()

    def sizeHint(self) -> QSize:
        hint = QFontMetrics(self.font()).size(0, self._full)
        return QSize(min(hint.width() + 2, self.maximumWidth()), hint.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(60, QFontMetrics(self.font()).height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        if not self._full:
            return
        metrics = QFontMetrics(self.font())
        super().setText(
            metrics.elidedText(self._full, Qt.TextElideMode.ElideLeft, max(60, self.width()))
        )


class TopBar(QWidget):
    """A thin strip: the mark, Home when a disc is open, and the panel button.

    The disc's name lives on the page and in the window title, not here
    again. Release status is not repeated beside the mark.
    """

    toggle_panel = pyqtSignal()
    go_home = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("topBar")
        self.setFixedHeight(34)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 8, 0)
        row.setSpacing(10)

        self._mark = QLabel()
        self._mark.setObjectName("goldwingMark")
        mark = theme.mark_pixmap(20)
        if mark is not None:
            self._mark.setPixmap(mark)
        self._mark.setFixedSize(22, 22)
        row.addWidget(self._mark, 0, Qt.AlignmentFlag.AlignVCenter)

        self.home_button = QPushButton(strings.GO_HOME)
        self.home_button.setObjectName("quiet")
        self.home_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.home_button.clicked.connect(self.go_home.emit)
        self.home_button.hide()
        row.addWidget(self.home_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self._where = _ElidedLabel()
        self._where.setObjectName("note")
        self._where.setMaximumWidth(680)
        row.addWidget(self._where)
        row.addStretch(1)

        self.panel_button = IconButton("chapters", strings.HIDE_PANEL, size=16, box=28)
        self.panel_button.clicked.connect(self.toggle_panel.emit)
        self.panel_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.panel_button.hide()
        row.addWidget(self.panel_button)

    def set_where(self, text: str, *, tip: str = "") -> None:
        """Status while a disc is being read. Not the disc's name again."""
        self._where.setText(text)
        self._where.setToolTip(tip or text)

    def set_home_visible(self, visible: bool) -> None:
        self.home_button.setVisible(visible)

    def set_panel_available(self, available: bool) -> None:
        self.panel_button.setVisible(available)


def connect_once(signal, slot: Callable) -> None:
    """Connect and drop the connection after the first emission."""

    def wrapper(*args: object) -> None:
        signal.disconnect(wrapper)
        slot(*args)

    signal.connect(wrapper)
