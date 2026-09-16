"""Render one menu: a background picture and three pictures per button.

That is all a Blu-ray menu is. The player owns a rectangle per button and
swaps the picture inside it as somebody moves a remote; it does not
composite, scale or blend. So each state has to be a whole picture of that
button, and the three have to be the same size.

The signature is the factory's, on purpose, so ``rialto2`` can change one
import and keep its call sites.

What is new is the gate at the end. Every run of type that went onto the
frame is measured against the pixels actually under it, and a menu that
cannot be read does not get returned - it either gets its backing reinforced
until it can be, or it raises.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from wti_player.menu import contrast, designs, paint
from wti_player.menu.designs.base import Composition, Scene, Slot
from wti_player.menu.surface import Ink, Surface
from wti_player.menu.types import (
    BUTTON_STATES,
    MENU_HEIGHT,
    MENU_WIDTH,
    MIN_CONTRAST,
    MIN_LARGE_CONTRAST,
    Button,
    ContrastFailure,
    RenderedButton,
    RenderedMenu,
    safe_box,
)

#: How hard the backing behind the buttons is allowed to be reinforced, if a
#: design ever needs it. All six put their labels on stock rather than on the
#: picture, so on everything rendered so far this stays at 0.0.
REINFORCEMENT = (0.35, 0.55, 0.75, 0.90)

#: Fixed, so two renders of the same menu are the same file. A texture seeded
#: off the clock makes a visual diff useless.
SEED = 1968


def render_menu(
    buttons: list[Button],
    out_dir: Path,
    *,
    theme_key: str,
    title: str = "",
    poster: Path | None = None,
    still: Path | None = None,
    seed: int = SEED,
) -> RenderedMenu:
    """Render one menu into ``out_dir``. Returns where everything landed.

    ``poster`` and ``still`` are the film's own art and both may be absent.
    Every design uses whichever it is given - the old renderer keyed off a
    per-theme backdrop name and five of the six silently ignored a still -
    and every design has a deliberate look with neither.
    """
    if not buttons:
        raise ValueError("a menu with no buttons is not a menu")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    design = designs.design(theme_key)
    scene = Scene(
        title=title,
        buttons=tuple(buttons),
        still=paint.load(still),
        poster=paint.load(poster),
        seed=seed,
    )
    composition = design.compose(scene)
    _check_title_safe(composition, design.key)

    display, display_says = contrast.worst(
        composition.background.inks, lambda _ink: None, large=True
    )
    if display < MIN_LARGE_CONTRAST:
        raise ContrastFailure(
            f"{design.key}: the display type {display_says!r} measures {display:.2f}:1 "
            f"against what is behind it, and large text needs {MIN_LARGE_CONTRAST}:1"
        )

    tiles, scores, strength = _paint_buttons(composition, design)

    background_path = out_dir / "menu_background.png"
    composition.background.rgb().save(background_path, "PNG")

    rendered: list[RenderedButton] = []
    for slot, states, score in zip(composition.slots, tiles, scores, strict=True):
        images: dict[str, Path] = {}
        for state, tile in states.items():
            path = out_dir / f"button_{slot.key}_{state}.png"
            tile.image.save(path, "PNG")
            images[state] = path
        rendered.append(
            RenderedButton(
                key=slot.key,
                label=slot.label,
                x=slot.x,
                y=slot.y,
                width=slot.width,
                height=slot.height,
                images=images,
                contrast=round(score, 2),
            )
        )

    return RenderedMenu(
        background=background_path,
        buttons=tuple(rendered),
        theme_key=design.key,
        local_scrim=strength,
        contrast=round(min(scores), 2) if scores else 0.0,
        display_contrast=round(display, 2),
        used_artwork=composition.used_artwork,
        labels=tuple(slot.label for slot in composition.slots),
    )


# ---------------------------------------------------------------------------


def _paint_buttons(
    composition: Composition, design: Any
) -> tuple[list[dict[str, Surface]], list[float], float]:
    """Draw every button in every state, and make sure it can be read.

    Reinforcement, if it is ever needed, is applied to the background under
    the button block and the whole set is redrawn and re-measured against it.
    Type outside that block - a title, a caption - was measured before this
    runs, which is safe because no design puts a button box over its own
    display type.
    """
    base = composition.background.image.copy()
    for level in (0.0, *REINFORCEMENT):
        if level:
            composition.background.image = base.copy()
            _reinforce(composition, design, level)
        tiles = [_paint_one(slot) for slot in composition.slots]
        scores = [_score(slot, states, composition) for slot, states in zip(composition.slots, tiles, strict=True)]
        if min(scores) >= MIN_CONTRAST:
            return tiles, scores, level
    worst_at = min(
        zip(scores, [slot.label for slot in composition.slots], strict=True), key=lambda p: p[0]
    )
    raise ContrastFailure(
        f"{design.key}: {worst_at[1]!r} measures {worst_at[0]:.2f}:1 against what is "
        f"behind it, and reinforcing the backing to {REINFORCEMENT[-1]:.0%} did not "
        f"reach {MIN_CONTRAST}:1"
    )


def _paint_one(slot: Slot) -> dict[str, Surface]:
    tiles: dict[str, Surface] = {}
    for state in BUTTON_STATES:
        tile = Surface((slot.width, slot.height))
        slot.paint(tile, state)
        tiles[state] = tile
    return tiles


def _score(slot: Slot, tiles: dict[str, Surface], composition: Composition) -> float:
    """The worst contrast this button reaches in any of its three states."""
    background = composition.background.image

    def beneath_for(ink: Ink) -> Any:
        left, top, right, bottom = ink.box
        return background.crop((slot.x + left, slot.y + top, slot.x + right, slot.y + bottom))

    return min(
        contrast.worst(tile.inks, beneath_for, large=False)[0] for tile in tiles.values()
    )


def _reinforce(composition: Composition, design: Any, level: float) -> None:
    """Deepen the design's own backing colour behind the button block.

    In the design's colour, not a black scrim: a menu that has been rescued
    with a grey rectangle looks rescued. Feathered well past the block so the
    edge of the correction never shows.
    """
    from PIL import Image, ImageDraw, ImageFilter

    left = min(slot.x for slot in composition.slots) - 40
    top = min(slot.y for slot in composition.slots) - 40
    right = max(slot.x + slot.width for slot in composition.slots) + 40
    bottom = max(slot.y + slot.height for slot in composition.slots) + 40
    veil = Image.new("RGBA", (MENU_WIDTH, MENU_HEIGHT), (0, 0, 0, 0))
    mask = Image.new("L", (MENU_WIDTH, MENU_HEIGHT), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [left, top, right, bottom], radius=28, fill=int(255 * level)
    )
    veil.paste((*paint.rgb(design.backing), 255), (0, 0), mask.filter(ImageFilter.GaussianBlur(30)))
    composition.background.image.alpha_composite(veil)


def _check_title_safe(composition: Composition, key: str) -> None:
    """No button may sit where a television might crop it."""
    left, top, right, bottom = safe_box()
    for slot in composition.slots:
        if (
            slot.x < left
            or slot.y < top
            or slot.x + slot.width > right
            or slot.y + slot.height > bottom
        ):
            raise ValueError(
                f"{key}: button {slot.key!r} at "
                f"({slot.x}, {slot.y}, {slot.width}x{slot.height}) is outside the "
                f"title-safe area {(left, top, right, bottom)}"
            )


__all__ = ["REINFORCEMENT", "SEED", "render_menu"]
