"""Put existing product renders or print art beside a showcase disc's metadata.

    python tools/showcase_art.py <disc folder> --case-render <transparent PNG> --disc-render <transparent PNG>

    python tools/showcase_art.py <disc folder> --print-dir <print folder> [--variant B]
    python tools/showcase_art.py <disc folder> --cover-file <png> --disc-file <png>

The print folders (``Launch-2026/print/film/<slug>`` and friends) hold the case wrap
``WtI_<Name>_Cover_Outside_ENG_SE.png`` (``_B`` and ``_C`` for the other covers of a Choose-your-cover title) and the
label ``WtI_<Name>_Disc.png``. The wrap is 8400 x 5100 px at 600 dpi, as ``marketing/print/pd/build_pd_print.py``
draws it: back panel left, spine at x 4035..4365, front panel right. The front is cut at the trim
(x 4365..7424, y 389..4711), so no bleed and no crop mark shows; a wrap at another resolution is cut in proportion.

The pictures are written the way ``rialto2/rialto_core/disc_art.py`` writes them for a real disc (RGB JPEG, quality
85, 1200 px longest edge for the cover and 1000 px for the label), and the document's ``art`` block names them, so
GoldWing can show the print-art fallback. Transparent product renders instead retain their shape,
shadow and disc opening in ``cover.png`` and ``disc.png``, without another mask or frame.
The document is looked for where the Player looks
(the disc root, then ``menu/``); a folder with none gets a minimal one at the root.

Reads the print folder; writes only into the disc folder it is given. Nothing here ships.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

#: The wrap geometry, from build_pd_print.py.
WRAP_SIZE = (8400, 5100)
FRONT_TRIM = (4365, 389, 7424, 4711)

COVER_NAME = "cover.jpg"
DISC_NAME = "disc.jpg"
COVER_LONGEST_EDGE = 1200
DISC_LONGEST_EDGE = 1000
JPEG_QUALITY = 85
#: What the Player refuses outright.
MAX_BYTES = 8 * 1024 * 1024

META_NAME = ".wti_meta.json"
META_SEARCH = (META_NAME, f"menu/{META_NAME}")


def front_box(size: tuple[int, int]) -> tuple[int, int, int, int]:
    """The front panel's trim box for a wrap of ``size``, scaled from the 600 dpi layout."""
    sx = size[0] / WRAP_SIZE[0]
    sy = size[1] / WRAP_SIZE[1]
    left, top, right, bottom = FRONT_TRIM
    return (round(left * sx), round(top * sy), round(right * sx), round(bottom * sy))


def find_print_files(print_dir: Path, variant: str = "") -> tuple[Path | None, Path | None]:
    """The (wrap, label) in a print folder, or None for each that is not there."""
    suffix = f"_{variant.upper()}" if variant else ""
    wraps = sorted(p for p in print_dir.glob(f"WtI_*_Cover_Outside_ENG_SE{suffix}.png"))
    labels = sorted(p for p in print_dir.glob("WtI_*_Disc*.png"))
    return (wraps[0] if wraps else None, labels[0] if labels else None)


def _save_jpeg(picture, target: Path, longest_edge: int) -> None:
    picture = picture.convert("RGB")
    picture.thumbnail((longest_edge, longest_edge))
    target.parent.mkdir(parents=True, exist_ok=True)
    picture.save(target, "JPEG", quality=JPEG_QUALITY, optimize=True)
    if target.stat().st_size > MAX_BYTES:
        target.unlink()
        raise SystemExit(f"{target.name} came out over {MAX_BYTES} bytes, which the Player refuses")


