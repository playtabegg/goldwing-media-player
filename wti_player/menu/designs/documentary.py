"""Documentary: a contact strip and a contents page.

The still is not a backdrop here, it is evidence. It runs across the top as a
strip of 35mm - three consecutive frames, sprocket holes top and bottom - and
the buttons underneath are a numbered contents list on a technical ground.

The old version of this theme was the one that looked worst with real
artwork: small grey monospace over a busy grey photograph, and the contrast
check reported that nothing needed doing. Nothing here sits on the picture.
"""

from __future__ import annotations

from typing import Any

from wti_player.menu import fonts, paint
from wti_player.menu.designs.base import Composition, Design, Scene, Slot, set_labels
from wti_player.menu.surface import Surface
from wti_player.menu.types import MENU_HEIGHT, MENU_WIDTH

GROUND = "#101315"
GRID = "#171B1E"
GRID_HEAVY = "#1E2429"
STRIP = "#08090A"
FRAME_EMPTY = "#171C20"
FRAME_EDGE = "#2A3238"
HOLE = "#1D2327"
INK = "#E9EDEF"
#: The row numbers. Lifted twice: #6E7A80 measured 4.47:1 on the flat
#: ground and #7C888E 4.71:1 where a heavy grid line runs behind a
#: number, which is the pixel the check looks at and the eye does too.
DIM = "#8D999F"
CYAN = "#4FB3D9"

STRIP_TOP = 118
RAIL = 34
FRAME_HEIGHT = 266
GUTTER = 14
#: Full title-safe width. A contents page rules right across the page,
#: and a column two thirds of the way over left the frame lopsided.
BUTTON_WIDTH = 1728
ROW_HEIGHT = 66


