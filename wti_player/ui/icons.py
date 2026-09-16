"""The Player's icons, drawn rather than loaded.

Nineteen small shapes is not worth an image format, a resource file or a
dependency on Qt's SVG module — and a drawn icon is the only kind that can
be handed a colour at the moment it is used, which is what the hover and
disabled states need.

Everything is described on a 24 by 24 grid, the same grid the design canvas
used, and scaled at paint time. Stroked shapes keep a 1.6px line at 24px so
they sit at the same weight as Outfit at 300 beside them.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

GRID = 24.0
STROKE = 1.6

_cache: dict[tuple[str, int, str], QPixmap] = {}


# -- the shapes -------------------------------------------------------------
#
# A filled name draws a solid shape; a stroked one draws a line. Playback
# controls are filled, because at 14px a stroked triangle turns to mush.

def _play(path: QPainterPath) -> None:
    path.moveTo(7.5, 4.6)
    path.lineTo(19.0, 12.0)
    path.lineTo(7.5, 19.4)
    path.closeSubpath()


def _pause(path: QPainterPath) -> None:
    path.addRoundedRect(QRectF(6.4, 4.5, 4.2, 15.0), 1.2, 1.2)
    path.addRoundedRect(QRectF(13.4, 4.5, 4.2, 15.0), 1.2, 1.2)


def _stop(path: QPainterPath) -> None:
    path.addRoundedRect(QRectF(5.8, 5.8, 12.4, 12.4), 1.6, 1.6)


def _previous(path: QPainterPath) -> None:
    path.addRoundedRect(QRectF(5.4, 5.0, 2.4, 14.0), 1.0, 1.0)
    path.moveTo(19.2, 5.0)
    path.lineTo(19.2, 19.0)
    path.lineTo(9.2, 12.0)
    path.closeSubpath()


def _next(path: QPainterPath) -> None:
    path.moveTo(4.8, 5.0)
    path.lineTo(14.8, 12.0)
    path.lineTo(4.8, 19.0)
    path.closeSubpath()
    path.addRoundedRect(QRectF(16.2, 5.0, 2.4, 14.0), 1.0, 1.0)


def _back(path: QPainterPath) -> None:
    """Skip back. Two chevrons, so it is never confused with previous title."""
    path.moveTo(11.6, 5.6)
    path.lineTo(11.6, 18.4)
    path.lineTo(3.6, 12.0)
    path.closeSubpath()
    path.moveTo(20.4, 5.6)
    path.lineTo(20.4, 18.4)
    path.lineTo(12.4, 12.0)
    path.closeSubpath()


def _forward(path: QPainterPath) -> None:
    path.moveTo(12.4, 5.6)
    path.lineTo(20.4, 12.0)
    path.lineTo(12.4, 18.4)
    path.closeSubpath()
    path.moveTo(3.6, 5.6)
    path.lineTo(11.6, 12.0)
    path.lineTo(3.6, 18.4)
    path.closeSubpath()


def _menu(path: QPainterPath) -> None:
    """A disc menu: four choices on a screen."""
    for x in (5.0, 13.4):
        for y in (5.0, 13.4):
            path.addRoundedRect(QRectF(x, y, 5.6, 5.6), 1.0, 1.0)


def _chapters(path: QPainterPath) -> None:
    for y in (6.0, 11.2, 16.4):
        path.addRoundedRect(QRectF(3.4, y, 2.0, 2.0), 0.6, 0.6)
        path.addRoundedRect(QRectF(7.6, y, 13.0, 2.0), 1.0, 1.0)


def _eject(path: QPainterPath) -> None:
    path.moveTo(12.0, 4.4)
    path.lineTo(20.0, 13.4)
    path.lineTo(4.0, 13.4)
    path.closeSubpath()
    path.addRoundedRect(QRectF(4.0, 16.2, 16.0, 2.6), 1.0, 1.0)


def _volume(path: QPainterPath) -> None:
    path.moveTo(4.0, 9.4)
    path.lineTo(8.0, 9.4)
    path.lineTo(12.6, 5.2)
    path.lineTo(12.6, 18.8)
    path.lineTo(8.0, 14.6)
    path.lineTo(4.0, 14.6)
    path.closeSubpath()
    path.moveTo(15.6, 9.0)
    path.arcTo(QRectF(12.6, 9.0, 6.0, 6.0), 90.0, -180.0)
    path.moveTo(18.0, 6.4)
    path.arcTo(QRectF(12.6, 6.4, 11.2, 11.2), 90.0, -180.0)


def _muted(path: QPainterPath) -> None:
    path.moveTo(4.0, 9.4)
    path.lineTo(8.0, 9.4)
    path.lineTo(12.6, 5.2)
    path.lineTo(12.6, 18.8)
    path.lineTo(8.0, 14.6)
    path.lineTo(4.0, 14.6)
    path.closeSubpath()
    path.moveTo(15.8, 9.6)
    path.lineTo(21.0, 14.8)
    path.moveTo(21.0, 9.6)
    path.lineTo(15.8, 14.8)


def _fullscreen(path: QPainterPath) -> None:
    for x, y, dx, dy in ((4.4, 9.6, 0, -5.2), (4.4, 4.4, 5.2, 0),
                         (19.6, 14.4, 0, 5.2), (19.6, 19.6, -5.2, 0),
                         (4.4, 14.4, 0, 5.2), (4.4, 19.6, 5.2, 0),
                         (19.6, 9.6, 0, -5.2), (19.6, 4.4, -5.2, 0)):
        path.moveTo(x, y)
        path.lineTo(x + dx, y + dy)


def _restore(path: QPainterPath) -> None:
    for x, y, dx, dy in ((9.6, 4.4, 0, 5.2), (9.6, 9.6, -5.2, 0),
                         (14.4, 19.6, 0, -5.2), (14.4, 14.4, 5.2, 0),
                         (14.4, 4.4, 0, 5.2), (14.4, 9.6, 5.2, 0),
                         (9.6, 19.6, 0, -5.2), (9.6, 14.4, -5.2, 0)):
        path.moveTo(x, y)
        path.lineTo(x + dx, y + dy)


def _folder(path: QPainterPath) -> None:
    path.moveTo(3.4, 18.6)
    path.lineTo(3.4, 6.0)
    path.lineTo(9.4, 6.0)
    path.lineTo(11.4, 8.4)
    path.lineTo(20.6, 8.4)
    path.lineTo(20.6, 18.6)
    path.closeSubpath()


def _disc(path: QPainterPath) -> None:
    path.addEllipse(QPointF(12.0, 12.0), 8.4, 8.4)
    path.addEllipse(QPointF(12.0, 12.0), 2.4, 2.4)


def _image_file(path: QPainterPath) -> None:
    path.addRoundedRect(QRectF(3.6, 5.4, 16.8, 13.2), 1.6, 1.6)
    path.moveTo(3.6, 15.0)
    path.lineTo(9.0, 10.4)
    path.lineTo(14.0, 15.0)
    path.lineTo(16.6, 12.8)
    path.lineTo(20.4, 16.0)


def _inspect(path: QPainterPath) -> None:
    path.addEllipse(QPointF(11.0, 11.0), 6.6, 6.6)
    path.moveTo(15.8, 15.8)
    path.lineTo(20.2, 20.2)


def _check(path: QPainterPath) -> None:
    path.moveTo(4.6, 12.4)
    path.lineTo(9.6, 17.4)
    path.lineTo(19.4, 6.6)


def _warn(path: QPainterPath) -> None:
    path.moveTo(12.0, 4.2)
    path.lineTo(21.2, 19.8)
    path.lineTo(2.8, 19.8)
    path.closeSubpath()
    path.moveTo(12.0, 10.0)
    path.lineTo(12.0, 14.4)


def _bars(path: QPainterPath) -> None:
    """A playing indicator: four bars of a level meter, at rest."""
    for x, top in ((4.0, 13.0), (9.0, 6.4), (14.0, 10.4), (19.0, 15.4)):
        path.addRoundedRect(QRectF(x, top, 2.6, 20.0 - top), 1.2, 1.2)


FILLED = {
    "play": _play,
    "pause": _pause,
    "stop": _stop,
    "previous": _previous,
    "next": _next,
    "back": _back,
    "forward": _forward,
    "menu": _menu,
    "chapters": _chapters,
    "eject": _eject,
    "volume": _volume,
    "bars": _bars,
}

STROKED = {
    "muted": _muted,
    "fullscreen": _fullscreen,
    "restore": _restore,
    "folder": _folder,
    "disc": _disc,
    "image": _image_file,
    "inspect": _inspect,
    "check": _check,
    "warn": _warn,
}


def device_pixel_ratio() -> float:
    """The primary screen's scale, or 1.0 with no screen (a test, a service)."""
    try:
        from PyQt6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
    except Exception:  # pragma: no cover - no Qt at all
        return 1.0
    if screen is None:
        return 1.0
    return max(1.0, float(screen.devicePixelRatio()))


