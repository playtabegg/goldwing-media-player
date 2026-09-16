"""Measured contrast, over the pixels a label actually covers.

The old renderer averaged the colour of a button's whole rectangle and
compared that to the label colour. On a flat ground that is right. On a
photograph it is worthless: grey type on a busy grey still averages to
something that passes while every glyph disappears into it. That render
reported ``local_scrim 0.00`` and shipped four unreadable buttons.

This takes the glyph mask, composites whatever was under it, and reduces the
result to its distinct colours - a few dozen, not a million - so the worst
one can be found exactly rather than averaged away.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from wti_player.menu.surface import Ink

#: sRGB channel to linear light, one entry per byte value. The transform is
#: three floating-point operations and this is called a few hundred thousand
#: times per render.
_LINEAR = tuple(
    (value / 255 / 12.92) if value / 255 <= 0.04045 else (((value / 255) + 0.055) / 1.055) ** 2.4
    for value in range(256)
)

#: How much of a pixel has to be inside a glyph before it counts. Antialiased
#: edges are half background by definition and would fail everything.
SOLID = 200

#: What to fall back to when hairline type never reaches SOLID anywhere.
THIN = (140, 90, 40)


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG relative luminance of an sRGB colour."""
    r, g, b = rgb[0], rgb[1], rgb[2]
    return 0.2126 * _LINEAR[r] + 0.7152 * _LINEAR[g] + 0.0722 * _LINEAR[b]


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """WCAG contrast between two colours. 1.0 identical, 21.0 black on white."""
    first, second = relative_luminance(a), relative_luminance(b)
    lighter, darker = (first, second) if first >= second else (second, first)
    return (lighter + 0.05) / (darker + 0.05)


def _solid_mask(mask: Any, threshold: int) -> Any:
    return mask.point(lambda value: 255 if value >= threshold else 0)


def measure(ink: Ink, beneath: Any) -> float:
    """Worst contrast of one text run against what is behind every glyph pixel.

    ``beneath`` is the RGBA image the run's ``backing`` sits on - the menu
    background for type drawn straight onto it, or the background under a
    button tile for type inside one. Composited here rather than passed in
    already flattened, because a button tile is transparent everywhere its
    design does not paint and the background shows through those parts.
    """
    from PIL import Image

    under = ink.backing
    if beneath is not None:
        under = Image.alpha_composite(beneath.convert("RGBA"), ink.backing)
    under = under.convert("RGB")

    for threshold in (SOLID, *THIN):
        solid = _solid_mask(ink.mask, threshold)
        sampled = under.copy()
        sampled.putalpha(solid)
        colours = sampled.getcolors(maxcolors=1 << 22)
        if colours is None:  # pragma: no cover - only past 4M distinct colours
            colours = [(1, (*under.resize((1, 1)).getpixel((0, 0)), 255))]
        opaque = [rgba[:3] for _count, rgba in colours if rgba[3] == 255]
        if opaque:
            return min(contrast_ratio(ink.colour, colour) for colour in opaque)
    return 21.0


def worst(
    inks: list[Ink],
    beneath_for: Callable[[Ink], Any],
    *,
    large: bool,
) -> tuple[float, str]:
    """The least readable run in a list, and what it said.

    ``beneath_for`` returns what sits under one run - None for type drawn
    straight onto an opaque background, and the matching crop of the menu
    background for type inside a transparent button tile. It is a callback
    because each run needs a different crop and cropping all of them up front
    is most of the work of the check.

    Split by size class: WCAG asks 4.5:1 of body text and 3:1 of large text,
    and a title at 90px is unambiguously the second. Reporting them together
    would let one big word carry a small unreadable one.
    """
    chosen = [ink for ink in inks if ink.large is large]
    if not chosen:
        return (21.0, "")
    scored = [(measure(ink, beneath_for(ink)), ink.text) for ink in chosen]
    return min(scored, key=lambda pair: pair[0])


__all__ = ["SOLID", "contrast_ratio", "measure", "relative_luminance", "worst"]
