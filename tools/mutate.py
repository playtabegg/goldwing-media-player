"""Break the code on purpose and see whether a test notices.

A green suite says the tests pass. It does not say they would fail if the
code were wrong, and those are different claims. This checks the second one:
each entry below is a real defect, applied to a real file, with the suite run
against it and the file put back afterwards whatever happens.

    python tools/mutate.py
    python tools/mutate.py --list

Every mutation here is one that DID survive when it was first tried, on
2026-08-23. They are kept rather than deleted so that a later change cannot
quietly undo the test that killed it.

This is not a mutation-testing framework and does not want to be. Ten checks
that run in a minute get used; ten thousand that run overnight do not.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Mutation:
    """One defect, and where a test should catch it."""

    name: str
    #: What would break for somebody using the Player.
    consequence: str
    file: str
    old: str
    new: str
    selection: tuple[str, ...] = ("tests/unit/",)


MUTATIONS = (
    Mutation(
        name="the DVD title count, uncapped",
        consequence="a table claiming 65535 titles is 65535 scans of the file",
        file="wti_player/formats/ifo.py",
        old="    count = min(_u16(data, start), MAX_TITLES_PER_SET)",
        new="    count = _u16(data, start)",
        selection=("tests/unit/test_hostile_disc.py",),
    ),
    Mutation(
        name="the art path guard, deleted",
        consequence="a disc could name a file outside its own folder and have it shown",
        file="wti_player/optical/meta.py",
        old=(
            '    if not name or "\\\\" in name or "/" in name or name.startswith("."):\n'
            "        return None\n"
            "    if Path(name).name != name:\n"
            "        return None\n"
        ),
        new="",
        selection=("tests/unit/test_disc_meta.py",),
    ),
    Mutation(
        name="the DVD stream tables, emptied",
        consequence="every DVD shows an empty audio picker and no subtitles",
        file="wti_player/formats/ifo.py",
        old="    return tuple(audio), tuple(subtitles)",
        new="    return (), ()",
    ),
    Mutation(
        name="the program chain palette, read 16 bytes late",
        consequence="every DVD menu is drawn in whatever bytes happened to be there",
        file="wti_player/formats/ifo.py",
        old="_PGC_PALETTE = 0xA4",
        new="_PGC_PALETTE = 0xB4",
    ),
    Mutation(
        name="vob_files, including the menu VOB",
        consequence="the menu plays before the film on every disc that has one",
        file="wti_player/formats/ifo.py",
        old='f"VTS_{title.title_set:02d}_[1-9].VOB"',
        new='f"VTS_{title.title_set:02d}_[0-9].VOB"',
    ),
    Mutation(
        name="yuv_to_rgb with Cb and Cr swapped",
        consequence="a red menu button renders blue",
        file="wti_player/formats/dvd_spu.py",
        old="def yuv_to_rgb(y: int, cb: int, cr: int) -> tuple[int, int, int]:",
        new="def yuv_to_rgb(y: int, cr: int, cb: int) -> tuple[int, int, int]:",
    ),
    Mutation(
        name="the DVD chapter table, unbounded again",
        consequence="a malformed disc hangs the Player the moment it goes in",
        file="wti_player/formats/ifo.py",
        old=(
            "        stop = min(start + end, len(data), position + MAX_CHAPTERS * 4)"
        ),
        new="        stop = min(start + end, len(data))",
        selection=("tests/unit/test_hostile_disc.py",),
    ),
    Mutation(
        name="the subpicture size clamp, removed",
        consequence="six kilobytes off a disc becomes a 269MB bitmap on the GUI thread",
        file="wti_player/formats/dvd_spu.py",
        old="    if area.width > MAX_WIDTH or area.height > MAX_HEIGHT:",
        new="    if False:",
        selection=("tests/unit/test_hostile_disc.py",),
    ),
    Mutation(
        name="the DVD menu key, back below the navigation branch",
        consequence="the menu button does nothing, silently, on every DVD",
        file="wti_player/ui/main_window.py",
        old=(
            "        if action in (PlayerAction.TOP_MENU, PlayerAction.POPUP_MENU) "
            "and self._is_dvd:"
        ),
        new="        if False:",
        selection=("tests/unit/test_dvd_menu_reachable.py",),
    ),
    Mutation(
        name="the DVD title number, off by one again",
        consequence="a menu's Play button plays nothing and reports a problem",
        file="wti_player/ui/main_window.py",
        old="            number = action.title or self._chosen_title or 1",
        new="            number = max(0, action.title - 1) if action.title else 0",
        selection=("tests/unit/test_dvd_menu_reachable.py",),
    ),
)


def apply(mutation: Mutation, quiet: bool) -> bool | None:
    """True if a test caught it, False if none did, None if it would not apply."""
    path = REPO / mutation.file
    original = path.read_text(encoding="utf-8")
    if mutation.old not in original:
        print(f"  STALE    {mutation.name}")
        print("           the code it edits has moved; this check is not running")
        return None

    path.write_text(original.replace(mutation.old, mutation.new, 1), encoding="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *mutation.selection, "-q", "--no-header", "-x"],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
    finally:
        # Whatever happened, including a keyboard interrupt.
        path.write_text(original, encoding="utf-8")

    killed = result.returncode != 0
    print(f"  {'KILLED  ' if killed else 'SURVIVED'} {mutation.name}")
    if not killed:
        print(f"           nothing noticed. If this shipped: {mutation.consequence}")
    elif not quiet:
        print(f"           ({mutation.consequence})")
    return killed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Break the code and see if a test notices.")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--quiet", action="store_true", help="only report the failures")
    args = parser.parse_args(argv)

    if args.list:
        for mutation in MUTATIONS:
            print(f"  {mutation.name}\n      {mutation.file}\n      {mutation.consequence}")
        return 0

    print("\nBreaking the code on purpose. Every file is put back.\n")
    survived = [entry for entry in MUTATIONS if apply(entry, args.quiet) is False]
    print(f"\n{len(MUTATIONS) - len(survived)} of {len(MUTATIONS)} caught.\n")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
