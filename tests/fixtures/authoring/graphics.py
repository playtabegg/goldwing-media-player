"""Turn button artwork into the palette-indexed form an IG stream wants.

Blu-ray graphics are 8-bit indexed with a 256-entry YCbCr+alpha palette. Flat
button fills are one colour each; what blows the budget is the antialiasing on
the text, so the quantiser keeps the 255 most-used colours across every bitmap
in the menu and snaps the rest to the nearest one. Edges lose a little; the
fills, which is what anyone sees, stay exact.
"""

from __future__ import annotations

from collections import Counter

from PIL import Image, ImageDraw, ImageFont

from .hdmv import GraphicObject, Palette

#: Palette entry 0 is the transparent one, by convention and by the RLE's
#: preference for short runs of it.
TRANSPARENT = 0

#: 255 colours plus the transparent entry fills the palette.
MAX_COLOURS = 255

Rgba = tuple[int, int, int, int]


def rgb_to_ycbcr(red: int, green: int, blue: int) -> tuple[int, int, int]:
    """BT.709 limited range, which is what HD Blu-ray graphics use."""
    luma = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    y = 16 + luma * 219 / 255
    cb = 128 + (blue - luma) * 0.5389 * 224 / 255
    cr = 128 + (red - luma) * 0.6350 * 224 / 255
    return (
        max(0, min(255, round(y))),
        max(0, min(255, round(cb))),
        max(0, min(255, round(cr))),
    )


class MenuPalette:
    """One palette shared by every bitmap in a menu.

    Two passes: ``add`` every image, then ``build`` the palette, then
    ``quantise`` each image against it. Sharing matters — a button's normal
    and selected states have to index into the same palette, because a page
    has exactly one.
    """

    def __init__(self) -> None:
        self._counts: Counter[Rgba] = Counter()
        self._images: list[tuple[int, Image.Image]] = []
        self._index: dict[Rgba, int] = {}
        self._colours: list[Rgba] = []

    def add(self, object_id: int, image: Image.Image) -> None:
        rgba = image.convert("RGBA")
        self._images.append((object_id, rgba))
        for pixel in rgba.getdata():
            self._counts[pixel if pixel[3] else (0, 0, 0, 0)] += 1

    def build(self) -> None:
        self._colours = [(0, 0, 0, 0)]
        for colour, _count in self._counts.most_common():
            if colour == (0, 0, 0, 0) or len(self._colours) > MAX_COLOURS:
                continue
            self._colours.append(colour)
        self._index = {colour: index for index, colour in enumerate(self._colours)}

    def _nearest(self, colour: Rgba) -> int:
        if colour[3] == 0:
            return TRANSPARENT
        found = self._index.get(colour)
        if found is not None:
            return found
        best_index, best_distance = TRANSPARENT, None
        for index, candidate in enumerate(self._colours):
            distance = sum((a - b) ** 2 for a, b in zip(colour, candidate, strict=True))
            if best_distance is None or distance < best_distance:
                best_index, best_distance = index, distance
        self._index[colour] = best_index
        return best_index

    def objects(self) -> list[GraphicObject]:
        """Every added image, quantised, in the order they were added."""
        if not self._colours:
            self.build()
        out: list[GraphicObject] = []
        for object_id, image in self._images:
            width, height = image.size
            pixels = list(image.getdata())
            rows = [
                [self._nearest(pixels[y * width + x]) for x in range(width)]
                for y in range(height)
            ]
            out.append(
                GraphicObject(object_id=object_id, width=width, height=height, rows=rows)
            )
        return out

    def palette(self, palette_id: int = 0) -> Palette:
        if not self._colours:
            self.build()
        entries: dict[int, tuple[int, int, int, int]] = {}
        for index, (red, green, blue, alpha) in enumerate(self._colours):
            y, cb, cr = rgb_to_ycbcr(red, green, blue)
            # A palette entry is (Y, Cr, Cb, T) — chroma the other way round
            # from the usual triple, which is an easy hour to lose.
            entries[index] = (y, cr, cb, alpha)
        return Palette(palette_id=palette_id, entries=entries)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def button_bitmap(
    label: str,
    *,
    width: int = 460,
    height: int = 84,
    selected: bool = False,
) -> Image.Image:
    """A plain rectangular button, dim when normal and bright when selected."""
    fill = (238, 232, 214, 255) if selected else (28, 32, 44, 220)
    border = (238, 232, 214, 255) if selected else (150, 140, 116, 255)
    text = (18, 20, 28, 255) if selected else (238, 232, 214, 255)

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, width - 1, height - 1], fill=fill, outline=border, width=3)
    font = _font(34)
    box = draw.textbbox((0, 0), label, font=font)
    draw.text(
        ((width - (box[2] - box[0])) // 2, (height - (box[3] - box[1])) // 2 - box[1]),
        label,
        font=font,
        fill=text,
    )
    return image


def menu_background(width: int = 1280, height: int = 720) -> Image.Image:
    """The still the menu clip is made of."""
    image = Image.new("RGB", (width, height), (18, 20, 28))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, width - 1, height - 1], outline=(96, 86, 62), width=8)
    draw.text((110, 90), "WE THE INDIES", font=_font(44), fill=(232, 226, 210))
    draw.text((110, 150), "menu test disc", font=_font(30), fill=(150, 140, 116))
    return image
