"""Music film: the bill outside the venue.

A screen-printed gig poster. The still is flattened into three inks and a
line screen rather than dimmed behind a scrim, which is both the right look
and the reason the contrast on this design is knowable: after the duotone the
picture contains three colours, not sixteen million.

The title is knocked out of solid blocks, one per line, the way poster type
is set. The buttons are a run down the right on a printed panel with a
ticket-stub edge - not a row across the bottom, which is what produced
"AUDIO AND SU..." and "ABOUT THIS D..." on the version this replaces.
"""

from __future__ import annotations

from typing import Any

from wti_player.menu import fonts, paint
from wti_player.menu.designs.base import Composition, Design, Scene, Slot, set_labels
from wti_player.menu.surface import Surface
from wti_player.menu.types import MENU_HEIGHT, MENU_WIDTH

INK = "#0C0A12"
MID = "#4A2160"
PINK = "#FF4D7E"
YELLOW = "#FFE066"
PAPER = "#FFF3E8"

PANEL = (1234, 566, 1824, 1026)
BUTTON_LEFT = 1264
BUTTON_WIDTH = 530
ROW_HEIGHT = 78
TITLE_MAX = 1080


class MusicFilm(Design):
    key = "music_film"
    name = "Music film"
    description = "A screen-printed bill: the film flattened into three inks, the title knocked out of black."
    references = (
        "Three inks and a line screen. A gig poster is printed, not photographed.",
        "The run of buttons is a set list down the right, so nothing has to be shortened.",
    )
    backing = INK

    def compose(self, scene: Scene) -> Composition:
        surface = Surface((MENU_WIDTH, MENU_HEIGHT), paint.rgba(INK))
        used = self._print(surface, scene.art("still"), scene.seed)
        self._panel(surface)
        self._title(surface, scene)
        return Composition(surface, tuple(self._buttons(scene)), used)

    def _print(self, surface: Surface, art: Any, seed: int) -> bool:
        from PIL import Image

        if art is not None:
            plate = paint.duotone(
                paint.crop_fill(art, (MENU_WIDTH, MENU_HEIGHT), focus=0.35),
                paint.rgb(INK),
                paint.rgb(MID),
                paint.rgb(PINK),
            )
        else:
            # No photograph: one ink and a spotlight. Still a printed poster.
            plate = Image.new("RGBA", (MENU_WIDTH, MENU_HEIGHT), paint.rgba(INK))
            from PIL import ImageDraw

            draw = ImageDraw.Draw(plate)
            for index, x in enumerate(range(-40, MENU_WIDTH + 200, 168)):
                draw.polygon(
                    [(x, 0), (x + 96 + index * 6, 0), (x + 40, MENU_HEIGHT), (x - 60, MENU_HEIGHT)],
                    fill=paint.rgba(MID),
                )
            draw.ellipse([1080, 150, 1660, 730], fill=paint.rgba(PINK))
        surface.paste(plate, (0, 0))
        surface.paste(
            paint.line_screen(
                (MENU_WIDTH, MENU_HEIGHT), spacing=8, colour=paint.rgb(INK), alpha=52, thickness=3
            ),
            (0, 0),
        )
        surface.image = paint.grain(surface.image, amount=0.13, seed=seed + 51)
        return art is not None

    def _panel(self, surface: Surface) -> None:
        """The printed block the buttons sit on, with a stub edge bitten out."""
        from PIL import Image, ImageDraw

        width = PANEL[2] - PANEL[0]
        height = PANEL[3] - PANEL[1]
        panel = Image.new("RGBA", (width, height), paint.rgba(INK))
        draw = ImageDraw.Draw(panel)
        paint.keyline(draw, (0, 0, width, height), paint.rgba(PINK), thickness=3)
        # Drawn straight onto the alpha, so the poster underneath shows in the
        # notches. Compositing a transparent shape would have blended nothing.
        paint.notched_edge(draw, 0, 18, height - 18, colour=(0, 0, 0, 0), pitch=30, depth=9)
        surface.paste(panel, (PANEL[0], PANEL[1]))

    def _title(self, surface: Surface, scene: Scene) -> None:
        title = fonts.clean(scene.title)
        if not title:
            return
        block = fonts.fit(
            title.upper(),
            family="ui",
            weight=900,
            max_width=TITLE_MAX,
            max_height=420,
            max_lines=3,
            size=118,
            min_size=48,
            tracking=-0.018,
            leading=1.0,
        )
        pad_x, pad_y = 26, 12
        step = block.leading + pad_y
        top = 1000 - (step * (len(block.lines) - 1) + fonts.height_of(block.font) + pad_y * 2)
        # One band, off the left edge, up to the buttons panel. Blocks cut to
        # each line's own width left ragged strips of poster showing between
        # them, which read as a mistake rather than as knocked-out type.
        surface.draw.rectangle(
            [-20, top, PANEL[0] - 16, top + step * (len(block.lines) - 1)
             + fonts.height_of(block.font) + pad_y * 2],
            fill=paint.rgba(INK),
        )
        for index, line in enumerate(block.lines):
            surface.text(
                (96 + pad_x, top + index * step + pad_y),
                line,
                block.font,
                paint.rgb(PAPER),
                tracking=block.tracking,
                large=True,
            )

    def _buttons(self, scene: Scene) -> list[Slot]:
        labels = [fonts.clean(button.label, fallback=button.key).upper() for button in scene.buttons]
        chosen = set_labels(
            labels,
            family="ui",
            weight=500,
            max_width=BUTTON_WIDTH - 52,
            size=30,
            min_size=18,
            tracking=0.12,
        )
        height = max(ROW_HEIGHT, chosen.text_height + 34)
        count = len(scene.buttons)
        top = PANEL[1] + max(20, (PANEL[3] - PANEL[1] - height * count) // 2)
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
            ink = paint.rgb(PAPER)
            if state == "normal":
                tile.draw.rectangle(
                    [0, height - 1, width - 1, height - 1], fill=paint.rgba("#3A2340")
                )
            elif state == "selected":
                tile.draw.rectangle([0, 0, width, height], fill=paint.rgba(PINK))
                ink = paint.rgb(INK)
            else:
                tile.draw.rectangle([0, 0, width, height], fill=paint.rgba(YELLOW))
                ink = paint.rgb(INK)
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


DESIGN = MusicFilm()
