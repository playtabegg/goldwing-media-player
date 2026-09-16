"""Draw a DVD menu: the picture, the subpicture, and the lit button.

Ordinary playback hands libvlc a window and lets the graphics card get on
with it. That is right for a film and wrong for a menu: nothing can be
composited over video the card is painting straight to a window.

So a DVD menu takes the other path: libvlc renders into a buffer we own, and
this widget paints the picture, then the menu's subpicture on top, then the
highlight over the button that is lit. The highlight is the same subpicture
pixels re-coloured inside the button's rectangle, which is how a disc
defines it.

It is a separate widget from the one ordinary playback uses, deliberately: if
this path has a bad day, films still play.
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPainter, QPaintEvent
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ..dvd.navigator import Navigator
from ..formats.dvd_spu import Subpicture, resolve_palette

#: What a DVD's picture is, and the coordinate space its buttons are in.
DVD_WIDTH = 720
DVD_HEIGHT = 480


class MenuSurface(QWidget):
    """A video surface that can have a DVD menu drawn over it."""

    #: Emitted from libvlc's thread when a frame lands. Connect it queued.
    frame_ready = pyqtSignal()
    #: A button was clicked, in the disc's own coordinates.
    button_clicked = pyqtSignal(int, int)
    #: The cursor moved over the picture, in the disc's own coordinates.
    cursor_moved = pyqtSignal(int, int)

    def __init__(
        self,
        width: int = DVD_WIDTH,
        height: int = DVD_HEIGHT,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

        self.video_width = width
        self.video_height = height
        self._buffer: memoryview | None = None
        self._frame_lock = None
        self._subpicture: Subpicture | None = None
        self._chain_palette: list[int] = [0] * 16
        self._highlight_palette: tuple[int, int, int, int] | None = None
        self._highlight_alpha: tuple[int, int, int, int] | None = None
        self.navigator: Navigator | None = None
        self._base_cache: QImage | None = None
        self._button_cache: dict[int, tuple[QImage, int, int]] = {}
        # Whether the subpicture has anything visible in it. Worked out once
        # when it arrives: asking a 720x480 picture on every frame costs more
        # than drawing it.
        self._blank = True

        self.frame_ready.connect(self.update, Qt.ConnectionType.QueuedConnection)

    # -- what to draw ------------------------------------------------------

    def attach_buffer(
        self, buffer: memoryview, width: int, height: int, lock=None
    ) -> None:
        """The frame buffer, and the lock the decoder writes it under.

        Without the lock a paint can land halfway through the decoder's
        write and show a frame that is half of the next one. It is optional
        because the fake engine has no decoder and needs none.
        """
        self._buffer = buffer
        self.video_width = width
        self.video_height = height
        self._frame_lock = lock

    def show_menu(
        self,
        navigator: Navigator | None,
        subpicture: Subpicture | None,
        chain_palette: list[int] | None = None,
        highlight_palette: tuple[int, int, int, int] | None = None,
        highlight_alpha: tuple[int, int, int, int] | None = None,
    ) -> None:
        self.navigator = navigator
        self._subpicture = subpicture
        if chain_palette:
            self._chain_palette = list(chain_palette)[:16] + [0] * max(
                0, 16 - len(chain_palette)
            )
        self._highlight_palette = highlight_palette
        self._highlight_alpha = highlight_alpha
        self._blank = subpicture is None or subpicture.is_blank
        self._base_cache = None
        self._button_cache.clear()
        self.update()

    def clear_menu(self) -> None:
        self.navigator = None
        self._subpicture = None
        # The frame buffer goes too. It is 1.4 MB, it belongs to a menu that
        # is over, and holding it kept it alive for the rest of the session
        # while every new menu allocated another.
        self._buffer = None
        self._blank = True
        self._base_cache = None
        self._button_cache.clear()
        self.update()

    def set_selection(self) -> None:
        """The highlight moved, and nothing else did.

        Kept apart from :meth:`show_menu` because that one throws away both
        caches, and the caches are the reason moving a highlight costs
        0.009 ms instead of 98. Calling show_menu on every arrow key put the
        cost straight back.
        """
        self.update()

    # -- painting ----------------------------------------------------------

    def _frame_bytes(self) -> int:
        """How big the buffer has to be before Qt is allowed to read it.

        ``QImage`` over a Python buffer does no bounds checking at all: a
        buffer one page short of what the geometry implies is a segmentation
        fault, not an exception. One comparison is cheap insurance.
        """
        return max(0, self.video_width) * max(0, self.video_height) * 4

    def _video_rect(self):
        """Where the picture goes, letterboxed to keep its shape."""
        if not self.video_width or not self.video_height:
            return 0, 0, self.width(), self.height()
        scale = min(self.width() / self.video_width, self.height() / self.video_height)
        width = int(self.video_width * scale)
        height = int(self.video_height * scale)
        return (self.width() - width) // 2, (self.height() - height) // 2, width, height

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        left, top, width, height = self._video_rect()

        if self._buffer is not None and len(self._buffer) >= self._frame_bytes():
            # Taken while the frame is copied into the QImage, so a paint
            # never lands halfway through the decoder writing the next one.
            held = self._frame_lock.acquire(timeout=0.05) if self._frame_lock else False
            frame = QImage(
                self._buffer,
                self.video_width,
                self.video_height,
                self.video_width * 4,
                QImage.Format.Format_RGB32,
            )
            try:
                painter.drawImage(
                    self.rect()
                    .adjusted(left, top, -(self.width() - left - width), 0)
                    .topLeft(),
                    frame.scaled(
                        width,
                        height,
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ),
                )
            finally:
                if held:
                    self._frame_lock.release()

        self._paint_menu(painter, left, top, width, height)
        painter.end()

    def _paint_menu(
        self, painter: QPainter, left: int, top: int, width: int, height: int
    ) -> None:
        base = self._base_overlay()
        if base is None:
            return
        picture = self._subpicture
        scale_x = width / self.video_width
        scale_y = height / self.video_height

        def place(image: QImage, x: int, y: int) -> None:
            painter.drawImage(
                QRect(
                    left + int(x * scale_x),
                    top + int(y * scale_y),
                    max(1, int(image.width() * scale_x)),
                    max(1, int(image.height() * scale_y)),
                ),
                image,
            )

        place(base, picture.area.x_start, picture.area.y_start)
        button = self.navigator.selected_button if self.navigator is not None else None
        lit = self._lit_button_overlay(button)
        if lit is not None:
            image, x, y = lit
            place(image, x, y)

    def _rgba_image(
        self,
        rows,
        origin_x: int,
        origin_y: int,
        colours,
        width: int,
        height: int,
    ) -> QImage:
        """Turn indexed rows into an ARGB image in one pass.

        Built as bytes and handed to Qt whole. Setting pixels one at a time
        took about a tenth of a second for a full-frame menu, which is a
        visible stutter every time somebody moves the highlight.
        """
        # Qt's ARGB32 is a 32-bit word per pixel, little-endian in memory.
        lookup = [
            bytes((blue, green, red, alpha)) for red, green, blue, alpha in colours
        ]
        transparent = bytes(4)
        buffer = bytearray()
        for line in range(height):
            row = rows[line] if line < len(rows) else ()
            if len(row) == width:
                buffer += b"".join(map(lookup.__getitem__, row))
            else:
                buffer += b"".join(
                    lookup[row[column]] if column < len(row) else transparent
                    for column in range(width)
                )
        image = QImage(bytes(buffer), width, height, width * 4, QImage.Format.Format_ARGB32)
        return image.copy()

    def _base_overlay(self) -> QImage | None:
        """The whole subpicture in its ordinary colours. Cached."""
        picture = self._subpicture
        if picture is None or self._blank:
            return None
        if self._base_cache is None:
            self._base_cache = self._rgba_image(
                picture.rows,
                picture.area.x_start,
                picture.area.y_start,
                resolve_palette(self._chain_palette, picture.palette, picture.alpha),
                picture.width,
                picture.height,
            )
        return self._base_cache

    def _lit_button_overlay(self, button) -> QImage | None:
        """Only the lit button's rectangle, re-coloured. Cached per button.

        Redrawing the whole menu to move a highlight is what makes DVD menus
        feel slow. The disc only ever means for one rectangle to change.
        """
        picture = self._subpicture
        if (
            picture is None
            or button is None
            or self._highlight_palette is None
            or self._highlight_alpha is None
        ):
            return None
        cached = self._button_cache.get(button.number)
        if cached is not None:
            return cached

        area = picture.area
        left = max(button.x_start, area.x_start)
        top = max(button.y_start, area.y_start)
        right = min(button.x_end, area.x_start + picture.width)
        bottom = min(button.y_end, area.y_start + picture.height)
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            return None

        rows = [
            picture.rows[top - area.y_start + line][
                left - area.x_start : right - area.x_start
            ]
            for line in range(height)
        ]
        image = self._rgba_image(
            rows,
            left,
            top,
            resolve_palette(
                self._chain_palette, self._highlight_palette, self._highlight_alpha
            ),
            width,
            height,
        )
        self._button_cache[button.number] = (image, left, top)
        return self._button_cache[button.number]

    # -- the mouse ---------------------------------------------------------

    def _to_disc(self, x: int, y: int) -> tuple[int, int] | None:
        left, top, width, height = self._video_rect()
        if not width or not height:
            return None
        if not (left <= x < left + width and top <= y < top + height):
            return None
        return (
            int((x - left) * self.video_width / width),
            int((y - top) * self.video_height / height),
        )

    def mouseMoveEvent(self, event) -> None:
        point = self._to_disc(int(event.position().x()), int(event.position().y()))
        if point is not None:
            self.cursor_moved.emit(*point)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        point = self._to_disc(int(event.position().x()), int(event.position().y()))
        if point is not None:
            self.button_clicked.emit(*point)
        super().mousePressEvent(event)
