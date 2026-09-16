"""Build the test media the Player's suite runs against.

Everything here is generated, never committed: synthetic video from ffmpeg,
muxed to Blu-ray by tsMuxeR, then given a navigation layer — including a real
HDMV menu — by ``tests/fixtures/authoring``. Nothing in the output is anyone
else's content, so there is no licence question about any of it.

    python tools/make_fixtures.py            # build whatever is missing
    python tools/make_fixtures.py --force    # rebuild everything
    python tools/make_fixtures.py --list     # say what it would build

What comes out, in ``tests/fixtures/_generated``:

    bd_feature/     a plain Blu-ray: one title, three chapters, no menu
    bd_menu/        a Blu-ray with an HDMV menu: two buttons that go somewhere
    bd_menu.iso     the same disc as a UDF image
    dvd_disc/       a DVD-Video disc, tables written by hand — no dvdauthor needed
    dvd_menu_disc/  the same, with a real menu: buttons, subpicture, palette
    data_disc/      an ordinary data tree, standing in for an M-Disc archive
    game_disc/      a real Rialto fileset: setup.exe, menu/menu.exe, the lot
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tests.fixtures.authoring import bdmv, graphics, hdmv, spu, videots  # noqa: E402
from wti_player.formats import clpi as clpi_reader  # noqa: E402

OUT = REPO / "tests" / "fixtures" / "_generated"
SRC = OUT / "src"
TOOLS = REPO / "vendor" / "tools"

TSMUXER_VERSION = "2.7.0"
TSMUXER_URL = (
    f"https://github.com/justdan96/tsMuxer/releases/download/{TSMUXER_VERSION}/"
    f"tsMuxer-{TSMUXER_VERSION}-win64.zip"
)
TSMUXER_SHA256 = "e3cf117d2c6f01332188123641c63fe38ab9731ae7aa23645f6f9a261a7a301c"

#: 45 kHz, and the instant every Blu-ray convention starts a clip at.
CLIP_START_45K = 27_000_000

VIDEO_ARGS = [
    "-c:v", "libx264",
    "-profile:v", "high",
    "-level:v", "4.1",
    "-pix_fmt", "yuv420p",
    "-r", "24000/1001",
]
X264_OPTS = (
    "keyint=24:min-keyint=24:no-scenecut:ref=1:slices=4:"
    "nal-hrd=vbr:aud=1:colorprim=bt709:transfer=bt709:colormatrix=bt709"
)


class MissingTool(RuntimeError):
    pass


def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command, capture_output=True, text=True, check=False, **kwargs
    )
    if result.returncode != 0:
        raise MissingTool(
            f"{command[0]} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}"
        )
    return result


def require_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise MissingTool("ffmpeg is not on PATH — install it to build the video fixtures")
    return path


def require_tsmuxer() -> str:
    local = TOOLS / "tsMuxeR.exe"
    if local.is_file():
        return str(local)
    found = shutil.which("tsMuxeR") or shutil.which("tsmuxer")
    if found:
        return found
    print(f"fetching tsMuxeR {TSMUXER_VERSION}")
    TOOLS.mkdir(parents=True, exist_ok=True)
    archive = TOOLS / f"tsMuxer-{TSMUXER_VERSION}.zip"
    if not archive.exists():
        with urllib.request.urlopen(TSMUXER_URL, timeout=180) as response:
            archive.write_bytes(response.read())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != TSMUXER_SHA256:
        raise MissingTool(
            "tsMuxeR checksum mismatch\n"
            f"  expected {TSMUXER_SHA256}\n"
            f"  got      {digest}"
        )
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(TOOLS)
    if not local.is_file():
        raise MissingTool(f"tsMuxeR was not in {archive}")
    return str(local)


# --------------------------------------------------------------------------
# Source video
# --------------------------------------------------------------------------


def encode_feature(force: bool) -> Path:
    target = SRC / "feature.mkv"
    if target.exists() and not force:
        return target
    SRC.mkdir(parents=True, exist_ok=True)
    print("encoding the feature clip (12s, 3 chapters' worth)")
    run(
        [
            require_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24000/1001:duration=12",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=12",
            *VIDEO_ARGS,
            "-b:v", "2000k", "-maxrate", "2500k", "-bufsize", "5000k",
            "-x264opts", X264_OPTS + ":bframes=2:b-pyramid=none:vbv-maxrate=2500:vbv-bufsize=5000",
            "-c:a", "ac3", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-shortest", str(target),
        ]
    )
    return target


def encode_menu_background(force: bool) -> Path:
    target = SRC / "menu.mkv"
    if target.exists() and not force:
        return target
    SRC.mkdir(parents=True, exist_ok=True)
    background = SRC / "menu_bg.png"
    graphics.menu_background().save(background)

    print("encoding the menu background (6s still)")
    run(
        [
            require_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
            "-loop", "1", "-i", str(background), "-t", "6",
            *VIDEO_ARGS,
            "-b:v", "1500k", "-maxrate", "2000k", "-bufsize", "4000k",
            "-x264opts", X264_OPTS + ":bframes=0:vbv-maxrate=2000:vbv-bufsize=4000",
            str(target),
        ]
    )
    return target


def mux_blu_ray(source: Path, out_dir: Path, *, audio: bool, force: bool) -> Path:
    if (out_dir / "BDMV" / "STREAM" / "00000.m2ts").exists() and not force:
        return out_dir
    if out_dir.exists():
        shutil.rmtree(out_dir)
    meta = SRC / f"{out_dir.name}.meta"
    lines = [
        "MUXOPT --no-pcr-on-video-pid --new-audio-pes --blu-ray --vbr --vbv-len=500"
        " --custom-chapters=00:00:00.000;00:00:04.000;00:00:08.000",
        f'V_MPEG4/ISO/AVC, "{source}", fps=23.976, insertSEI, contSPS, track=1, lang=eng',
    ]
    if audio:
        lines.append(f'A_AC3, "{source}", track=2, lang=eng')
    meta.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"muxing {out_dir.name}")
    run([require_tsmuxer(), str(meta), str(out_dir)])
    return out_dir


# --------------------------------------------------------------------------
# The menu disc
# --------------------------------------------------------------------------

MENU_PLAYLIST = 0
FEATURE_PLAYLIST = 1
MOBJ_MENU = 0
MOBJ_FEATURE = 1


def build_menu() -> tuple[hdmv.Menu, list[bytes]]:
    """A two-button Top Menu: play the film, or jump to its second chapter."""
    palette = graphics.MenuPalette()
    palette.add(0, graphics.button_bitmap("PLAY THE FILM"))
    palette.add(1, graphics.button_bitmap("PLAY THE FILM", selected=True))
    palette.add(2, graphics.button_bitmap("CHAPTER TWO"))
    palette.add(3, graphics.button_bitmap("CHAPTER TWO", selected=True))
    palette.build()
    objects = palette.objects()
    buttons = (
        hdmv.Button(
            button_id=0,
            x=410,
            y=380,
            normal_object=0,
            selected_object=1,
            lower=1,
            commands=(hdmv.cmd_jump_title(1),),
        ),
        hdmv.Button(
            button_id=1,
            x=410,
            y=490,
            normal_object=2,
            selected_object=3,
            upper=0,
            commands=(hdmv.cmd_play_playlist_at_mark(FEATURE_PLAYLIST, 1),),
        ),
    )
    page = hdmv.Page(page_id=0, palette_id=0, buttons=buttons, default_selected=0)
    menu = hdmv.Menu(
        width=1280,
        height=720,
        frame_rate_code=hdmv.FRAME_RATE_23_976,
        palette=palette.palette(0),
        objects=objects,
        pages=[page],
    )
    return menu, menu.segments()


def assemble_menu_disc(menu_src: Path, feature_src: Path, target: Path) -> Path:
    """Put the menu clip and the feature clip on one disc, with our navigation."""
    if target.exists():
        shutil.rmtree(target)

    menu_clip = clpi_reader.read(menu_src / "BDMV" / "CLIPINF" / "00000.clpi")
    feature_clip = clpi_reader.read(feature_src / "BDMV" / "CLIPINF" / "00000.clpi")
    menu_m2ts = (menu_src / "BDMV" / "STREAM" / "00000.m2ts").read_bytes()
    feature_m2ts = (feature_src / "BDMV" / "STREAM" / "00000.m2ts").read_bytes()

    _menu, segments = build_menu()
    # The menu has to be decoded before the first frame it sits on top of.
    ig_pts = menu_clip.presentation_start * 2  # 45 kHz clip time -> 90 kHz PTS
    ig_packets = hdmv.ts_packets(hdmv.pes_packets(segments, ig_pts))
    print(
        f"  menu: {len(segments)} segments, "
        f"{sum(len(s) for s in segments)} bytes, {len(ig_packets)} transport packets"
    )
    menu_m2ts, inserted = bdmv.splice_interactive_graphics(menu_m2ts, ig_packets)
    menu_cpi = bdmv.shift_ep_map(
        bdmv.cpi_of((menu_src / "BDMV" / "CLIPINF" / "00000.clpi").read_bytes()), inserted
    )

    video = bdmv.StreamSpec(pid=0x1011, coding_type=bdmv.CODING_H264, format_rate=0x51)
    audio = bdmv.StreamSpec(
        pid=0x1100, coding_type=bdmv.CODING_AC3, language="eng", format_rate=0x31
    )
    interactive = bdmv.StreamSpec(pid=hdmv.IG_PID, coding_type=bdmv.CODING_IG, language="eng")

    menu_clpi = bdmv.build_clip_info(
        streams=(video, interactive),
        source_packet_count=len(menu_m2ts) // 192,
        ts_recording_rate=menu_clip.ts_recording_rate,
        pcr_pid=menu_clip.pcr_pid,
        pmt_pid=0x0100,
        presentation_start=menu_clip.presentation_start,
        presentation_end=menu_clip.presentation_end,
        cpi_block=menu_cpi,
    )

    menu_mpls = bdmv.build_playlist(
        items=[
            bdmv.PlayItemSpec(
                clip_id="00000",
                in_time=menu_clip.presentation_start,
                out_time=menu_clip.presentation_end,
                streams=(video, interactive),
                # An infinite still is what a real menu is: the clip runs out
                # and the last frame stays up until the viewer chooses. A menu
                # that loops instead keeps restarting the movie object, and a
                # button pressed across that seam confuses the HDMV VM.
                still_mode=0x02,
            )
        ],
        marks=[(0, menu_clip.presentation_start)],
    )
    feature_mpls = bdmv.build_playlist(
        items=[
            bdmv.PlayItemSpec(
                clip_id="00001",
                in_time=feature_clip.presentation_start,
                out_time=feature_clip.presentation_end,
                streams=(video, audio),
            )
        ],
        marks=[
            (0, feature_clip.presentation_start),
            (0, feature_clip.presentation_start + 4 * 45000),
            (0, feature_clip.presentation_start + 8 * 45000),
        ],
    )

    movie_objects = bdmv.build_movie_objects(
        [
            # 0: the menu. Play it, and when the clip runs out, play it again.
            bdmv.MovieObjectSpec(
                commands=(
                    hdmv.cmd_play_playlist(MENU_PLAYLIST),
                    hdmv.cmd_jump_object(MOBJ_MENU),
                )
            ),
            # 1: the feature. When it ends, the menu comes back.
            bdmv.MovieObjectSpec(
                commands=(
                    hdmv.cmd_play_playlist(FEATURE_PLAYLIST),
                    hdmv.cmd_jump_object(MOBJ_MENU),
                )
            ),
        ]
    )
    index = bdmv.build_index(
        first_play=MOBJ_MENU, top_menu=MOBJ_MENU, titles=[MOBJ_FEATURE, MOBJ_MENU]
    )

    bdmv.write_bdmv(
        target,
        {
            "BDMV/index.bdmv": index,
            "BDMV/MovieObject.bdmv": movie_objects,
            "BDMV/PLAYLIST/00000.mpls": menu_mpls,
            "BDMV/PLAYLIST/00001.mpls": feature_mpls,
            "BDMV/CLIPINF/00000.clpi": menu_clpi,
            "BDMV/CLIPINF/00001.clpi": (
                feature_src / "BDMV" / "CLIPINF" / "00000.clpi"
            ).read_bytes(),
            "BDMV/STREAM/00000.m2ts": menu_m2ts,
            "BDMV/STREAM/00001.m2ts": feature_m2ts,
        },
    )
    (target / "CERTIFICATE").mkdir(exist_ok=True)
    return target


# --------------------------------------------------------------------------
# The non-Blu-ray fixtures
# --------------------------------------------------------------------------


def build_dvd(target: Path, force: bool) -> Path:
    """A DVD-Video disc: a real VIDEO_TS around an ffmpeg-made VOB.

    `dvdauthor` is not on this machine and the Player's DVD support has to be
    testable before a real disc turns up, so the tables are written by hand —
    the same way the Blu-ray menu is.
    """
    if (target / "VIDEO_TS" / "VIDEO_TS.IFO").is_file() and not force:
        return target
    if target.exists():
        shutil.rmtree(target)

    vob = SRC / "dvd_title.vob"
    if not vob.exists() or force:
        print("encoding the DVD title (10s, 3 chapters)")
        run(
            [
                require_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=720x480:rate=30000/1001:duration=10",
                "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=10",
                "-target", "ntsc-dvd", "-shortest", str(vob),
            ]
        )

    sectors = vob.stat().st_size // videots.SECTOR
    title = videots.TitleSpec(
        cells=(
            videots.CellSpec(4000, 0, sectors // 3),
            videots.CellSpec(3000, sectors // 3 + 1, 2 * sectors // 3),
            videots.CellSpec(2984, 2 * sectors // 3 + 1, max(0, sectors - 1)),
        ),
        chapter_cells=(1, 2, 3),
    )
    videots.write_video_ts(
        target, vob, title=title, audio_languages=("en",), subtitle_languages=("en", "fr")
    )
    print("wrote a DVD-Video disc")
    return target


def build_dvd_menu_disc(target: Path, force: bool) -> Path:
    """A DVD with a menu on it: buttons, a subpicture, and a palette.

    The one fixture the DVD menu path could not be tested without. A menu is
    four things at once and each lives somewhere different — the chain and
    its palette in the IFO, the buttons in a NAV pack inside the video, the
    words on the buttons in a subpicture beside the video, and the colours a
    lit button uses in the NAV pack again. ffmpeg writes none of them; it is
    a muxer, not an authoring tool. So they are written here.
    """
    if (target / "VIDEO_TS" / "VTS_01_0.VOB").is_file() and not force:
        return target
    if target.exists():
        shutil.rmtree(target)

    title_vob = SRC / "dvd_title.vob"
    if not title_vob.exists():
        build_dvd(OUT / "dvd_disc", force=False)

    # The menu's video: a still, four seconds of it.
    menu_still = SRC / "dvd_menu_bg.png"
    graphics.menu_background(720, 480).save(menu_still)
    menu_video = SRC / "dvd_menu.vob"
    if not menu_video.exists() or force:
        print("encoding the DVD menu background (4s still)")
        run(
            [
                require_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                "-loop", "1", "-i", str(menu_still), "-t", "4",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-target", "ntsc-dvd", "-shortest", str(menu_video),
            ]
        )

    menu_vob = SRC / "dvd_menu_authored.vob"
    menu_vob.write_bytes(_authored_menu_vob(menu_video.read_bytes()))

    sectors = title_vob.stat().st_size // videots.SECTOR
    title = videots.TitleSpec(
        cells=(
            videots.CellSpec(4000, 0, sectors // 3),
            videots.CellSpec(3000, sectors // 3 + 1, 2 * sectors // 3),
            videots.CellSpec(2984, 2 * sectors // 3 + 1, max(0, sectors - 1)),
        ),
        chapter_cells=(1, 2, 3),
    )
    menu_sectors = menu_vob.stat().st_size // videots.SECTOR
    menu_chain = videots.TitleSpec(
        cells=(videots.CellSpec(4000, 0, max(0, menu_sectors - 1)),),
        chapter_cells=(1,),
    )
    videots.write_video_ts(
        target,
        title_vob,
        title=title,
        audio_languages=("en",),
        subtitle_languages=("en",),
        menus={"root": menu_chain, "title": menu_chain},
        menu_vob=menu_vob,
    )
    print("wrote a DVD-Video disc with a menu on it")
    return target


#: Two buttons, laid out where a 720x480 menu would put them.
MENU_BUTTONS = (
    videots.ButtonSpec(
        x_start=180, y_start=240, x_end=540, y_end=300,
        # LinkPGCN 2: play the title.
        command=bytes((0x30, 0x06, 0x00, 0x00, 0x00, 0x00, 0x00, 0x02)),
        down=2,
    ),
    videots.ButtonSpec(
        x_start=180, y_start=320, x_end=540, y_end=380,
        # LinkPTT: the film's second chapter.
        command=bytes((0x30, 0x05, 0x00, 0x00, 0x00, 0x00, 0x00, 0x02)),
        up=1,
    ),
)


def _authored_menu_vob(video: bytes) -> bytes:
    """A NAV pack, then the menu's subpicture, then ffmpeg's video."""
    words = [
        spu.box(360, 60, border=3, fill=2),   # PLAY THE FILM
        spu.box(360, 60, border=3, fill=2),   # CHAPTER TWO
    ]
    picture = bytearray()
    for index, rows in enumerate(words):
        picture += spu.build_subpicture(
            spu.SpuSpec(x_start=180, y_start=240 + index * 80, rows=rows)
        )
    subpicture = spu.build_subpicture(
        spu.SpuSpec(x_start=180, y_start=240, rows=_two_buttons())
    )

    sectors = (len(video) // videots.SECTOR) + 2
    nav = videots.build_nav_pack(
        sector=0,
        start_pts=0,
        end_pts=4 * 90_000,
        vobu_sectors=sectors,
        buttons=MENU_BUTTONS,
        selected=1,
    )
    spu_sector = spu.sector_with(spu.spu_pes_packets(subpicture, stream=0, pts=0))
    return nav + spu_sector + video


def _two_buttons() -> list[list[int]]:
    """The subpicture: two button-shaped boxes with a gap between them."""
    rows: list[list[int]] = []
    rows += spu.box(360, 60, border=3, fill=2)
    rows += [[0] * 360 for _ in range(20)]
    rows += spu.box(360, 60, border=3, fill=2)
    return rows


def build_data_disc(target: Path, force: bool) -> Path:
    """An ordinary archive tree, standing in for a twenty-year-old M-Disc."""
    if target.exists() and not force:
        return target
    if target.exists():
        shutil.rmtree(target)
    (target / "Photos" / "1998").mkdir(parents=True)
    (target / "Documents").mkdir(parents=True)
    (target / "README.TXT").write_text(
        "This disc was written to outlive the drive that wrote it.\r\n", encoding="ascii"
    )
    (target / "Documents" / "letter.txt").write_text("Dear future,\r\n", encoding="ascii")
    (target / "Photos" / "1998" / "beach.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 512)
    (target / "Photos" / "index.html").write_text("<h1>Photos</h1>", encoding="utf-8")
    return target


#: The document a WTI game disc carries, in the place it carries it.
GAME_DOCUMENT = {
    "schema": 1,
    "kind": "game",
    "title": "Shooty Shooty",
    "author": "A Studio",
    "publisher_text": "© 2026 A Studio.",
    "id": "shooty-shooty",
    "version": "1.2.0",
    "disc_label": "SHOOTY_SHOOTY",
    "made_by": "We the Indies",
    "game": {
        "launch_options": ["Play", "Play windowed"],
        "has_mod_tool": True,
        "has_bonus": True,
        "mac_build": True,
        "linux_build": True,
        "online_updates": False,
        "menu_language": "en",
    },
}


def build_game_disc(target: Path, force: bool) -> Path:
    """The shape a Rialto game disc actually has.

    This used to be an invention: a ``menu.exe`` at the disc root, an autorun
    saying ``open=menu.exe``, and ``Game/`` and ``Bonus/`` folders. Nothing
    the factory produces looks like that, and the Player's game-disc
    detection had been written against the invention — so every disc We The
    Indies has ever pressed would have read as a plain data disc, with a
    green test suite either way.

    The real fileset is ``rialto_core.disc_root.DISC_ROOT_FIXED`` plus
    ``DISC_ROOT_EXTRAS``, and a test over there guards it name for name. Two
    details are what matter here: the launcher is at ``menu/menu.exe``, and
    the autorun opens ``setup.exe`` rather than the launcher.

    The label carries an em dash and a curly apostrophe on purpose. Read as
    latin-1 rather than cp1252 those bytes come back as control codes.
    """
    if target.exists() and not force:
        return target
    if target.exists():
        shutil.rmtree(target)

    for folder in ("menu", "bonus", "Mac", "Linux"):
        (target / folder).mkdir(parents=True)

    # An em dash and a curly apostrophe: cp1252 has both, latin-1 does not.
    label = "Shooty Shooty — Director’s Cut"  # noqa: RUF001
    autorun = (
        "[AutoRun]\r\n"
        "Open=setup.exe\r\n"
        "Icon=disc_icon.ico\r\n"
        "IconFile=disc_icon.ico\r\n"
        "IconResource=disc_icon.ico,0\r\n"
        "IconIndex=0\r\n"
        f"Label={label}\r\n"
    )
    (target / "autorun.inf").write_bytes(autorun.encode("cp1252", "replace"))
    (target / "README.txt").write_text(
        "Shooty Shooty\r\n\r\nRun setup.exe to install.\r\n", encoding="cp1252"
    )
    (target / "setup.exe").write_bytes(b"MZ" + b"\x00" * 4096)
    (target / "disc_icon.ico").write_bytes(b"\x00\x00\x01\x00" + b"\x00" * 512)

    launch = '@start "" "%~dp0menu\\menu.exe"\r\n'
    (target / "menu.bat").write_text(launch, encoding="ascii")
    (target / "start_menu.bat").write_text(launch, encoding="ascii")

    (target / "menu" / "menu.exe").write_bytes(b"MZ" + b"\x00" * 2048)
    (target / "menu" / "menu_config.json").write_text(
        json.dumps({"title": "Shooty Shooty", "launch_options": ["Play"]}, indent=2),
        encoding="utf-8",
    )
    (target / "menu" / ".wti_meta.json").write_text(
        json.dumps(GAME_DOCUMENT, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    (target / "bonus" / "soundtrack.txt").write_text("01. Title theme\r\n", encoding="ascii")
    (target / "Mac" / "README.txt").write_text("Mac build.\r\n", encoding="ascii")
    (target / "Linux" / "README.txt").write_text("Linux build.\r\n", encoding="ascii")
    return target


def build_iso(source: Path, target: Path, label: str, force: bool) -> Path | None:
    """A UDF image of a folder, using oscdimg where the Windows ADK has it."""
    if target.exists() and not force:
        return target
    oscdimg = shutil.which("oscdimg") or _adk_oscdimg()
    if not oscdimg:
        print(f"  skipping {target.name}: no oscdimg (install the Windows ADK deployment tools)")
        return None
    target.unlink(missing_ok=True)
    run([oscdimg, "-u2", "-udfver102", f"-l{label}", str(source), str(target)])
    return target


def _adk_oscdimg() -> str | None:
    candidate = Path(
        r"C:\Program Files (x86)\Windows Kits\10\Assessment and Deployment Kit"
        r"\Deployment Tools\amd64\Oscdimg\oscdimg.exe"
    )
    return str(candidate) if candidate.is_file() else None


# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="rebuild even what exists")
    parser.add_argument("--list", action="store_true", help="say what would be built")
    args = parser.parse_args(argv)

    if args.list:
        print(f"fixtures live in {OUT}")
        for name, what in (
            ("bd_feature/", "plain Blu-ray, one title, three chapters (ffmpeg + tsMuxeR)"),
            ("bd_menu/", "Blu-ray with a hand-authored HDMV menu"),
            ("bd_menu.iso", "the menu disc as a UDF image (oscdimg)"),
            ("dvd_disc/", "a DVD-Video disc: hand-written VIDEO_TS around an ffmpeg VOB"),
            ("dvd_menu_disc/", "the same, with a menu: buttons, a subpicture and a palette"),
            ("data_disc/", "an ordinary data/M-Disc archive tree"),
            ("game_disc/", "a Rialto-shaped game disc"),
        ):
            state = "present" if (OUT / name.rstrip("/")).exists() else "missing"
            print(f"  {name:<14} {state:<8} {what}")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    feature_src = encode_feature(args.force)
    menu_src = encode_menu_background(args.force)

    feature_bd = mux_blu_ray(feature_src, OUT / "bd_feature", audio=True, force=args.force)
    menu_bd = mux_blu_ray(menu_src, OUT / "bd_menu_clip", audio=False, force=args.force)

    print("assembling the menu disc")
    assemble_menu_disc(menu_bd, feature_bd, OUT / "bd_menu")
    build_iso(OUT / "bd_menu", OUT / "bd_menu.iso", "WTI_MENU_TEST", args.force)
    build_iso(OUT / "bd_feature", OUT / "bd_feature.iso", "WTI_FEATURE", args.force)

    build_dvd(OUT / "dvd_disc", args.force)
    build_dvd_menu_disc(OUT / "dvd_menu_disc", args.force)
    build_data_disc(OUT / "data_disc", args.force)
    build_game_disc(OUT / "game_disc", args.force)
    build_iso(OUT / "game_disc", OUT / "game_disc.iso", "SHOOTY_SHOOTY", args.force)

    print(f"\nfixtures ready in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
