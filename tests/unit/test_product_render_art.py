"""Finished PNG product images keep their shape, hole and alpha in the Player."""

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from tools.showcase_art import write_showcase_art


def test_showcase_keeps_product_png_alpha_and_names_it_in_the_document(tmp_path: Path):
    picture = Image.new("RGBA", (200, 100))
    ImageDraw.Draw(picture).rectangle((30, 20, 170, 80), fill=(255, 0, 0, 255))
    # An actual hole in a finished render must remain transparent.
    ImageDraw.Draw(picture).ellipse((90, 40, 110, 60), fill=(0, 0, 0, 0))
    source = tmp_path / "render.png"
    picture.save(source)
    disc = tmp_path / "disc"
    disc.mkdir()
    art = write_showcase_art(disc, case_render=source, disc_render=source)
    assert art == {"cover": "cover.png", "disc": "disc.png"}
    with Image.open(disc / "disc.png") as result:
        assert result.mode == "RGBA"
        assert result.width > result.height
        assert result.getpixel((result.width // 2, result.height // 2))[3] == 0


def test_empty_render_does_not_replace_the_document(tmp_path: Path):
    source = tmp_path / "empty.png"
    Image.new("RGBA", (10, 10)).save(source)
    disc = tmp_path / "disc"
    disc.mkdir()
    document = disc / ".wti_meta.json"
    document.write_text('{"title": "keep me"}', encoding="utf-8")
    with pytest.raises(ValueError, match="empty product render"):
        write_showcase_art(disc, case_render=source)
    assert document.read_text(encoding="utf-8") == '{"title": "keep me"}'


@pytest.mark.parametrize("shape", ["case", "disc"])
def test_finished_render_is_neither_cropped_nor_given_a_fake_hub(qapp, tmp_path: Path, shape: str):
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QImage

    from wti_player.ui import artwork

    source = QImage(200, 100, QImage.Format.Format_ARGB32)
    source.fill(QColor(0, 0, 0, 0))
    # Pixels at both ends and at the centre catch cropping and a painted hub.
    for x in range(5, 195):
        for y in range(10, 90):
            source.setPixelColor(x, y, QColor("#ff0000"))
    filename = tmp_path / "product.png"
    assert source.save(str(filename))
    artwork.forget()
    widget = artwork.CoverPlate(width=200) if shape == "case" else artwork.DiscFace(size=200)
    if shape == "case":
        widget.set_cover(filename)
    else:
        widget.set_face(filename)
    assert widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    drawn = widget.grab().toImage()
    middle = drawn.height() // 2
    for x in (10, 100, 189):
        assert drawn.pixelColor(x, middle) == QColor("#ff0000")
    assert drawn.pixelColor(0, 0).alpha() == 0
