"""Materials. The parts of a printed thing that a flat fill cannot fake.

Every design in this package is built out of these: paper with a grain in it,
a keyline, a plate with a shadow under it, a strip of film with sprocket
holes, a screen-printed duotone. They are here rather than in the designs
because six designs sharing one set of materials is what makes them look like
six pieces of one system instead of six unrelated pictures.

Everything is deterministic. A texture seeded off the clock means two renders
of the same menu differ, which makes a visual diff useless and a regression
test impossible.
"""

from __future__ import annotations

import math
import random
from typing import Any

from wti_player.menu.types import RenderUnavailable

RGB = tuple[int, int, int]
RGBA = tuple[int, int, int, int]


def _pillow() -> Any:
    try:
        from PIL import Image, ImageChops, ImageDraw, ImageFilter

        return Image, ImageChops, ImageDraw, ImageFilter
    except ImportError as exc:  # pragma: no cover - Pillow is a dependency here
        raise RenderUnavailable(
            "Pillow is not installed, and the menu renderer is built on it. "
            "pip install pillow"
        ) from exc


# ---------------------------------------------------------------------------
# Colour
# ---------------------------------------------------------------------------


def rgb(value: str) -> RGB:
    """``#rgb`` or ``#rrggbb`` to a triple."""
    return rgba(value)[:3]


def rgba(value: str, alpha: int | None = None) -> RGBA:
    """``#rgb``, ``#rrggbb`` or ``#rrggbbaa`` to a quadruple."""
    text = value.lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) == 6:
        text += "ff"
    if len(text) != 8 or any(ch not in "0123456789abcdefABCDEF" for ch in text):
        # Checked before int(): "red" doubles to "rreedd", reaches the right
        # length, and would fail naming the wrong problem.
        raise ValueError(f"{value!r} is not a colour")
    out = tuple(int(text[i : i + 2], 16) for i in (0, 2, 4, 6))
    if alpha is not None:
        return (out[0], out[1], out[2], alpha)
    return out  # type: ignore[return-value]


def mix(a: RGB, b: RGB, t: float) -> RGB:
    """``t`` of the way from ``a`` to ``b``."""
    t = max(0.0, min(1.0, t))
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def dominant(art: Any) -> RGB:
    """The colour a piece of artwork mostly is.

    A 16x16 average, not the modal pixel: a poster that is 40 percent black
    sky has black as its mode and is not a black poster.
    """
    small = art.convert("RGB").resize((16, 16))
    pixels = list(small.getdata())
    count = len(pixels)
    return (
        sum(p[0] for p in pixels) // count,
        sum(p[1] for p in pixels) // count,
        sum(p[2] for p in pixels) // count,
    )


# ---------------------------------------------------------------------------
# Artwork
# ---------------------------------------------------------------------------


def load(path: Any) -> Any | None:
    """Open a piece of artwork as RGBA, or None if it is not one.

    Artwork comes off a web form. A .png that is really a renamed .txt is a
    normal thing to receive and not a reason for a disc not to get pressed.
    """
    Image, _chops, _draw, _filter = _pillow()
    if path is None:
        return None
    try:
        with Image.open(path) as art:
            return art.convert("RGBA")
    except (OSError, ValueError):
        return None


def crop_fill(art: Any, size: tuple[int, int], *, focus: float = 0.5) -> Any:
    """Cover ``size``, cropping rather than squashing.

    ``focus`` slides the crop window across the long axis, 0.0 to 1.0. The
    documentary filmstrip uses it to take three different frames out of one
    still so the strip reads as consecutive exposures.
    """
    Image, _chops, _draw, _filter = _pillow()
    want_w, want_h = max(1, size[0]), max(1, size[1])
    scale = max(want_w / art.width, want_h / art.height)
    scaled = art.resize((max(1, round(art.width * scale)), max(1, round(art.height * scale))), Image.LANCZOS)
    spare_x = scaled.width - want_w
    spare_y = scaled.height - want_h
    left = int(spare_x * focus) if spare_x else 0
    top = int(spare_y * (0.5 if spare_x else focus)) if spare_y else 0
    return scaled.crop((left, top, left + want_w, top + want_h))


def scaled(art: Any, size: tuple[int, int]) -> Any:
    """Resize with the good filter, without every caller naming it."""
    Image, _chops, _draw, _filter = _pillow()
    return art.resize((max(1, int(size[0])), max(1, int(size[1]))), Image.LANCZOS)


