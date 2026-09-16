"""Bold poster art: the one-sheet, hung.

The art is treated as a print - a 2:3 plate, keylined, with a shadow under it
- rather than stretched across the frame and dimmed. Beside it the title is
set as large as the words allow and the buttons run to the bottom like the
credit block on a poster.

Two things this fixes outright. The old version of this theme drew no title
at all, so a disc arrived as a black screen with five right-aligned words in
it. And it filled the frame with the poster, then had to put a scrim over the
poster so the words could be read, which is a design that undoes itself.
"""

from __future__ import annotations

from typing import Any

from wti_player.menu import fonts, paint
from wti_player.menu.designs.base import Composition, Design, Scene, Slot, set_labels
from wti_player.menu.surface import Surface
from wti_player.menu.types import MENU_HEIGHT, MENU_WIDTH

PAPER = "#F4F2ED"
INK = "#14161A"
DEFAULT_GROUND = "#16181C"
#: Warm enough to carry near-black type at better than 5:1. A deeper red
#: looks better and cannot: dark ink needs a light field, and vermilion is
#: as dark as the field can get.
ACCENT = "#FF5A3C"
DIM = "#6B7078"

PLATE = (96, 54, 744, 1026)
COLUMN_LEFT = 812
COLUMN_RIGHT = 1824
ROW_HEIGHT = 100


