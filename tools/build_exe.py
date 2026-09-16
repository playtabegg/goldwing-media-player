"""Build ``dist\\Player.exe``.

    python tools/build_exe.py             # one folder, fast to start
    python tools/build_exe.py --onefile   # one file, slower to start
    python tools/build_exe.py --clean     # throw the caches away first

Signing happens at publish and nowhere else — this script never signs, and
never talks to Azure. What it produces is an unsigned build for testing;
``docs`` on the release runbook covers what happens to it after that.

The vendored VLC goes in beside the EXE as ``vlc\\``, which is the first place
``engine/libvlc_loader.py`` looks. Nothing about the build reaches into a
system VLC, so what is tested is what ships.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wti_player.version import APP_NAME, PUBLISHER, VERSION

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / "dist"
BUILD = REPO / "build"
VENDOR_VLC = REPO / "vendor" / "vlc"

#: VLC plugin folders the Player actually uses. Shipping all 363 plugins adds
#: ~90 MB of decoders for formats no disc carries, and pulls in plugins whose
#: licences we would then have to account for one by one.
PLUGIN_GROUPS = (
    "access",        # disc, file, ISO
    "audio_filter",
    "audio_mixer",
    "audio_output",
    "codec",
    "demux",
    "misc",
    "packetizer",
    "spu",           # subtitle and menu overlays
    "stream_filter",
    "text_renderer",
    "video_chroma",
    "video_filter",
    "video_output",
)


#: Plugins a disc player has no use for: video *encoders*, network and
#: capture sources, and players for formats no disc carries. Dropping them
#: takes about 35 MB off the download and takes their licences off the
#: attribution list with them. Every removal is checked by playing the
#: fixture discs from the built EXE afterwards.
PLUGIN_EXCLUDES = frozenset(
    {
        # encoders — the Player only ever decodes
        "libx264_plugin.dll",
        "libx265_plugin.dll",
        "libx26410b_plugin.dll",
        "libtwolame_plugin.dll",
        "libaom_plugin.dll",
        "libvpx_plugin.dll",
        "libschroedinger_plugin.dll",
        # network and capture — a disc player opens discs. The list used to
        # say this and name six; forty were shipping anyway, including a
        # screen recorder, a DVB tuner, an RTSP *server*, a last.fm
        # scrobbler, an online add-on repository and an audio fingerprinter.
        # A product whose notice says it does not phone anywhere should not
        # carry them, whether or not anything can reach them.
        "libaccess_srt_plugin.dll",
        "libvnc_plugin.dll",
        "libdcp_plugin.dll",
        "libdshow_plugin.dll",
        "libgnutls_plugin.dll",
        "libadaptive_plugin.dll",
        "libftp_plugin.dll",
        "libhttp_plugin.dll",
        "libhttps_plugin.dll",
        "libsmb_plugin.dll",
        "libnfs_plugin.dll",
        "libsftp_plugin.dll",
        "libtcp_plugin.dll",
        "libudp_plugin.dll",
        "librtp_plugin.dll",
        "librist_plugin.dll",
        "libsatip_plugin.dll",
        "liblive555_plugin.dll",
        "libaccess_mms_plugin.dll",
        "libsdp_plugin.dll",
        "libscreen_plugin.dll",
        "libshm_plugin.dll",
        "libdtv_plugin.dll",
        "libvdr_plugin.dll",
        "libdemux_chromecast_plugin.dll",
        "libstream_out_chromecast_plugin.dll",
        "libremoteosd_plugin.dll",
        "libaddonsvorepository_plugin.dll",
        "libaddonsfsstorage_plugin.dll",
        "libfingerprinter_plugin.dll",
        "libpodcast_plugin.dll",
        "libhds_plugin.dll",
        "librecord_plugin.dll",
        "libaccess_output_http_plugin.dll",
        "libaccess_output_udp_plugin.dll",
        "libaccess_output_livehttp_plugin.dll",
        "libaccess_output_srt_plugin.dll",
        "libaccess_output_shout_plugin.dll",
        "libaccess_output_file_plugin.dll",
        # formats that never appear on an optical disc
        "libsid_plugin.dll",
        "libgme_plugin.dll",
        "libspatialaudio_plugin.dll",
        "libmod_plugin.dll",
        "libfluidsynth_plugin.dll",
        "libcaca_plugin.dll",
        "libflaschen_plugin.dll",
        "libsdl_image_plugin.dll",
        # --- GPL-only plugins ---
        # These thirteen carry the GNU General Public License with no LGPL
        # option, while the notice we ship says libVLC is under the LGPL. A
        # disc player needs none of them, so the honest fix is to remove
        # them rather than to reword the sentence. (libavcodec is a separate
        # matter: VideoLAN configures ffmpeg with --enable-gpl, so the
        # decoder itself is GPL and cannot be dropped — the notice says so.)
        "libaccess_realrtsp_plugin.dll",
        "libmpc_plugin.dll",
        "libvod_rtsp_plugin.dll",
        "librotate_plugin.dll",
        "libaudioscrobbler_plugin.dll",
        "libexport_plugin.dll",
        "libreal_plugin.dll",
        "libmono_plugin.dll",
        "libheadphone_channel_mixer_plugin.dll",
        "libstats_plugin.dll",
        "libdolby_surround_decoder_plugin.dll",
        "libt140_plugin.dll",
        "liblogger_plugin.dll",
        # --- the DVD plugins, and why they are not here ---
        # VideoLAN's Windows build has libdvdcss compiled *into* these two.
        # The proof is in the binaries: "cracking disc key", "cracked disc
        # key is", "failed to crack the disc key" are libdvdcss's own
        # messages, and no separate libdvdcss.dll is named anywhere in
        # their imports. Shipping them would mean shipping a CSS
        # descrambler, which is the opposite of the line the About box
        # draws for Blu-ray, and the opposite of what the estate has said
        # everywhere else.
        #
        # Chandler's ruling, 2026-08-23: build libdvdread and libdvdnav
        # ourselves without libdvdcss before Sept 10. Unprotected DVDs
        # then play with their menus and a commercial DVD gets the same
        # honest refusal a commercial Blu-ray gets. Separately, pursue the
        # CSS licence from the DVD CCA on its own clock — that door is
        # open, unlike AACS — and if it lands, turning commercial DVDs on
        # is a change to this list.
        #
        # Until the clean build exists, no EXE we make carries these.
        "libdvdread_plugin.dll",
        "libdvdnav_plugin.dll",
    }
)

#: Qt ships these for uses the Player does not have. The software OpenGL
#: fallback alone is 20 MB.
QT_EXCLUDES = (
    "PyQt6/Qt6/bin/opengl32sw.dll",
    "PyQt6/Qt6/bin/Qt6Pdf.dll",
    "PyQt6/Qt6/bin/Qt6Network.dll",
    "PyQt6/Qt6/bin/Qt6Svg.dll",
    "PyQt6/Qt6/plugins/imageformats/qpdf.dll",
    "PyQt6/Qt6/plugins/imageformats/qsvg.dll",
    "PyQt6/Qt6/plugins/iconengines",
    "PyQt6/QtPdf.pyd",
    "PyQt6/QtNetwork.pyd",
    "PyQt6/QtSvg.pyd",
)


def vlc_datas() -> list[tuple[str, str]]:
    """(source, destination) pairs for the runtime we carry."""
    if not (VENDOR_VLC / "libvlc.dll").is_file():
        raise SystemExit("vendor/vlc is empty — run: python tools/fetch_vlc.py")
    datas: list[tuple[str, str]] = []
    for name in ("libvlc.dll", "libvlccore.dll", "COPYING.txt", "AUTHORS.txt"):
        source = VENDOR_VLC / name
        if source.is_file():
            datas.append((str(source), "vlc"))
    for group in PLUGIN_GROUPS:
        folder = VENDOR_VLC / "plugins" / group
        if not folder.is_dir():
            continue
        for plugin in sorted(folder.glob("*.dll")):
            if plugin.name not in PLUGIN_EXCLUDES:
                datas.append((str(plugin), f"vlc/plugins/{group}"))
    return datas


#: Where the typefaces go in the build. ``ui.theme._font_dir`` looks here
#: when it cannot find them beside the module, which is the frozen case.
FONT_DEST = "wti_player/ui/fonts"

#: The gold bird. ``ui.theme.MARK_DIR`` looks here in a frozen build.
MARK_DEST = "wti_player/ui/marks"

#: Where the licence texts land inside the installed program. Beside the EXE,
#: not buried: the GPL asks for them to travel with the binary, and a licence
#: nobody can find is not one that shipped.
LICENCE_DEST = "licences"

#: The icon Windows shows in the taskbar, the Alt-Tab card and the installer.
#: Drawn by tools/make_icon.py. Without it a build wears PyInstaller's mark,
#: which belongs to somebody else's project.
ICON = REPO / "wti_player" / "ui" / "player.ico"

#: The Windows version resource — what right-click ▸ Properties ▸ Details
#: shows. An EXE with no version block reads as something a person should not
#: run, and it is what a signature is attached to.
VERSION_FILE = REPO / "build" / "version_info.txt"


def font_datas() -> list[tuple[str, str]]:
    """The two typefaces the Player is set in, and the licence they are under.

    Without these the Player still runs and still plays discs — it just
    looks like every other Windows program, which is most of what the
    design was for.
    """
    folder = REPO / "wti_player" / "ui" / "fonts"
    files = sorted(folder.glob("*.ttf")) + sorted(folder.glob("OFL*.txt"))
    if not any(path.suffix == ".ttf" for path in files):
        raise SystemExit(
            "wti_player/ui/fonts has no typefaces — run: python tools/fetch_fonts.py"
        )
    return [(str(path), FONT_DEST) for path in files]


def mark_datas() -> list[tuple[str, str]]:
    """The gold bird, for the window icon and the top bar."""
    folder = REPO / "wti_player" / "ui" / "marks"
    files = sorted(folder.glob("*.png"))
    return [(str(path), MARK_DEST) for path in files]


def licence_datas() -> list[tuple[str, str]]:
    """The full licence texts, which the GPL requires us to include.

    Not a footnote. A build that ships GPL code without the licence text
    beside it is a build that cannot legally be handed to anyone, so this
    stops the build rather than warning.
    """
    folder = REPO / "licences"
    files = sorted(folder.glob("*.txt"))
    if not files:
        raise SystemExit(f"no licence texts in {folder}. The build will not ship without them.")
    out = [(str(path), LICENCE_DEST) for path in files]
    notice = REPO / "dist" / "LICENSE-NOTICE.txt"
    if notice.is_file():
        out.append((str(notice), "."))
    return out


def build_stamp_text() -> str:
    """``<short sha> <YYYY-MM-DD>`` from git, or ``unknown <date>`` outside one."""
    import datetime as _dt
    import subprocess as _sp

    date = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    try:
        sha = _sp.run(
            ["git", "rev-parse", "--short=9", "HEAD"],
            capture_output=True, text=True, check=True, cwd=str(REPO), timeout=10,
        ).stdout.strip()
        dirty = _sp.run(
            ["git", "status", "--porcelain", "--", "wti_player", "tools"],
            capture_output=True, text=True, check=True, cwd=str(REPO), timeout=10,
        ).stdout.strip()
    except Exception:
        return f"unknown {date}"
    return f"{sha}{'+' if dirty else ''} {date}"


def write_build_stamp(stamp: str) -> Path:
    """``wti_player/_build_stamp.py``, read by ``wti_player.version`` in a build."""
    path = REPO / "wti_player" / "_build_stamp.py"
    path.write_text(
        "# Written by tools/build_exe.py. Not in git; absent in a checkout.\n\n"
        f"BUILD_STAMP = {stamp!r}\n",
        encoding="utf-8",
    )
    return path


def write_version_info(path: Path, *, stamp: str = "") -> Path:
    """The Windows version resource, from the one place the version lives."""
    numbers = [int(part) for part in VERSION.split(".")][:4]
    numbers += [0] * (4 - len(numbers))
    quad = ", ".join(str(number) for number in numbers)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({quad}), prodvers=({quad}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([StringTable(u'040904B0', [
      StringStruct(u'Comments', u'build {stamp or "unknown"}'),
      StringStruct(u'CompanyName', u'{PUBLISHER}'),
      StringStruct(u'FileDescription', u'{APP_NAME}'),
      StringStruct(u'FileVersion', u'{VERSION}'),
      StringStruct(u'InternalName', u'Player'),
      StringStruct(u'LegalCopyright', u'{PUBLISHER}. Under the GNU General Public License v3.'),
      StringStruct(u'OriginalFilename', u'Player.exe'),
      StringStruct(u'ProductName', u'{APP_NAME}'),
      StringStruct(u'ProductVersion', u'{VERSION}')])]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )
    return path


def prune(root: Path) -> int:
    """Delete what PyInstaller pulled in that the Player does not use."""
    freed = 0
    for relative in QT_EXCLUDES:
        target = root / relative
        if target.is_file():
            freed += target.stat().st_size
            target.unlink()
        elif target.is_dir():
            freed += folder_size(target)
            shutil.rmtree(target)
    return freed


def write_spec(path: Path, *, onefile: bool) -> Path:
    stamp = build_stamp_text()
    write_build_stamp(stamp)
    write_version_info(VERSION_FILE, stamp=stamp)
    print(f"build stamp {stamp}")
    datas = ",\n        ".join(
        repr(pair) for pair in vlc_datas() + font_datas() + mark_datas() + licence_datas()
    )
    # Resolved here and written into the spec as literals. PyInstaller execs
    # the spec in its own namespace, so a name from this module is not in
    # scope there — writing `icon=str(ICON)` into the spec is a NameError at
    # build time, which is exactly how the previous build died.
    icon = repr(str(ICON)) if ICON.is_file() else "None"
    version = repr(str(VERSION_FILE)) if VERSION_FILE.is_file() else "None"
    body = f'''# Generated by tools/build_exe.py — edit that, not this.
# ruff: noqa
block_cipher = None

a = Analysis(
    [r"{REPO / 'Player.pyw'}"],
    pathex=[r"{REPO}"],
    binaries=[],
    datas=[
        {datas}
    ],
    hiddenimports=["vlc"],
    hookspath=[],
    runtime_hooks=[],
    # The Player has no use for these, and they are large.
    excludes=["tkinter", "numpy", "matplotlib", "PyQt5", "PySide6", "test", "unittest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
'''
    if onefile:
        body += '''
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Player",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon={icon},
    version={version},
)
'''
    else:
        body += f'''
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Player",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon={icon},
    version={version},
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="Player",
)
'''
    path.write_text(body, encoding="utf-8")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def folder_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onefile", action="store_true", help="one EXE, unpacked at each launch")
    parser.add_argument("--clean", action="store_true", help="clear build caches first")
    args = parser.parse_args(argv)

    if args.clean:
        for folder in (BUILD, DIST / "Player"):
            if folder.exists():
                shutil.rmtree(folder)

    spec = write_spec(REPO / "tools" / "player.spec", onefile=args.onefile)
    print(f"spec -> {spec}")

    started = time.monotonic()
    build_env = os.environ.copy()
    if sys.platform == "win32":
        # Qt uses the Windows ICU interface. An unrelated ICU DLL on PATH
        # (for example a document converter's runtime) has the same filename
        # but incompatible exports. Resolve OS DLLs from Windows first.
        windows_root = Path(build_env.get("SystemRoot", r"C:\Windows"))
        build_env["PATH"] = os.pathsep.join(
            [str(windows_root / "System32"), str(windows_root), build_env.get("PATH", "")]
        )
    result = subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm",
            "--distpath", str(DIST),
            "--workpath", str(BUILD),
            str(spec),
        ],
        cwd=str(REPO),
        env=build_env,
        check=False,
    )
    if result.returncode != 0:
        return result.returncode
    print(f"built in {time.monotonic() - started:.0f}s")

    # Only the one-folder build has an _internal tree, and pruning is only
    # meaningful there — a one-file EXE has everything inside the archive.
    # Run --onefile in a checkout that already has a one-folder build and
    # this used to happily report "pruned 25.6 MB" while deleting them out
    # of the *other* build: the one the installer packages.
    if not args.onefile:
        internal = DIST / "Player" / "_internal"
        if internal.is_dir():
            if sys.platform == "win32" and (internal / "icuuc.dll").exists():
                raise SystemExit(
                    "Refusing a bundled ICU DLL under the Windows system name. "
                    "Check DLL discovery before packaging: Qt requires the Windows ICU interface."
                )
            freed = prune(internal)
            print(f"pruned {freed / 1_048_576:.1f} MB the Player does not use")
    else:
        print("one-file build: nothing to prune (the excludes are inside the archive)")

    if args.onefile:
        exe = DIST / "Player.exe"
        print(f"\n{exe}")
        print(f"  {exe.stat().st_size / 1_048_576:.1f} MB")
        print(f"  sha256 {sha256(exe)}")
    else:
        folder = DIST / "Player"
        print(f"\n{folder / 'Player.exe'}")
        print(f"  folder {folder_size(folder) / 1_048_576:.1f} MB")
        # The hash that belongs on the download page is the hash of what
        # somebody downloads. For a one-folder build that is the archive, not
        # the bootloader stub — which does not change when the payload does.
        archive = Path(shutil.make_archive(str(DIST / f"Player-{VERSION}"), "zip", folder))
        print(f"\n{archive}")
        print(f"  {archive.stat().st_size / 1_048_576:.1f} MB")
        print(f"  sha256 {sha256(archive)}")
    print("\nUnsigned. Signing is a publish step, never a build step.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
