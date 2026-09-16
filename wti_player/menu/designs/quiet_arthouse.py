"""Quiet arthouse: a gallery wall label.

Paper, a hairline frame, and far more empty space than a menu usually dares.
The film's image is held small and square, the way a catalogue reproduces a
work rather than the way a poster uses one - the point of this design is that
the art is a reference, not the wallpaper.

Quiet at rest and not quiet when you press it. The selected row fills solid,
because a person three metres away with a remote needs to see which line they
are on, and a slightly darker grey is not a state.
"""

from __future__ import annotations

from typing import Any

from wti_player.menu import fonts, paint
from wti_player.menu.designs.base import Composition, Design, Scene, Slot, set_labels
from wti_player.menu.surface import Surface
from wti_player.menu.types import MENU_HEIGHT, MENU_WIDTH

PAPER = "#E9E6DE"
INK = "#23211C"
HAIRLINE = "#B6B0A2"
RULE = "#CFC9BB"
MOUNT = "#DEDAD0"
OXBLOOD = "#8C2B1F"

FRAME = (150, 100, 1770, 980)
#: Square. A film frame cropped square reads as a detail lifted out of
#: the picture, which is what a catalogue plate is.
PLATE = (222, 158, 622, 558)
TEXT_LEFT = 692
#: The list shares the title's axis. Set against the left margin it left
#: the whole bottom right of the frame empty, which read as unfinished
#: rather than as quiet.
BUTTON_LEFT = 692
BUTTON_WIDTH = 720
ROW_HEIGHT = 64


class QuietArthouse(Design):
    key = "quiet_arthouse"
    name = "Quiet arthouse"
    description = "Paper, a hairline frame, the still held small and square, type kept out of the way."
    references = (
        "A wall label beside a print: the reproduction is small on purpose.",
        "A light ground, which almost no disc menu risks and which reads as confidence.",
    )
    backing = PAPER
    backing_is_light = True

    def compose(self, scene: Scene) -> Composition:
        surface = Surface((MENU_WIDTH, MENU_HEIGHT), paint.rgba(PAPER))
        surface.image = paint.grain(surface.image, amount=0.11, seed=scene.seed + 21, softness=0.7)
        surface.image = paint.vignette(surface.image, strength=0.12, colour=paint.rgb("#8E887A"))
        paint.keyline(surface.draw, FRAME, paint.rgba(HAIRLINE))
        used = self._plate(surface, scene.art("still"))
        self._title(surface, scene)
        return Composition(surface, tuple(self._buttons(scene)), used)

    def _plate(self, surface: Surface, art: Any) -> bool:
        from PIL import Image

        size = (PLATE[2] - PLATE[0], PLATE[3] - PLATE[1])
        if art is not None:
            plate = paint.crop_fill(art, size)
            plate = paint.monochrome(plate, paint.rgb("#302C25"), paint.rgb("#E4E0D6"))
        else:
            # An unprinted mount with a registration cross on it. A catalogue
            # with no plate yet, which is a real thing and looks like one.
            plate = Image.new("RGBA", size, paint.rgba(MOUNT))
            from PIL import ImageDraw

            paint.registration(
                ImageDraw.Draw(plate),
                (size[0] // 2, size[1] // 2),
                size=64,
                colour=paint.rgba(HAIRLINE),
                thickness=1,
            )
        surface.paste(plate, (PLATE[0], PLATE[1]))
        paint.keyline(surface.draw, PLATE, paint.rgba(HAIRLINE))
        return art is not None

    def _title(self, surface: Surface, scene: Scene) -> None:
        title = fonts.clean(scene.title)
        if not title:
            return
        block = fonts.fit(
            title,
            family="display",
            weight=400,
            max_width=FRAME[2] - 40 - TEXT_LEFT,
            max_height=280,
            max_lines=3,
            size=58,
            min_size=30,
            leading=1.18,
        )
        surface.block(
            (TEXT_LEFT, PLATE[1] + 6),
            block.lines,
            block.font,
            paint.rgb(INK),
            leading=block.leading,
            large=True,
        )
        rule_y = PLATE[1] + 6 + block.height + 36
        surface.draw.rectangle(
            [TEXT_LEFT, rule_y, TEXT_LEFT + 260, rule_y], fill=paint.rgba(HAIRLINE)
        )

    def _buttons(self, scene: Scene) -> list[Slot]:
        labels = [fonts.clean(button.label, fallback=button.key).upper() for button in scene.buttons]
        chosen = set_labels(
            labels,
            family="ui",
            weight=300,
            max_width=BUTTON_WIDTH - 60,
            size=26,
            min_size=17,
            tracking=0.22,
        )
        height = max(ROW_HEIGHT, chosen.text_height + 32)
        top = 448
        return [
            Slot(
                key=button.key,
                label=" ".join(chosen.lines[index]),
                x=BUTTON_LEFT,
                y=top + index * height,
                width=BUTTON_WIDTH,
                height=height,
                paint=self._painter(chosen, chosen.lines[index]),
            )
            for index, button in enumerate(scene.buttons)
        ]

    def _painter(self, chosen: Any, lines: tuple[str, ...]) -> Any:
        def draw_button(tile: Surface, state: str) -> None:
            width, height = tile.size
            ink = paint.rgb(INK)
            if state == "normal":
                tile.draw.rectangle([0, height - 1, width - 1, height - 1], fill=paint.rgba(RULE))
            elif state == "selected":
                tile.draw.rectangle([0, 0, width, height], fill=paint.rgba(INK))
                ink = paint.rgb(PAPER)
            else:
                tile.draw.rectangle([0, 0, width, height], fill=paint.rgba(OXBLOOD))
                ink = paint.rgb("#F2EFE7")
            text_top = (height - chosen.text_height) // 2
            tile.block(
                (26, text_top),
                list(lines),
                chosen.font,
                ink,
                leading=chosen.leading,
                tracking=chosen.tracking,
            )

        return draw_button


DESIGN = QuietArthouse()
