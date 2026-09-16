"""Write the notice that ships with the Player.

Generated rather than hand-kept, because the thing it describes changes: a
plugin gets excluded, a library gets added, and a hand-written notice quietly
stops being true. This reads what is actually in ``vendor/vlc`` and names it.

    python tools/licence_notice.py            # write dist/LICENSE-NOTICE.txt
    python tools/licence_notice.py --check    # fail if the shipped one is stale

What it is for: everything in the Player that somebody else wrote, what
licence it came under, and — for the copyleft ones — where to get its source.
Getting this wrong is not a style problem. Shipping a GPL library while
telling people it is LGPL is a licence breach, and it was true of this
program until it was checked.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from wti_player.version import APP_NAME, PUBLISHER, VERSION  # noqa: E402

VENDOR = REPO / "vendor" / "vlc"
OUT = REPO / "dist" / "LICENSE-NOTICE.txt"

#: Where the Player's own source lives, for the GPL's "corresponding source"
#: requirement. The website's /player/source page (wetheindies-web, W19): it
#: is live regardless of the download curtain, names the public repository
#: and the tagged release, and the web suite pins it to this exact string.
#: ``tests/unit/test_public_readiness.py`` proves the page's repository link
#: is the one the update feed is published from.
SOURCE_URL = "https://wetheindies.com/player/source"

#: The plugins that carry the GPL rather than the LGPL, and what is in them.
#: Checked by reading the DLLs, not by reading a web page: libavcodec_plugin
#: contains the string "libavformat license: GPL version 2 or later" and the
#: configure line it was built with contains --enable-gpl.
GPL_PLUGINS = {
    "libavcodec_plugin.dll": (
        "FFmpeg (libavcodec, libavformat, libswscale), built by VideoLAN with "
        "--enable-gpl, so GPL version 2 or later"
    ),
    "libmad_plugin.dll": "libmad, GPL version 2 or later",
    "libfaad_plugin.dll": "FAAD2, GPL version 2 or later",
    "libzvbi_plugin.dll": "libzvbi, GPL version 2 or later",
    "liba52_plugin.dll": "liba52, GPL version 2 or later",
    "libdca_plugin.dll": "libdca, GPL version 2 or later",
}

#: Everything else worth naming, with the licence it comes under. Not a
#: complete bill of materials for VLC — a complete one would be VLC's own —
#: but every library whose licence asks to be named.
THIRD_PARTY = (
    ("libVLC and libVLCcore", "the VideoLAN team", "LGPL version 2.1 or later"),
    ("libbluray", "the VideoLAN team", "LGPL version 2.1 or later"),
    ("FreeType", "David Turner, Robert Wilhelm and Werner Lemberg", "the FreeType Licence"),
    ("libass", "the libass authors", "the ISC Licence"),
    ("dav1d", "the VideoLAN team", "the 2-clause BSD Licence"),
    ("mpg123", "the mpg123 project", "LGPL version 2.1"),
    ("libsamplerate", "Erik de Castro Lopo", "the 2-clause BSD Licence"),
    ("libogg, libvorbis, libopus, FLAC", "the Xiph.Org Foundation", "the 3-clause BSD Licence"),
    ("libpng", "the PNG Development Group", "the libpng Licence"),
    ("zlib", "Jean-loup Gailly and Mark Adler", "the zlib Licence"),
    ("Lua", "PUC-Rio", "the MIT Licence"),
    ("libmatroska and libebml", "the Matroska project", "LGPL version 2.1"),
    ("Qt", "The Qt Company", "LGPL version 3"),
    # GOLD-5 (11 Sep 2026): four libraries statically linked into shipped
    # plugins (libspeex_plugin, libtheora_plugin, libjpeg_plugin,
    # libxml_plugin) whose licences ask to be named, and were not.
    ("Speex", "the Xiph.Org Foundation", "the 3-clause BSD Licence"),
    ("Theora", "the Xiph.Org Foundation", "the 3-clause BSD Licence"),
    ("libjpeg", "the Independent JPEG Group", "the IJG Licence"),
    ("libxml2", "Daniel Veillard and contributors", "the MIT Licence"),
    ("Playfair Display and Outfit", "their designers", "the SIL Open Font Licence 1.1"),
    # Not VLC's: the Python runtime the Player is frozen with carries
    # OpenSSL for its ssl module. Named because its licence asks to be, and
    # because a reader of this file deserves to know it is there. The Player
    # opens no network connection on its own.
    ("OpenSSL (libssl, libcrypto)", "the OpenSSL Project", "the Apache License 2.0"),
)


def gpl_plugins_present() -> list[str]:
    """The GPL-licensed plugins actually in the vendored runtime."""
    plugins = VENDOR / "plugins"
    if not plugins.is_dir():
        return []
    found = []
    for name, description in sorted(GPL_PLUGINS.items()):
        if any(plugins.rglob(name)):
            found.append(description)
    return found


def notice() -> str:
    lines = [
        f"{APP_NAME} {VERSION}",
        PUBLISHER,
        "",
        "This build plays discs. It does not phone anywhere or keep an account.",
        "It checks for a new version only when you ask it to, from the Help menu,",
        "and it keeps nothing about that check.",
        "",
        "Copy-protected commercial discs will not play: AACS Blu-rays, and DVDs",
        "with CSS. We would rather pay for the key than break the lock, and this",
        "build carries neither licence and no code that breaks either one.",
        "",
        "This program's licence",
        "----------------------",
        f"{APP_NAME} is built on libraries under the GNU General Public License,",
        "so the program as a whole is under the GNU General Public License,",
        "version 3 or later. The full text is installed beside this file as",
        "GPL-3.0.txt.",
        "",
        "That gives you the right to the complete source of this program. It is",
        f"at {SOURCE_URL}. If that address ever stops working, write to",
        f"{PUBLISHER} and we will send it to you.",
        "",
        "Software under the GPL in this build",
        "------------------------------------",
        "The user interface uses Qt through PyQt6, copyright Riverbank Computing,",
        "under the GNU General Public License version 3.",
        "",
    ]

    gpl = gpl_plugins_present()
    if gpl:
        lines.append("Playback uses these decoders, each under the GPL:")
        lines += [f"  - {item}" for item in gpl]
    else:
        lines.append("No GPL-licensed decoders are included in this build.")
    lines += [
        "",
        "Their source is available from VideoLAN at",
        "https://www.videolan.org/vlc/download-sources.html, and from us on the",
        "same terms as above.",
        "",
        "Everything else",
        "---------------",
    ]
    for name, holder, licence in THIRD_PARTY:
        lines.append(f"  {name}")
        lines.append(f"    copyright {holder}, under {licence}")
    lines += [
        "",
        "The GPL version 3, GPL version 2, LGPL version 3, LGPL version 2.1 and",
        "Apache 2.0 texts are all installed beside this file. libVLC is a separate library",
        "that this program calls; it is not modified, and it can be replaced with",
        "another build of the same version.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the shipped file is stale")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    text = notice()
    if args.check:
        try:
            current = args.out.read_text(encoding="utf-8")
        except OSError:
            print(f"{args.out} is not there. Run this without --check.")
            return 1
        if current != text:
            print(f"{args.out} does not match what the build would write.")
            return 1
        print(f"{args.out} is current.")
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out} ({len(text)} bytes)")
    gpl = gpl_plugins_present()
    print(f"  {len(gpl)} GPL decoder(s) named")
    return 0


if __name__ == "__main__":
    sys.exit(main())