def duotone(art: Any, shadow: RGB, mid: RGB, light: RGB, *, levels: int = 3) -> Any:
    """Flatten a photograph into two or three inks.

    A screen-printed poster is not a photograph with a dark rectangle over
    it, and this is the difference. It also makes the result measurable: the
    picture afterwards contains only the colours named here, so anything set
    over it has a contrast that can be worked out rather than sampled and
    hoped about.
    """
    Image, _chops, _draw, ImageFilter = _pillow()
    from PIL import ImageOps

    # Stretched to the full range first. A still that lives between 40 and 120
    # posterises into one ink and comes out as a flat rectangle.
    grey = ImageOps.autocontrast(art.convert("L").filter(ImageFilter.SMOOTH), cutoff=2)
    step = 255 / max(1, levels - 1)
    ramp = [shadow, mid, light][:levels] if levels <= 3 else None
    if ramp is None:  # pragma: no cover - designs use two or three
        ramp = [mix(shadow, light, i / (levels - 1)) for i in range(levels)]
    table_r, table_g, table_b = [], [], []
    for value in range(256):
        index = min(levels - 1, int(value / step + 0.5))
        colour = ramp[index]
        table_r.append(colour[0])
        table_g.append(colour[1])
        table_b.append(colour[2])
    flat = Image.merge(
        "RGB",
        (grey.point(table_r), grey.point(table_g), grey.point(table_b)),
    )
    return flat.convert("RGBA")


def monochrome(art: Any, dark: RGB, light: RGB) -> Any:
    """Map a photograph onto a two-colour ramp, keeping its tones."""
    Image, _chops, _draw, _filter = _pillow()
    grey = art.convert("L")
    table_r = [mix(dark, light, v / 255)[0] for v in range(256)]
    table_g = [mix(dark, light, v / 255)[1] for v in range(256)]
    table_b = [mix(dark, light, v / 255)[2] for v in range(256)]
    return Image.merge(
        "RGB", (grey.point(table_r), grey.point(table_g), grey.point(table_b))
    ).convert("RGBA")


# ---------------------------------------------------------------------------
# Texture
# ---------------------------------------------------------------------------


def _noise(size: tuple[int, int], seed: int) -> Any:
    Image, _chops, _draw, _filter = _pillow()
    generator = random.Random(seed)
    return Image.frombytes("L", size, generator.randbytes(size[0] * size[1]))


def grain(image: Any, *, amount: float = 0.10, seed: int = 1968, softness: float = 0.0) -> Any:
    """Print grain. Returns a new RGBA image.

    Flat digital fills are the thing that makes a rendered menu look
    rendered. Two percent of tonal wobble is below the threshold anyone can
    name and above the one they can feel.
    """
    _image, ImageChops, _draw, ImageFilter = _pillow()
    size = image.size
    speckle = _noise(size, seed)
    if softness:
        speckle = speckle.filter(ImageFilter.GaussianBlur(softness))
    levelled = speckle.point([int(128 + (v - 128) * amount) for v in range(256)])
    body = image.convert("RGB")
    grained = ImageChops.overlay(body, levelled.convert("RGB"))
    out = grained.convert("RGBA")
    out.putalpha(image.getchannel("A") if image.mode == "RGBA" else 255)
    return out


def vignette(image: Any, *, strength: float = 0.35, colour: RGB = (0, 0, 0)) -> Any:
    """Darken toward the corners. Returns a new RGBA image."""
    Image, _chops, _draw, _filter = _pillow()
    if strength <= 0:
        return image
    gradient = Image.radial_gradient("L").resize(image.size, Image.BILINEAR)
    veil = Image.new("RGBA", image.size, (*colour, 0))
    veil.putalpha(gradient.point([int(v * strength) for v in range(256)]))
    out = image.copy()
    out.alpha_composite(veil)
    return out


def line_screen(
    size: tuple[int, int],
    *,
    spacing: int = 7,
    angle: float = 45.0,
    colour: RGB = (0, 0, 0),
    alpha: int = 40,
    thickness: int = 2,
) -> Any:
    """A diagonal line screen, as a transparent overlay.

    What a screen-printed poster has instead of a smooth gradient. Cheap:
    a few hundred lines, not a per-pixel halftone.
    """
    Image, _chops, ImageDraw, _filter = _pillow()
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    reach = int((size[0] + size[1]) / max(1, math.cos(math.radians(angle))))
    dx = math.tan(math.radians(angle)) * size[1]
    for offset in range(-reach, reach, max(1, spacing)):
        draw.line(
            [(offset, 0), (offset + dx, size[1])],
            fill=(*colour, alpha),
            width=thickness,
        )
    return layer


