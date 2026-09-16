"""Shared fixtures.

Most of the suite runs on structures built in memory by
``tests/fixtures/authoring``, so a fresh clone with no ffmpeg, no tsMuxeR and
no VLC still goes green. The tests that genuinely need media or an engine are
marked ``media`` / ``engine`` and skip with a message that says what to run.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Every widget test runs without a screen. Set before PyQt6 is imported by
# anything, which is why it lives here and not in a test module.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

GENERATED = Path(__file__).parent / "fixtures" / "_generated"


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole run. Qt will not have two."""
    pytest.importorskip("PyQt6.QtWidgets")
    from PyQt6.QtWidgets import QApplication

    from wti_player.ui.theme import load_fonts

    application = QApplication.instance() or QApplication([])
    load_fonts()
    yield application


@pytest.fixture(scope="session")
def generated_dir() -> Path:
    return GENERATED


@pytest.fixture
def menu_disc() -> Path:
    path = GENERATED / "bd_menu"
    if not (path / "BDMV" / "index.bdmv").is_file():
        pytest.skip("run: python tools/make_fixtures.py")
    return path


@pytest.fixture
def feature_disc() -> Path:
    path = GENERATED / "bd_feature"
    if not (path / "BDMV" / "index.bdmv").is_file():
        pytest.skip("run: python tools/make_fixtures.py")
    return path


@pytest.fixture
def data_disc() -> Path:
    path = GENERATED / "data_disc"
    if not path.is_dir():
        pytest.skip("run: python tools/make_fixtures.py")
    return path


@pytest.fixture
def game_disc() -> Path:
    path = GENERATED / "game_disc"
    if not path.is_dir():
        pytest.skip("run: python tools/make_fixtures.py")
    return path


@pytest.fixture(scope="session")
def libvlc():
    """The loaded ``vlc`` module, or a skip if no runtime is installed."""
    from wti_player.engine.libvlc_loader import LibVlcNotFound, load_vlc

    try:
        return load_vlc()
    except LibVlcNotFound:
        pytest.skip("no VLC runtime, run: python tools/fetch_vlc.py")


@pytest.fixture(scope="session")
def hidden_surface(qapp):
    """One window for libvlc to draw into, parked off the side of the desktop.

    Without a drawable, libvlc opens a window of its own, and a test run
    flashes one up per test: ugly to watch, and it steals focus from whatever
    the machine was doing.

    It has to be a REAL, mapped window. A widget that is created but never
    shown has no surface to present into, and playback stalls at position
    zero with the engine reporting PLAYING — which is a worse problem than
    the one being solved, and is how this was found.

    So: shown, but at a coordinate no monitor covers, and marked so it never
    takes the focus on the way there.
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QWidget

    surface = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
    surface.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    surface.setGeometry(-4000, -4000, 640, 480)
    surface.show()
    handle = int(surface.winId())
    yield handle
    surface.hide()
    surface.deleteLater()


@pytest.fixture
def engine(libvlc, hidden_surface):
    """A real engine that draws nowhere anybody can see.

    Software decoding: an overlay cannot be blended onto every hardware
    surface, and the tests that use this care about menus.
    """
    from wti_player.engine.vlc_engine import VlcEngine

    made = VlcEngine(hardware_decoding=False)
    made.set_video_window(hidden_surface)
    yield made
    made.release()


@pytest.fixture
def dvd_disc() -> Path:
    path = GENERATED / "dvd_disc"
    if not (path / "VIDEO_TS" / "VIDEO_TS.IFO").is_file():
        pytest.skip("run: python tools/make_fixtures.py")
    return path


@pytest.fixture
def broken_seek_disc(feature_disc, tmp_path) -> Path:
    """A real Blu-ray with three bad bytes in its entry-point map.

    A scratch on a disc does not produce a file that fails to parse; it
    produces a file that parses into a number pointing somewhere it should
    not. Here every coarse entry claims a fine entry far past the end of its
    own table, which is the shape of the crash: libbluray follows the pointer
    without checking it.
    """
    import shutil

    disc = tmp_path / "scratched"
    shutil.copytree(feature_disc, disc)
    for clip in (disc / "BDMV" / "CLIPINF").glob("*.clpi"):
        data = bytearray(clip.read_bytes())
        cpi = int.from_bytes(data[16:20], "big")
        ep_map = cpi + 6
        # The first PID's entry: coarse count, fine count, table address.
        packed = int.from_bytes(data[ep_map + 4 : ep_map + 10], "big")
        coarse = (packed >> 18) & 0xFFFF
        start = int.from_bytes(data[ep_map + 10 : ep_map + 14], "big")
        table = ep_map + start + 4
        for index in range(max(1, coarse)):
            at = table + index * 8
            data[at : at + 4] = (0x3FFFF << 14).to_bytes(4, "big")
        clip.write_bytes(bytes(data))
    return disc


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path_factory: pytest.TempPathFactory) -> None:
    """No test writes to the real registry: QSettings go to an ini under tmp."""
    try:
        from PyQt6.QtCore import QSettings
    except ImportError:  # pragma: no cover - a checkout without Qt
        return
    root = tmp_path_factory.mktemp("qsettings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(root))
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(root))
