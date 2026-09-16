"""Classic cinema: a repertory house's printed programme.

The reference is the card a rep cinema hands you at the door - ivory stock,
engraved rules, the title set in a book serif, the evening's running order
down the page. So the frame is split: a printed card on the left, the film's
own image running off the right edge behind it, the way a programme sits on a
table in front of a screen.

The card is why the labels are readable without any correction at all. Dark
ink on ivory is a decision about materials, not a scrim laid over a
photograph because the photograph turned out to be too bright.
"""

from __future__ import annotations

from typing import Any

from wti_player.menu import fonts, paint
from wti_player.menu.designs.base import Composition, Design, Scene, Slot, set_labels
from wti_player.menu.surface import Surface
from wti_player.menu.types import MENU_HEIGHT, MENU_WIDTH

GROUND = "#12100D"
CARD = "#EFE7D6"
INK = "#1B1712"
RULE = "#B9A882"
HAIRLINE = "#D8CBB0"
GOLD = "#C08A3E"

#: The card runs the full title-safe height and just under a third of the
#: width. Wider and the picture becomes a strip; narrower and a three-line
#: title has nowhere to go.
CARD_LEFT = 96
CARD_RIGHT = 796
CARD_TOP = 54
CARD_BOTTOM = 1026
#: Inside the card's own keyline.
PAD = 16
ROW_HEIGHT = 82


