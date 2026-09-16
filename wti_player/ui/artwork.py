"""A disc's own picture of itself.

Two shapes, because a disc has two pieces of art and they are not
interchangeable. The **cover** is the front of the case: portrait, the image
people recognise across a room. The **face** is the printed label: square art
seen as a circle, which is what you are holding when you put it in the drive.

Either can be missing, and on an audio CD both always are — a Red Book disc
is a table of contents and interleaved audio frames with no filesystem to
keep a file on. So :class:`DiscFace` draws one when there is nothing to load:
a plain disc, tinted from the album's own name so the same record looks the
same way every time it goes in, and different from the one before it.

Everything here is defensive about what it loads, because the bytes come off
a disc somebody else made.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from PyQt6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QImageReader,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget

from . import theme

#: No cover is worth more pixels than this. A disc could carry a 6000px
#: scan, and scaling one of those on the interface thread is a visible stall.
MAX_EDGE = 1400

#: The name to tint a disc with when it is not a particular disc — the one
#: drawn on the empty screen. Chosen rather than hashed, so the Player's own
#: resting state never comes out lilac.
NEUTRAL = "::wti-player-at-rest::"

_cache: dict[tuple[str, int], QPixmap | None] = {}


def load(path: Path | None, *, max_edge: int = MAX_EDGE) -> QPixmap | None:
    """Read one art file. ``None`` for anything that is not a usable image.

    Bounded twice over: :mod:`optical.meta` has already refused a file that
    is too large on disk, and :class:`QImageReader` is asked to scale on the
    way in rather than after, so a 6000px scan never exists at full size in
    memory.
    """
    if path is None:
        return None
    key = (str(path), max_edge)
    if key in _cache:
        return _cache[key]

    result: QPixmap | None = None
    try:
        fmt = _format_of(path)
        if fmt is None:
            _cache[key] = None
            return None
        # The format is pinned, never sniffed. QImageReader dispatches on
        # content, not on the name: a file called cover.jpg holding SVG went
        # to the SVG renderer, and eight megabytes of it froze the window for
        # ten and a half seconds. One called label.jpg holding a PDF went to
        # PDFium. A disc supplies this file.
        reader = QImageReader(str(path), fmt)
        reader.setAutoTransform(True)
        size = reader.size()
        if not _sane_shape(size):
            _cache[key] = None
            return None
        if size.isValid() and max(size.width(), size.height()) > max_edge:
            scaled = size.scaled(max_edge, max_edge, Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(scaled)
        image = reader.read()
        if not image.isNull():
            result = QPixmap.fromImage(image)
    except Exception:  # a picture is never worth an exception
        result = None

    _cache[key] = result
    return result


#: The widest a picture may be relative to its height, or the other way
#: round. Real cover art is between about 1:2 and 2:1; a poster is 2:3.
MAX_ASPECT = 8.0

#: What a file has to start with to be the thing it claims to be. Two
#: formats, which is every format a disc's artwork is ever in.
_MAGIC = (
    (b"\xff\xd8\xff", b"jpeg"),
    (b"\x89PNG\r\n\x1a\n", b"png"),
)


def _format_of(path: Path) -> bytes | None:
    """JPEG or PNG, decided by the file's own first bytes.

    Not by its extension, which a disc chooses, and not by letting Qt sniff,
    which is how a ``.jpg`` ends up at the SVG renderer.
    """
    try:
        with path.open("rb") as handle:
            head = handle.read(8)
    except OSError:
        return None
    for magic, name in _MAGIC:
        if head.startswith(magic):
            return name
    return None


def _sane_shape(size) -> bool:
    """Is this a picture, or a shape chosen to make the painter work?

    A 28000x20 PNG is 665 bytes and passes every size check there is: the
    long edge clamps to a 1400x1 pixmap. Then drawing it to cover a 92x138
    plate expands it to 193200x138 — a hundred megabytes, smooth-filtered,
    on every repaint.
    """
    if not size.isValid():
        return True
    width, height = size.width(), size.height()
    if width <= 0 or height <= 0:
        return False
    return max(width, height) / min(width, height) <= MAX_ASPECT


def forget(path: Path | None = None) -> None:
    """Drop cached art. Called when a disc is ejected."""
    if path is None:
        _cache.clear()
        return
    for key in [key for key in _cache if key[0] == str(path)]:
        del _cache[key]


def tint_for(text: str) -> QColor:
    """A stable colour for a name.

    Deliberately narrow: hue anywhere on the wheel, but low saturation and
    dark, so a generated disc still belongs to this palette and never turns
    into a bright circle competing with the film beside it.
    """
    if text == NEUTRAL:
        colour = QColor()
        colour.setHsvF(0.60, 0.10, 0.20)
        return colour
    digest = hashlib.sha256((text or "unnamed").encode("utf-8")).digest()
    hue = digest[0] / 255.0
    saturation = 0.16 + (digest[1] / 255.0) * 0.14
    value = 0.19 + (digest[2] / 255.0) * 0.08
    colour = QColor()
    colour.setHsvF(hue, saturation, value)
    return colour


class CoverPlate(QWidget):
    """A disc's cover, or a plate standing in for one.

    Sized by its width: covers are close enough to 2:3 that forcing the ratio
    reads better than letting a square scan stretch the layout around it.
    """

    RATIO = 3 / 2

    def __init__(self, parent: QWidget | None = None, *, width: int = 220) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._title = ""
        self._width = width
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(width, int(width * self.RATIO))

    def set_cover(self, path: Path | None, title: str = "") -> None:
        self._pixmap = load(path)
        self._title = title
        self.setVisible(True)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(self._width, int(self._width * self.RATIO))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # Product renders already contain the case, its edges and its shadow.
        # Keep their alpha and proportions; a portrait crop would cut the case.
        if self._pixmap is not None and self._pixmap.hasAlphaChannel():
            _paint_product_render(painter, self._pixmap, self.size())
            painter.end()
            return

        area = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(area, 4, 4)
        painter.setClipPath(path)

        if self._pixmap is not None and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            offset = QPointF(
                (self.width() - scaled.width()) / 2,
                (self.height() - scaled.height()) / 2,
            )
            painter.drawPixmap(offset, scaled)
        else:
            painter.fillRect(self.rect(), tint_for(self._title))

        painter.setClipping(False)
        painter.setPen(QPen(QColor(232, 226, 214, 28), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()


class DiscFace(QWidget):
    """The disc itself, drawn as a disc.

    With art, the label is mapped into the annulus between the hub and the
    outer edge — which is where a printed label actually goes, so a cover
    dropped in here reads as a disc rather than as a circular crop.

    Without art, it is drawn: a slow conical sheen for the way a disc catches
    light, the fine concentric rings of the data spiral, and a hub tinted from
    the disc's name.
    """

    #: Fractions of the diameter. These are close to a real CD's proportions:
    #: 120mm across, a 15mm hole, a 46mm clamping area.
    HOLE = 0.125
    HUB = 0.38
    RING_SPACING = 4

    def __init__(self, parent: QWidget | None = None, *, size: int = 300) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._title = ""
        self._diameter = size
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(size, size)

    def set_face(self, path: Path | None, title: str = "") -> None:
        self._pixmap = load(path)
        self._title = title
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(self._diameter, self._diameter)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # A transparent PNG is the finished product image, including its hole
        # and reflections. Do not crop it to a circle or paint a second hub.
        if self._pixmap is not None and self._pixmap.hasAlphaChannel():
            _paint_product_render(painter, self._pixmap, self.size())
            painter.end()
            return

        side = min(self.width(), self.height())
        area = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        centre = area.center()

        outer = QPainterPath()
        outer.addEllipse(area)
        painter.save()
        painter.setClipPath(outer)

        if self._pixmap is not None and not self._pixmap.isNull():
            self._paint_label(painter, area)
        else:
            self._paint_blank(painter, area, side)

        # The sheen, over either. A disc is a mirror before it is a label.
        sheen = QConicalGradient(centre, 118.0)
        sheen.setColorAt(0.00, QColor(255, 255, 255, 0))
        sheen.setColorAt(0.14, QColor(255, 255, 255, 26))
        sheen.setColorAt(0.30, QColor(255, 255, 255, 0))
        sheen.setColorAt(0.62, QColor(255, 255, 255, 18))
        sheen.setColorAt(0.78, QColor(255, 255, 255, 0))
        sheen.setColorAt(1.00, QColor(255, 255, 255, 0))
        painter.fillPath(outer, QBrush(sheen))

        painter.restore()

        self._paint_hole(painter, area, side)

        painter.setPen(QPen(QColor(232, 226, 214, 30), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(area.adjusted(0.5, 0.5, -0.5, -0.5))
        painter.end()

    # -- the two halves of the drawing -------------------------------------

    def _paint_label(self, painter: QPainter, area: QRectF) -> None:
        assert self._pixmap is not None
        target = QSize(int(area.width()), int(area.height()))
        scaled = self._pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap(
            QPointF(
                area.x() + (area.width() - scaled.width()) / 2,
                area.y() + (area.height() - scaled.height()) / 2,
            ),
            scaled,
        )

    def _paint_blank(self, painter: QPainter, area: QRectF, side: float) -> None:
        base = tint_for(self._title)
        lift = base.lighter(150)
        drop = base.darker(135)

        wheel = QConicalGradient(area.center(), 210.0)
        for at, colour in ((0.0, base), (0.22, lift), (0.44, drop),
                           (0.68, lift), (1.0, base)):
            wheel.setColorAt(at, colour)
        painter.fillRect(area, QBrush(wheel))

        # The data spiral, as rings a pixel apart at the widest zoom anyone
        # will use. Cheap, and it is the detail that stops this reading flat.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(232, 226, 214, 11), 1))
        radius = side / 2
        step = self.RING_SPACING
        inner = radius * self.HUB
        while radius > inner:
            painter.drawEllipse(area.center(), radius, radius)
            radius -= step

    def _paint_hole(self, painter: QPainter, area: QRectF, side: float) -> None:
        centre = area.center()
        hub_r = side * self.HUB / 2
        hole_r = side * self.HOLE / 2

        hub = QRectF(centre.x() - hub_r, centre.y() - hub_r, hub_r * 2, hub_r * 2)
        glow = QRadialGradient(centre, hub_r)
        glow.setColorAt(0.0, QColor(theme.RAISED))
        glow.setColorAt(0.86, QColor(theme.RAISED))
        glow.setColorAt(1.0, QColor(18, 21, 29, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(hub)

        painter.setPen(QPen(QColor(232, 226, 214, 22), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(hub)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.INK))
        painter.drawEllipse(
            QRectF(centre.x() - hole_r, centre.y() - hole_r, hole_r * 2, hole_r * 2)
        )


def _paint_product_render(painter: QPainter, pixmap: QPixmap, size: QSize) -> None:
    scaled = pixmap.scaled(
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    painter.drawPixmap(
        QPointF((size.width() - scaled.width()) / 2, (size.height() - scaled.height()) / 2),
        scaled,
    )


def paint_shadow(painter: QPainter, rect: QRect, *, depth: int = 18) -> None:
    """A soft drop shadow under something that genuinely floats.

    Used under a cover and a disc, and nowhere else. Chrome does not float.
    """
    for step in range(depth, 0, -1):
        alpha = int(52 * (step / depth) ** 3)
        if alpha <= 0:
            continue
        painter.setPen(QPen(QColor(0, 0, 0, alpha), 1))
        painter.drawRoundedRect(
            rect.adjusted(-step, -step + depth // 3, step, step + depth // 3),
            4 + step,
            4 + step,
        )