def hairline_grid(
    draw: Any,
    box: tuple[int, int, int, int],
    *,
    step: int,
    colour: RGBA,
    heavy_every: int = 0,
    heavy_colour: RGBA | None = None,
) -> None:
    """Graph paper. Drawn straight onto a surface."""
    left, top, right, bottom = box
    index = 0
    x = left
    while x <= right:
        heavy = heavy_every and index % heavy_every == 0
        draw.line([(x, top), (x, bottom)], fill=heavy_colour if heavy else colour, width=1)
        x += step
        index += 1
    index = 0
    y = top
    while y <= bottom:
        heavy = heavy_every and index % heavy_every == 0
        draw.line([(left, y), (right, y)], fill=heavy_colour if heavy else colour, width=1)
        y += step
        index += 1


# ---------------------------------------------------------------------------
# Objects
# ---------------------------------------------------------------------------


def shadow(size: tuple[int, int], box: tuple[int, int, int, int], *, blur: int = 24,
           alpha: int = 110, offset: tuple[int, int] = (0, 14), radius: int = 0) -> Any:
    """A soft shadow under a plate, as its own layer.

    Composited under the plate rather than drawn on it, because a plate with
    a shadow painted into its own edges has a grey halo instead.
    """
    Image, _chops, ImageDraw, ImageFilter = _pillow()
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    shifted = (box[0] + offset[0], box[1] + offset[1], box[2] + offset[0], box[3] + offset[1])
    if radius:
        draw.rounded_rectangle(shifted, radius=radius, fill=(0, 0, 0, alpha))
    else:
        draw.rectangle(shifted, fill=(0, 0, 0, alpha))
    return layer.filter(ImageFilter.GaussianBlur(blur))


def keyline(draw: Any, box: tuple[int, int, int, int], colour: RGBA, thickness: int = 1) -> None:
    """A drawn border, inset so it lands inside ``box`` rather than astride it."""
    left, top, right, bottom = box
    for step in range(thickness):
        draw.rectangle(
            [left + step, top + step, right - 1 - step, bottom - 1 - step], outline=colour, width=1
        )


def sprocket_rail(
    draw: Any,
    box: tuple[int, int, int, int],
    *,
    rail: RGBA,
    hole: RGBA,
    pitch: int = 46,
    hole_width: int = 22,
    hole_height: int = 16,
) -> None:
    """One edge of 35mm film: a solid rail punched at a regular pitch.

    Perforations are the reason a strip of film is recognisable at a glance,
    and they are two rectangles and a loop.
    """
    left, top, right, bottom = box
    draw.rectangle([left, top, right, bottom], fill=rail)
    centre_y = (top + bottom) // 2
    x = left + pitch // 2
    while x + hole_width <= right:
        draw.rounded_rectangle(
            [x, centre_y - hole_height // 2, x + hole_width, centre_y + hole_height // 2],
            radius=3,
            fill=hole,
        )
        x += pitch


def registration(draw: Any, at: tuple[int, int], *, size: int, colour: RGBA, thickness: int = 2) -> None:
    """A printer's cross. Used where a design wants to look unfinished on purpose."""
    x, y = at
    half = size // 2
    draw.line([(x - half, y), (x + half, y)], fill=colour, width=thickness)
    draw.line([(x, y - half), (x, y + half)], fill=colour, width=thickness)
    draw.ellipse([x - half // 2, y - half // 2, x + half // 2, y + half // 2], outline=colour, width=thickness)


def notched_edge(
    draw: Any,
    x: int,
    top: int,
    bottom: int,
    *,
    colour: RGBA,
    pitch: int = 26,
    depth: int = 7,
) -> None:
    """A ticket stub's perforated edge: half-circles bitten out of a vertical line."""
    y = top
    while y <= bottom:
        draw.ellipse([x - depth, y - depth, x + depth, y + depth], fill=colour)
        y += pitch


__all__ = [
    "RGB",
    "RGBA",
    "crop_fill",
    "dominant",
    "duotone",
    "grain",
    "hairline_grid",
    "keyline",
    "line_screen",
    "load",
    "mix",
    "monochrome",
    "notched_edge",
    "registration",
    "rgb",
    "rgba",
    "scaled",
    "shadow",
    "sprocket_rail",
    "vignette",
]
