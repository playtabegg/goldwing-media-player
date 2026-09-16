"""Fetch the two typefaces the Player is set in.

Playfair Display and Outfit are the faces the We The Indies pages use, and
the Player uses them so that the site and the program are recognisably the
same hand. Both are under the SIL Open Font License 1.1, which permits
bundling them inside an application; the licence text is fetched with them
and ships beside them, which is the one thing the OFL asks for.

They are VARIABLE fonts — one file carrying every weight along an axis —
because that is the only form upstream publishes now, and because three
files are less to ship than eleven. ``ui.fonts`` deals with what Qt makes
of that.

Run once. The files are committed, so nobody needs a network connection to
build the Player.

    python tools/fetch_fonts.py
"""

from __future__ import annotations

import sys
import urllib.parse
import urllib.request
from pathlib import Path

DESTINATION = Path(__file__).resolve().parent.parent / "wti_player" / "ui" / "fonts"

BASE = "https://raw.githubusercontent.com/google/fonts/main/ofl/"

WANTED = (
    ("outfit/Outfit[wght].ttf", "Outfit.ttf"),
    ("playfairdisplay/PlayfairDisplay[wght].ttf", "PlayfairDisplay.ttf"),
    ("playfairdisplay/PlayfairDisplay-Italic[wght].ttf", "PlayfairDisplay-Italic.ttf"),
    ("outfit/OFL.txt", "OFL-Outfit.txt"),
    ("playfairdisplay/OFL.txt", "OFL-PlayfairDisplay.txt"),
)


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "wti-player-fetch-fonts/1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main() -> int:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    failures = 0
    for remote, local in WANTED:
        url = BASE + urllib.parse.quote(remote)
        try:
            data = get(url)
        except Exception as error:
            print(f"  {local:<30} FAILED: {error}")
            failures += 1
            continue
        if local.endswith(".ttf") and data[:4] not in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
            print(f"  {local:<30} not a TrueType file ({data[:4]!r})")
            failures += 1
            continue
        (DESTINATION / local).write_bytes(data)
        print(f"  {local:<30} {len(data):>8,} bytes")

    print(f"\n  -> {DESTINATION}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