def _save_render(source: Path, target: Path, longest_edge: int) -> None:
    """Keep a product render's transparency and aspect ratio, never its print crop."""
    from PIL import Image

    with Image.open(source) as picture:
        picture = picture.convert("RGBA")
        # Ignore the camera's empty margin while keeping the rendered shadow.
        bounds = picture.getchannel("A").getbbox()
        if bounds is None:
            raise ValueError(f"empty product render: {source.name}")
        picture = picture.crop(bounds)
        picture.thumbnail((longest_edge, longest_edge))
        target.parent.mkdir(parents=True, exist_ok=True)
        picture.save(target, "PNG", optimize=True)
    if target.stat().st_size > MAX_BYTES:
        target.unlink()
        raise ValueError(f"{target.name} exceeds the Player's art limit")


def meta_path(disc_dir: Path) -> Path:
    """Where this disc's document is, or where a new one goes (the root)."""
    for relative in META_SEARCH:
        candidate = disc_dir / relative
        if candidate.is_file():
            return candidate
    return disc_dir / META_NAME


def write_showcase_art(disc_dir: Path, *, wrap: Path | None = None, cover: Path | None = None, label: Path | None = None, case_render: Path | None = None, disc_render: Path | None = None) -> dict[str, str]:
    """Write the pictures beside the disc's document and name them in its ``art`` block. Returns the block.

    ``wrap`` is a whole case wrap to cut the front from; ``cover`` is an already-front picture (a dual disc's insert)
    used as it is. ``label`` is the disc label.
    """
    from PIL import Image

    document = meta_path(disc_dir)
    folder = document.parent
    art: dict[str, str] = {}
    if case_render is not None:
        _save_render(case_render, folder / "cover.png", COVER_LONGEST_EDGE)
        art["cover"] = "cover.png"
    elif wrap is not None:
        with Image.open(wrap) as image:
            _save_jpeg(image.crop(front_box(image.size)), folder / COVER_NAME, COVER_LONGEST_EDGE)
        art["cover"] = COVER_NAME
    elif cover is not None:
        with Image.open(cover) as image:
            _save_jpeg(image, folder / COVER_NAME, COVER_LONGEST_EDGE)
        art["cover"] = COVER_NAME
    if disc_render is not None:
        _save_render(disc_render, folder / "disc.png", DISC_LONGEST_EDGE)
        art["disc"] = "disc.png"
    elif label is not None:
        with Image.open(label) as image:
            _save_jpeg(image, folder / DISC_NAME, DISC_LONGEST_EDGE)
        art["disc"] = DISC_NAME

    data: dict = {}
    if document.is_file():
        data = json.loads(document.read_text(encoding="utf-8"))
    else:
        data = {"schema": 1, "made_by": "We the Indies"}
    data["art"] = {**(data.get("art") or {}), **art}
    document.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data["art"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Put real print art on a showcase disc folder.")
    parser.add_argument("disc", type=Path, help="the disc folder (holds BDMV/, VIDEO_TS/ or menu/)")
    parser.add_argument("--print-dir", type=Path, help="the title's print folder")
    parser.add_argument("--variant", default="", help="B or C for a Choose-your-cover title")
    parser.add_argument("--cover-file", type=Path, help="a front picture to use as it is (a dual disc's insert)")
    parser.add_argument("--disc-file", type=Path, help="the label to use")
    parser.add_argument("--case-render", type=Path, help="the existing transparent case PNG, displayed whole")
    parser.add_argument("--disc-render", type=Path, help="the existing transparent disc PNG, displayed whole")
    args = parser.parse_args(argv)

    if not args.disc.is_dir():
        print(f"not a folder: {args.disc}")
        return 2
    wrap = label = None
    if args.print_dir:
        wrap, label = find_print_files(args.print_dir, args.variant)
    label = args.disc_file or label
    if args.cover_file:
        wrap = None
    if wrap is None and args.cover_file is None and label is None and args.case_render is None and args.disc_render is None:
        print("no print art found: give --print-dir, or --cover-file and --disc-file")
        return 2
    art = write_showcase_art(args.disc, wrap=wrap, cover=args.cover_file, label=label, case_render=args.case_render, disc_render=args.disc_render)
    print(f"{meta_path(args.disc)}: art {art}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