class ClassicCinema(Design):
    key = "classic_cinema"
    name = "Classic cinema"
    description = "A repertory programme card, ivory on black, with the film running off the right edge."
    references = (
        "The card a rep house hands you at the door: rules, a running order, one serif.",
        "The picture is behind the programme, not under a filter.",
    )
    backing = CARD
    backing_is_light = True

    def compose(self, scene: Scene) -> Composition:
        surface = self.frame(GROUND)
        art = scene.art("still")
        used = self._picture(surface, art, scene.seed)
        self._card(surface, scene)
        return Composition(surface, tuple(self._buttons(scene)), used)

    # -- the frame ----------------------------------------------------------

    def _picture(self, surface: Surface, art: Any, seed: int) -> bool:
        """The film's image on the right, faded into the ground under the card."""
        from PIL import Image

        left = CARD_RIGHT - 120
        span = MENU_WIDTH - left
        if art is None:
            self._embossed_field(surface, left, seed)
            return False

        plate = paint.crop_fill(art, (span, MENU_HEIGHT), focus=0.6)
        plate = paint.monochrome(plate, paint.rgb("#0D0B08"), paint.rgb("#EDE3D0"))
        # A ramp on the left edge instead of a hard cut. The card sits over
        # the first 120px of it, so the join never shows.
        fade = 300
        ramp = Image.new("L", (span, 1))
        ramp.putdata([min(255, int(255 * x / fade)) for x in range(span)])
        plate.putalpha(ramp.resize((span, MENU_HEIGHT)))
        surface.paste(plate, (left, 0))
        surface.image = paint.vignette(surface.image, strength=0.42, colour=paint.rgb(GROUND))
        surface.image = paint.grain(surface.image, amount=0.14, seed=seed, softness=0.4)
        return True

    def _embossed_field(self, surface: Surface, left: int, seed: int) -> None:
        """No artwork: blind-embossed stock, which is what the back of a card is."""
        draw = surface.draw
        centre = ((left + MENU_WIDTH) // 2, MENU_HEIGHT // 2)
        for step in range(7):
            inset = step * 46
            draw.rounded_rectangle(
                [centre[0] - 320 + inset, centre[1] - 320 + inset,
                 centre[0] + 320 - inset, centre[1] + 320 - inset],
                radius=18,
                outline=paint.rgba("#2C2418", 255),
                width=2,
            )
        draw.line([(left + 60, 54), (left + 60, 1026)], fill=paint.rgba("#2A2317", 255), width=1)
        draw.line([(MENU_WIDTH - 60, 54), (MENU_WIDTH - 60, 1026)], fill=paint.rgba("#2A2317", 255), width=1)
        surface.image = paint.grain(surface.image, amount=0.16, seed=seed, softness=0.5)

    def _card(self, surface: Surface, scene: Scene) -> None:
        from PIL import Image

        box = (CARD_LEFT, CARD_TOP, CARD_RIGHT, CARD_BOTTOM)
        surface.paste(
            paint.shadow((MENU_WIDTH, MENU_HEIGHT), box, blur=30, alpha=150, offset=(6, 16)), (0, 0)
        )
        stock = Image.new("RGBA", (CARD_RIGHT - CARD_LEFT, CARD_BOTTOM - CARD_TOP), paint.rgba(CARD))
        stock = paint.grain(stock, amount=0.09, seed=scene.seed + 3, softness=0.8)
        surface.paste(stock, (CARD_LEFT, CARD_TOP))

        draw = surface.draw
        paint.keyline(
            draw,
            (CARD_LEFT + PAD, CARD_TOP + PAD, CARD_RIGHT - PAD, CARD_BOTTOM - PAD),
            paint.rgba(RULE),
        )
        inner_left = CARD_LEFT + PAD + 40
        inner_right = CARD_RIGHT - PAD - 40
        # Two rules, one heavy one light, 9px apart. An engraver's masthead.
        draw.rectangle([inner_left, 140, inner_right, 142], fill=paint.rgba(INK))
        draw.rectangle([inner_left, 151, inner_right, 151], fill=paint.rgba(RULE))

        title = fonts.clean(scene.title)
        if title:
            block = fonts.fit(
                title,
                family="display",
                weight=600,
                max_width=inner_right - inner_left,
                max_height=300,
                max_lines=3,
                size=66,
                min_size=34,
                leading=1.14,
            )
            # Hung from the bottom, not the top. A one-line title set at 196
            # left 300px of blank card between it and the list; anchoring the
            # rule instead keeps the gap where it belongs, under the masthead.
            rule_y = 512
            top = max(200, rule_y - 40 - block.height)
            surface.block(
                (inner_left, top),
                block.lines,
                block.font,
                paint.rgb(INK),
                leading=block.leading,
                large=True,
            )
            draw.rectangle([inner_left, rule_y, inner_left + 140, rule_y + 3], fill=paint.rgba(GOLD))

    # -- the running order --------------------------------------------------

    def _buttons(self, scene: Scene) -> list[Slot]:
        left = CARD_LEFT + PAD
        right = CARD_RIGHT - PAD
        width = right - left
        labels = [fonts.clean(button.label, fallback=button.key).upper() for button in scene.buttons]
        chosen = set_labels(
            labels,
            family="ui",
            weight=400,
            max_width=width - 80,
            size=30,
            min_size=19,
            tracking=0.14,
        )
        height = max(ROW_HEIGHT, chosen.text_height + 44)
        top = CARD_BOTTOM - PAD - 24 - height * len(scene.buttons)

        slots: list[Slot] = []
        for index, button in enumerate(scene.buttons):
            lines = chosen.lines[index]
            slots.append(
                Slot(
                    key=button.key,
                    label=" ".join(lines),
                    x=left,
                    y=top + index * height,
                    width=width,
                    height=height,
                    paint=self._painter(chosen, lines),
                )
            )
        return slots

    def _painter(self, chosen: Any, lines: tuple[str, ...]) -> Any:
        def draw_button(tile: Surface, state: str) -> None:
            width, height = tile.size
            ink = paint.rgb(INK)
            if state == "normal":
                tile.draw.rectangle([0, 0, width, 0], fill=paint.rgba(HAIRLINE))
            elif state == "selected":
                tile.draw.rectangle([0, 0, width, height], fill=paint.rgba(INK))
                tile.draw.rectangle([0, 0, 9, height], fill=paint.rgba(GOLD))
                ink = paint.rgb(CARD)
            else:
                tile.draw.rectangle([0, 0, width, height], fill=paint.rgba(GOLD))
                tile.draw.rectangle([0, 0, 9, height], fill=paint.rgba(CARD))
            text_top = (height - chosen.text_height) // 2
            tile.block(
                (40, text_top),
                list(lines),
                chosen.font,
                ink,
                leading=chosen.leading,
                tracking=chosen.tracking,
            )

        return draw_button


DESIGN = ClassicCinema()
