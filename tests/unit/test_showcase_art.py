"""tools/showcase_art.py: the real print art on a showcase disc (launch-week plan, V0, 15 Sep 2026)."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from tools import showcase_art


def _wrap(path: Path, size: tuple[int, int] = (840, 510)) -> Path:
    """A small wrap: blue back and spine, red front from the spine's right edge."""
    image = Image.new("RGB", size, (0, 0, 255))
    left = showcase_art.front_box(size)[0]
    image.paste((255, 0, 0), (left, 0, size[0], size[1]))
    image.save(path)
    return path


def test_the_front_is_cut_at_the_trim_in_proportion() -> None:
    assert showcase_art.front_box((8400, 5100)) == (4365, 389, 7424, 4711)
    assert showcase_art.front_box((840, 510)) == (436, 39, 742, 471)


def test_writes_the_cover_and_label_and_names_them_in_an_existing_document(tmp_path: Path) -> None:
    disc = tmp_path / "disc"
    (disc / "BDMV").mkdir(parents=True)
    (disc / ".wti_meta.json").write_text(json.dumps({"schema": 1, "made_by": "We the Indies", "title": "Nosferatu"}), encoding="utf-8")
    label = tmp_path / "WtI_Nosferatu_Disc.png"
    Image.new("RGBA", (1500, 1500), (10, 20, 30, 255)).save(label)

    art = showcase_art.write_showcase_art(disc, wrap=_wrap(tmp_path / "wrap.png"), label=label)

    assert art == {"cover": "cover.jpg", "disc": "disc.jpg"}
    document = json.loads((disc / ".wti_meta.json").read_text(encoding="utf-8"))
    assert document["title"] == "Nosferatu" and document["art"] == art
    with Image.open(disc / "cover.jpg") as cover:
        assert cover.format == "JPEG" and max(cover.size) <= showcase_art.COVER_LONGEST_EDGE
        # Every pixel of the cut is the front panel: red, never the blue back or spine.
        red, _green, blue = cover.convert("RGB").getpixel((1, cover.size[1] // 2))
        assert red > 200 and blue < 60
        assert cover.size[0] < cover.size[1]
    with Image.open(disc / "disc.jpg") as face:
        assert max(face.size) == showcase_art.DISC_LONGEST_EDGE


def test_a_game_disc_keeps_its_art_in_menu_and_a_bare_folder_gets_a_document(tmp_path: Path) -> None:
    game = tmp_path / "game"
    (game / "menu").mkdir(parents=True)
    (game / "menu" / ".wti_meta.json").write_text("{}", encoding="utf-8")
    front = tmp_path / "insert.png"
    Image.new("RGB", (900, 1300), (0, 128, 0)).save(front)
    showcase_art.write_showcase_art(game, cover=front)
    assert (game / "menu" / "cover.jpg").is_file()
    assert json.loads((game / "menu" / ".wti_meta.json").read_text(encoding="utf-8"))["art"] == {"cover": "cover.jpg"}

    bare = tmp_path / "bare"
    bare.mkdir()
    showcase_art.write_showcase_art(bare, cover=front)
    document = json.loads((bare / ".wti_meta.json").read_text(encoding="utf-8"))
    assert document["made_by"] == "We the Indies" and document["art"] == {"cover": "cover.jpg"}


def test_finds_the_wrap_its_variant_and_the_label(tmp_path: Path) -> None:
    for name in ("WtI_X_Cover_Outside_ENG_SE.png", "WtI_X_Cover_Outside_ENG_SE_B.png", "WtI_X_Disc.png", "WtI_X_Cover_Inside_SE.png"):
        (tmp_path / name).write_bytes(b"")
    assert showcase_art.find_print_files(tmp_path) == (tmp_path / "WtI_X_Cover_Outside_ENG_SE.png", tmp_path / "WtI_X_Disc.png")
    assert showcase_art.find_print_files(tmp_path, "b")[0] == tmp_path / "WtI_X_Cover_Outside_ENG_SE_B.png"