class Documentary(Design):
    key = "documentary"
    name = "Documentary"
    description = "Three frames of the film as a contact strip, over a numbered contents list."
    references = (
        "A strip on a light box: perforations are what make film recognisable.",
        "The list is a record, not a product. Numbers, rules, no ornament.",
    )
    backing = GROUND

    def compose(self, scene: Scene) -> Composition:
        surface = Surface((MENU_WIDTH, MENU_HEIGHT), paint.rgba(GROUND))
        paint.hairline_grid(
            surface.draw,
            (0, 0, MENU_WIDTH, MENU_HEIGHT),
            step=60,
            colour=paint.rgba(GRID),
            heavy_every=5,
            heavy_colour=paint.rgba(GRID_HEAVY),
        )
        used = self._strip(surface, scene.art("still"))
        self._title(surface, scene)
        surface.image = paint.grain(surface.image, amount=0.07, seed=scene.seed + 31)
        return Composition(surface, tuple(self._buttons(scene)), used)

    def _strip(self, surface: Surface, art: Any) -> bool:
        from PIL import Image, ImageDraw

        left, right = 96, 1824
        frame_top = STRIP_TOP + RAIL
        frame_bottom = frame_top + FRAME_HEIGHT
        strip_bottom = frame_bottom + RAIL
        draw = surface.draw
        draw.rectangle([left, STRIP_TOP, right, strip_bottom], fill=paint.rgba(STRIP))
        paint.sprocket_rail(
            draw,
            (left, STRIP_TOP, right, frame_top),
            rail=paint.rgba(STRIP),
            hole=paint.rgba(HOLE),
            pitch=58,
            hole_width=26,
            hole_height=15,
        )
        paint.sprocket_rail(
            draw,
            (left, frame_bottom, right, strip_bottom),
            rail=paint.rgba(STRIP),
            hole=paint.rgba(HOLE),
            pitch=58,
            hole_width=26,
            hole_height=15,
        )

        span = right - left
        width = (span - GUTTER * 2) // 3
        for index, focus in enumerate((0.14, 0.5, 0.86)):
            x = left + index * (width + GUTTER)
            box = (x, frame_top, x + width, frame_bottom)
            if art is not None:
                cell = paint.crop_fill(art, (width, FRAME_HEIGHT), focus=focus)
            else:
                cell = Image.new("RGBA", (width, FRAME_HEIGHT), paint.rgba(FRAME_EMPTY))
                paint.registration(
                    ImageDraw.Draw(cell),
                    (width // 2, FRAME_HEIGHT // 2),
                    size=48,
                    colour=paint.rgba(FRAME_EDGE),
                )
            surface.paste(cell, (x, frame_top))
            paint.keyline(draw, box, paint.rgba(FRAME_EDGE))
        return art is not None

    def _title(self, surface: Surface, scene: Scene) -> None:
        title = fonts.clean(scene.title)
        if not title:
            return
        block = fonts.fit(
            title.upper(),
            family="ui",
            weight=600,
            max_width=1728,
            max_height=132,
            max_lines=2,
            size=58,
            min_size=30,
            tracking=0.05,
            leading=1.08,
        )
        surface.block(
            (96, 506),
            block.lines,
            block.font,
            paint.rgb(INK),
            leading=block.leading,
            tracking=block.tracking,
            large=True,
        )
        rule_y = 506 + block.height + 26
        surface.draw.rectangle([96, rule_y, 1824, rule_y + 2], fill=paint.rgba(FRAME_EDGE))

    def _buttons(self, scene: Scene) -> list[Slot]:
        labels = [fonts.clean(button.label, fallback=button.key).upper() for button in scene.buttons]
        chosen = set_labels(
            labels,
            family="ui",
            weight=400,
            max_width=BUTTON_WIDTH - 200,
            size=30,
            min_size=19,
            tracking=0.04,
        )
        height = max(ROW_HEIGHT, chosen.text_height + 30)
        top = 1020 - height * len(scene.buttons)
        return [
            Slot(
                key=button.key,
                label=" ".join(chosen.lines[index]),
                x=96,
                y=top + index * height,
                width=BUTTON_WIDTH,
                height=height,
                paint=self._painter(chosen, chosen.lines[index], index + 1),
            )
            for index, button in enumerate(scene.buttons)
        ]

    def _painter(self, chosen: Any, lines: tuple[str, ...], number: int) -> Any:
        index_font = fonts.face("ui", max(16, int(chosen.size * 0.78)), 500)

        def draw_button(tile: Surface, state: str) -> None:
            width, height = tile.size
            ink, dim, leader = paint.rgb(INK), paint.rgb(DIM), paint.rgba("#232B30")
            if state == "selected":
                tile.draw.rectangle([0, 0, width, height], fill=paint.rgba(INK))
                ink, dim, leader = paint.rgb(GROUND), paint.rgb("#57646B"), paint.rgba("#B7C1C6")
            elif state == "activated":
                tile.draw.rectangle([0, 0, width, height], fill=paint.rgba(CYAN))
                ink, dim, leader = paint.rgb("#05171E"), paint.rgb("#0C3546"), paint.rgba("#2C7E9C")
            else:
                tile.draw.rectangle(
                    [0, height - 1, width - 1, height - 1], fill=paint.rgba("#1D2429")
                )
            text_top = (height - chosen.text_height) // 2
            tile.text((22, text_top + 4), f"{number:02d}", index_font, dim, tracking=0.08)
            tile.block(
                (96, text_top),
                list(lines),
                chosen.font,
                ink,
                leading=chosen.leading,
                tracking=chosen.tracking,
            )
            # A leader from the end of the last line to the right edge, the
            # way a contents page runs one out to a page number.
            end = 96 + int(fonts.width(lines[-1], chosen.font, chosen.tracking))
            baseline = text_top + chosen.leading * (len(lines) - 1) + int(chosen.size * 0.72)
            for dot in range(end + 24, width - 26, 12):
                tile.draw.rectangle([dot, baseline, dot + 2, baseline + 1], fill=leader)

        return draw_button


DESIGN = Documentary()
