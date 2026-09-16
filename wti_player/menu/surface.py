"""A drawing surface that remembers where it put ink.

The point of this is the contrast check. To know whether a label can be read
you need three things: the colour of the glyphs, the exact pixels they cover,
and what was underneath at the moment they were drawn. Sampling the average
colour of a button's rectangle - what the old renderer did - gives none of
them, which is how "local_scrim 0.00" and grey-on-grey shipped together.

So every text run goes through :meth:`Surface.text`, which draws the glyphs
into a mask, keeps a crop of what was beneath, and then pastes the colour
through that mask. The pixels measured later are the pixels drawn, not an
approximation of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from wti_player.menu.fonts import width as text_width
from wti_player.menu.types import RenderUnavailable


def _pillow() -> Any:
    try:
        from PIL import Image, ImageDraw

        return Image, ImageDraw
    except ImportError as exc:  # pragma: no cover - Pillow is a dependency here
        raise RenderUnavailable(
            "Pillow is not installed, and the menu renderer is built on it. "
            "pip install pillow"
        ) from exc


@dataclass(frozen=True)
class Ink:
    """One run of text, kept so it can be measured.

    ``backing`` is a crop of the surface as it was before the glyphs landed,
    which is not always the same as the finished surface: a selected button
    paints a solid block and then knocks the label out of it, and the block
    is what the label has to be read against.
    """

    #: ``(left, top, right, bottom)`` in surface coordinates.
    box: tuple[int, int, int, int]
    #: Coverage, box-sized, 0-255. 255 is a pixel wholly inside a glyph.
    mask: Any
    #: What the glyphs were painted in.
    colour: tuple[int, int, int]
    #: The surface under the glyphs, box-sized, RGBA.
    backing: Any
    #: Display type gets WCAG's large-text ratio rather than body text's.
    large: bool = False
    #: For the report, when a check fails.
    text: str = ""


class Surface:
    """An RGBA image, a draw handle, and a record of the type on it."""

    def __init__(self, size: tuple[int, int], fill: tuple[int, int, int, int] = (0, 0, 0, 0)):
        Image, _draw = _pillow()
        self.size = size
        self.inks: list[Ink] = []
        self.image = Image.new("RGBA", size, fill)

    @property
    def image(self) -> Any:
        return self._image

    @image.setter
    def image(self, value: Any) -> None:
        """Swapping the image re-binds the draw handle.

        Whole-frame effects - grain, a vignette - return a new image rather
        than mutating one, and a design that assigned the result then kept
        drawing through the old handle was drawing onto an orphan. Nothing
        appeared and nothing failed.
        """
        _image, ImageDraw = _pillow()
        self._image = value
        self.draw = ImageDraw.Draw(value)

    # -- type ---------------------------------------------------------------

    def text(
        self,
        xy: tuple[int, int],
        content: str,
        font: Any,
        colour: tuple[int, int, int],
        *,
        tracking: float = 0.0,
        align: str = "left",
        large: bool = False,
    ) -> int:
        """Draw one line. Returns the width it used.

        ``align`` positions against ``xy[0]``: ``left`` starts there,
        ``centre`` centres on it, ``right`` ends there. Alignment is done here
        rather than with Pillow's anchors because tracked text is drawn glyph
        by glyph and the anchors measure the untracked run.
        """
        Image, ImageDraw = _pillow()
        if not content:
            return 0
        run = int(text_width(content, font, tracking))
        x, y = xy
        if align == "centre":
            x -= run // 2
        elif align == "right":
            x -= run
        mask = Image.new("L", self.size, 0)
        _tracked(ImageDraw.Draw(mask), (x, y), content, font, 255, tracking)
        box = mask.getbbox()
        if box is None:
            return run
        backing = self.image.crop(box).copy()
        self.image.paste((*colour, 255), box, mask.crop(box))
        self.inks.append(
            Ink(
                box=box,
                mask=mask.crop(box),
                colour=colour,
                backing=backing,
                large=large,
                text=content,
            )
        )
        return run

    def block(
        self,
        xy: tuple[int, int],
        lines: list[str],
        font: Any,
        colour: tuple[int, int, int],
        *,
        leading: int,
        tracking: float = 0.0,
        align: str = "left",
        large: bool = False,
    ) -> int:
        """Draw a wrapped block from :func:`fonts.fit`. Returns its height."""
        y = xy[1]
        for line in lines:
            self.text((xy[0], y), line, font, colour, tracking=tracking, align=align, large=large)
            y += leading
        return y - xy[1]

    # -- everything else ----------------------------------------------------

    def paste(self, source: Any, at: tuple[int, int]) -> None:
        """Composite an RGBA image on top, respecting its alpha."""
        self.image.alpha_composite(source, at)

    def crop(self, box: tuple[int, int, int, int]) -> Any:
        return self.image.crop(box)

    def rgb(self) -> Any:
        return self.image.convert("RGB")


def _tracked(
    draw: Any,
    xy: tuple[int, int],
    content: str,
    font: Any,
    fill: Any,
    tracking: float,
) -> None:
    """Text with letter-spacing. Pillow has none, and menus are all tracked.

    Drawn in one call when there is no tracking, because per-glyph drawing
    throws away kerning.
    """
    x, y = xy
    if not tracking:
        draw.text((x, y), content, font=font, fill=fill, anchor="la")
        return
    extra = font.size * tracking
    cursor = float(x)
    for character in content:
        draw.text((cursor, y), character, font=font, fill=fill, anchor="la")
        cursor += font.getlength(character) + extra


__all__ = ["Ink", "Surface"]
