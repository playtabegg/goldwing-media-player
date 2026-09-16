"""Animation: a model sheet.

Animation paper is punched with three pegs, ruled in non-photo blue, and
carries a field guide showing what the camera will actually see. All three
are on this menu, and the last one is not decoration - the field guide is
drawn on the title-safe box, so the design says out loud where the edge of
the television is.

The buttons are pills, big, with a hard offset shadow. A child with a remote
is a real user of this theme, and so is a parent across the room.
"""

from __future__ import annotations

from typing import Any

from wti_player.menu import fonts, paint
from wti_player.menu.designs.base import Composition, Design, Scene, Slot, set_labels
from wti_player.menu.surface import Surface
from wti_player.menu.types import MENU_HEIGHT, MENU_WIDTH, safe_box

BOARD = "#FBF7EE"
BLUE = "#DCE9F2"
BLUE_HEAVY = "#C7DCEA"
GUIDE = "#B4CFE2"
PUNCH = "#E4DDCC"
PUNCH_EDGE = "#C6BDA6"
INK = "#2A2440"
PAPER = "#FFFFFF"
CREAM = "#FFF8EC"
YELLOW = "#FFD23F"
RED = "#F25C54"
MAT = "#F2EDE0"

CEL = (1000, 190, 1824, 760)
#: The pill's shadow lives inside its own tile, so all three states are the
#: same picture size. The HDMV writer will not take three that are not.
SHADOW = 10
ROW_HEIGHT = 92
ROW_GAP = 16