class PosterArt(Design):
    key = "poster_art"
    name = "Bold poster art"
    description = "The artwork hung as a keylined 2:3 print, with the title set large beside it."
    references = (
        "A one-sheet in a lobby frame: the print is an object, not a wallpaper.",
        "Selected is the whole row in vermilion. It reads from the sofa.",
    )
    backing = DEFAULT_GROUND

    def compose(self, scene: Scene) -> Composition:
        art = scene.art("poster")
        ground = (
            paint.mix(paint.dominant(art), paint.rgb(DEFAULT_GROUND), 0.86)
            if art is not None
            else paint.rgb(DEFAULT_GROUND)
        )
        surface = Surface((MENU_WIDTH, MENU_HEIGHT), (*ground, 255))
        surface.image = paint.grain(surface.image, amount=0.10, seed=scene.seed + 11)
        used = self._plate(surface, art, scene.seed)
        self._title(surface, scene)
        return Composition(surface, tuple(self._buttons(scene)), used)

    def _plate(self, surface: Surface, art: Any, seed: int) -> bool:
        surface.paste(
            paint.shadow((MENU_WIDTH, MENU_HEIGHT), PLATE, blur=34, alpha=170, offset=(0, 18)),
            (0, 0),
        )
        width = PLATE[2] - PLATE[0]
        height = PLATE[3] - PLATE[1]
        if art is not None:
            print_face = self._mounted(art, width, height)
        else:
            print_face = self._typographic(width, height, seed)
        surface.paste(print_face, (PLATE[0], PLATE[1]))
        paint.keyline(surface.draw, PLATE, paint.rgba(PAPER), thickness=3)
        return art is not None

    def _mounted(self, art: Any, width: int, height: int) -> Any:
        """The artwork inside the plate, whole.

        The plate is 2:3 and most of what a film-maker sends is 16:9. Cropping
        a frame still to portrait threw away two thirds of it and cut the
        subject in half, so anything wider than the plate is mounted instead:
        contained, keylined, sitting high on a card the colour of the picture.
        A print in a mount, which is what the design was always about.
        """
        from PIL import Image

        if art.height / art.width >= height / width * 0.92:
            return paint.crop_fill(art, (width, height))
        inner_width = width - 76
        inner_height = max(1, round(inner_width * art.height / art.width))
        mount = Image.new("RGBA", (width, height), (*paint.mix(paint.dominant(art), paint.rgb(INK), 0.62), 255))
        # Optically centred: a third of the spare above, two thirds below,
        # the way a print is hung in a mount.
        top = 38 + int((height - 76 - inner_height) * 0.34)
        mount.alpha_composite(paint.scaled(art, (inner_width, inner_height)), (38, top))
        from PIL import ImageDraw

        paint.keyline(
            ImageDraw.Draw(mount),
            (38, top, 38 + inner_width, top + inner_height),
            paint.rgba("#0A0B0D", 150),
        )
        return mount

    def _typographic(self, width: int, height: int, seed: int) -> Any:
        """No artwork: a printed field, which is what a poster is before a photo.

        Two circles and a line screen. It is not a placeholder grey box and it
        is not pretending to be a still.
        """
        from PIL import Image, ImageDraw

        plate = Image.new("RGBA", (width, height), paint.rgba(ACCENT))
        draw = ImageDraw.Draw(plate)
        draw.ellipse([width * 0.06, height * 0.10, width * 0.82, height * 0.62], fill=paint.rgba(INK))
        draw.ellipse(
            [width * 0.30, height * 0.42, width * 0.98, height * 0.92],
            outline=paint.rgba(PAPER),
            width=10,
        )
        plate.alpha_composite(
            paint.line_screen((width, height), spacing=9, colour=paint.rgb(INK), alpha=46)
        )
        return paint.grain(plate, amount=0.12, seed=seed + 5)

    def _title(self, surface: Surface, scene: Scene) -> None:
        title = fonts.clean(scene.title)
        if not title:
            return
        block = fonts.fit(
            title.upper(),
            family="ui",
            weight=800,
            max_width=COLUMN_RIGHT - COLUMN_LEFT,
            max_height=360,
            max_lines=3,
            size=110,
            min_size=44,
            tracking=-0.005,
            leading=1.02,
        )
        surface.block(
            (COLUMN_LEFT, 132),
            block.lines,
            block.font,
            paint.rgb(PAPER),
            leading=block.leading,
            tracking=block.tracking,
            large=True,
        )
        rule_y = 132 + block.height + 42
        surface.draw.rectangle(
            [COLUMN_LEFT, rule_y, COLUMN_LEFT + 220, rule_y + 11], fill=paint.rgba(ACCENT)
        )

    def _buttons(self, scene: Scene) -> list[Slot]:
        width = COLUMN_RIGHT - COLUMN_LEFT
        labels = [fonts.clean(button.label, fallback=button.key).upper() for button in scene.buttons]
        chosen = set_labels(
            labels,
            family="ui",
            weight=500,
            max_width=width - 130,
            size=34,
            min_size=21,
            tracking=0.10,
        )
        height = max(ROW_HEIGHT, chosen.text_height + 52)
        top = 1026 - height * len(scene.buttons)
        return [
            Slot(
                key=button.key,
                label=" ".join(chosen.lines[index]),
                x=COLUMN_LEFT,
                y=top + index * height,
                width=width,
                height=height,
                paint=self._painter(chosen, chosen.lines[index]),
            )
            for index, button in enumerate(scene.buttons)
        ]

    def _painter(self, chosen: Any, lines: tuple[str, ...]) -> Any:
        def draw_button(tile: Surface, state: str) -> None:
            width, height = tile.size
            marker = paint.rgba(DIM)
            ink = paint.rgb(PAPER)
            if state == "normal":
                tile.draw.rectangle([0, 0, width - 1, 1], fill=paint.rgba("#3A3F46"))
            elif state == "selected":
                tile.draw.rectangle([0, 0, width, height], fill=paint.rgba(ACCENT))
                ink, marker = paint.rgb(INK), paint.rgba(INK)
            else:
                tile.draw.rectangle([0, 0, width, height], fill=paint.rgba(PAPER))
                ink, marker = paint.rgb(INK), paint.rgba(ACCENT)
            text_top = (height - chosen.text_height) // 2
            tile.block(
                (34, text_top),
                list(lines),
                chosen.font,
                ink,
                leading=chosen.leading,
                tracking=chosen.tracking,
            )
            centre = height // 2
            tile.draw.rectangle(
                [width - 52, centre - 9, width - 34, centre + 9], fill=marker
            )

        return draw_button


DESIGN = PosterArt()