def pixmap(name: str, size: int, colour: str, *, dpr: float | None = None) -> QPixmap:
    """One icon, at one size, in one colour. Cached — these get asked for a lot.

    Drawn at ``size * dpr`` device pixels and tagged with the ratio, so a
    16 px icon on a 200 percent display is 32 real pixels and stays sharp.
    Before this it was drawn at 16 and stretched (28 Aug 2026).
    """
    ratio = device_pixel_ratio() if dpr is None else max(1.0, float(dpr))
    key = (name, size, colour, ratio)
    hit = _cache.get(key)
    if hit is not None:
        return hit

    device_size = max(1, round(size * ratio))
    device = QPixmap(device_size, device_size)
    device.setDevicePixelRatio(ratio)
    device.fill(Qt.GlobalColor.transparent)
    painter = QPainter(device)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    scale = size / GRID
    painter.scale(scale, scale)

    path = QPainterPath()
    if name in FILLED:
        FILLED[name](path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colour))
    elif name in STROKED:
        STROKED[name](path)
        pen = QPen(QColor(colour), STROKE)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
    else:
        painter.end()
        raise KeyError("no icon called " + repr(name))
    painter.drawPath(path)
    painter.end()

    _cache[key] = device
    return device


def icon(name: str, size: int, colour: str, *, disabled: str | None = None) -> QIcon:
    """A QIcon with its normal and disabled faces already drawn."""
    result = QIcon(pixmap(name, size, colour))
    if disabled:
        result.addPixmap(pixmap(name, size, disabled), QIcon.Mode.Disabled)
    return result


def names() -> tuple[str, ...]:
    return tuple(sorted(set(FILLED) | set(STROKED)))


def size_hint(size: int) -> QSize:
    return QSize(size, size)