class Animation(Design):
    key = "animation"
    name = "Animation"
    description = "A punched model sheet in non-photo blue, with the art pegged on as a cel."
    references = (
        "Peg holes and a field guide: what an animator's paper actually looks like.",
        "Three states you can tell apart from the sofa: white, yellow, ink.",
    )
    backing = BOARD
    backing_is_light = True

    def compose(self, scene: Scene) -> Composition:
        surface = Surface((MENU_WIDTH, MENU_HEIGHT), paint.rgba(BOARD))
        paint.hairline_grid(
            surface.draw,
            (0, 0, MENU_WIDTH, MENU_HEIGHT),
            step=48,
            colour=paint.rgba(BLUE),
            heavy_every=5,
            heavy_colour=paint.rgba(BLUE_HEAVY),
        )
        self._field_guide(surface)
        self._peg_bar(surface)
        used = self._cel(surface, scene.art("still"))
        self._title(surface, scene)
        surface.image = paint.grain(surface.image, amount=0.08, seed=scene.seed + 41, softness=0.5)
        return Composition(surface, tuple(self._buttons(scene)), used)

    def _field_guide(self, surface: Surface) -> None:
        left, top, right, bottom = safe_box()
        draw = surface.draw
        draw.rectangle([left, top, right, bottom], outline=paint.rgba(GUIDE), width=2)
        for x, y in ((left, top), (right, top), (left, bottom), (right, bottom)):
            draw.line([(x - 22, y), (x + 22, y)], fill=paint.rgba(GUIDE), width=2)
            draw.line([(x, y - 22), (x, y + 22)], fill=paint.rgba(GUIDE), width=2)

    def _peg_bar(self, surface: Surface) -> None:
        """Centre round peg, two elongated side pegs. Oxberry geometry."""
        draw = surface.draw
        centre_y = 84
        draw.ellipse(
            [960 - 24, centre_y - 24, 960 + 24, centre_y + 24],
            fill=paint.rgba(PUNCH),
            outline=paint.rgba(PUNCH_EDGE),
            width=2,
        )
        for offset in (-272, 272):
            draw.rounded_rectangle(
                [960 + offset - 44, centre_y - 20, 960 + offset + 44, centre_y + 20],
                radius=20,
                fill=paint.rgba(PUNCH),
                outline=paint.rgba(PUNCH_EDGE),
                width=2,
            )

    def _cel(self, surface: Surface, art: Any) -> bool:
        from PIL import Image, ImageDraw

        surface.paste(
            paint.shadow((MENU_WIDTH, MENU_HEIGHT), CEL, blur=22, alpha=70, offset=(6, 12), radius=6),
            (0, 0),
        )
        width = CEL[2] - CEL[0]
        height = CEL[3] - CEL[1]
        mat = Image.new("RGBA", (width, height), paint.rgba(PAPER))
        inner = (14, 14, width - 14, height - 14)
        inner_size = (inner[2] - inner[0], inner[3] - inner[1])
        if art is not None:
            mat.alpha_composite(paint.crop_fill(art, inner_size), (inner[0], inner[1]))
        else:
            # An empty cel: the mat with its own registration marks on it.
            draw = ImageDraw.Draw(mat)
            draw.rectangle(inner, fill=paint.rgba(MAT))
            paint.registration(
                draw, (width // 2, height // 2), size=90, colour=paint.rgba("#D6CDB8"), thickness=3
            )
            for x in (inner[0] + 60, inner[2] - 60):
                for y in (inner[1] + 50, inner[3] - 50):
                    paint.registration(draw, (x, y), size=34, colour=paint.rgba("#E0D8C4"))
        surface.paste(mat, (CEL[0], CEL[1]))
        paint.keyline(surface.draw, CEL, paint.rgba(INK), thickness=3)
        return art is not None

    def _title(self, surface: Surface, scene: Scene) -> None:
        title = fonts.clean(scene.title)
        if not title:
            return
        block = fonts.fit(
            title.upper(),
            family="ui",
            weight=800,
            max_width=864,
            max_height=240,
            max_lines=3,
            size=88,
            min_size=38,
            leading=1.04,
        )
        surface.block(
            (96, 190), block.lines, block.font, paint.rgb(INK), leading=block.leading, large=True
        )
        rule_y = 190 + block.height + 30
        surface.draw.rectangle([96, rule_y, 276, rule_y + 8], fill=paint.rgba(RED))

    def _buttons(self, scene: Scene) -> list[Slot]:
        width = 800
        labels = [fonts.clean(button.label, fallback=button.key) for button in scene.buttons]
        chosen = set_labels(
            labels,
            family="ui",
            weight=600,
            max_width=width - SHADOW - 90,
            size=38,
            min_size=24,
            tracking=0.02,
        )
        height = max(ROW_HEIGHT, chosen.text_height + 46 + SHADOW)
        count = len(scene.buttons)
        total = count * height + (count - 1) * ROW_GAP
        top = 1026 - total
        return [
            Slot(
                key=button.key,
                label=" ".join(chosen.lines[index]),
                x=96,
                y=top + index * (height + ROW_GAP),
                width=width,
                height=height,
                paint=self._painter(chosen, chosen.lines[index]),
            )
            for index, button in enumerate(scene.buttons)
        ]

    def _painter(self, chosen: Any, lines: tuple[str, ...]) -> Any:
        def draw_button(tile: Surface, state: str) -> None:
            width, height = tile.size
            pill = [0, 0, width - SHADOW, height - SHADOW]
            radius = (height - SHADOW) // 2
            if state == "normal":
                fill, ink, shade = PAPER, INK, None
            elif state == "selected":
                fill, ink, shade = YELLOW, INK, INK
            else:
                fill, ink, shade = INK, CREAM, RED
            if shade is not None:
                tile.draw.rounded_rectangle(
                    [pill[0] + SHADOW, pill[1] + SHADOW, pill[2] + SHADOW, pill[3] + SHADOW],
                    radius=radius,
                    fill=paint.rgba(shade),
                )
            tile.draw.rounded_rectangle(
                pill, radius=radius, fill=paint.rgba(fill), outline=paint.rgba(INK), width=5
            )
            text_top = (height - SHADOW - chosen.text_height) // 2
            tile.block(
                ((width - SHADOW) // 2, text_top),
                list(lines),
                chosen.font,
                paint.rgb(ink),
                leading=chosen.leading,
                tracking=chosen.tracking,
                align="centre",
            )

        return draw_button


DESIGN = Animation()
