"""What the built EXE has to carry, checked without building one.

A build that is missing something is discovered on the machine it was
installed on, by somebody who was told the Player would look like the
screenshots. These are the cheap checks that stop that.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))


@pytest.fixture(scope="module")
def build_exe():
    import build_exe as module

    return module


class TestTypefacesShip:
    """A Player set in Segoe UI is a Player with the design taken out.

    Nothing here fails the *launch* — the fallback stacks are real and the
    program still plays discs. It fails the thing anyone would notice.
    """

    def test_the_font_files_are_in_the_repository(self):
        folder = REPO / "wti_player" / "ui" / "fonts"
        names = {path.name for path in folder.glob("*.ttf")}
        assert "Outfit.ttf" in names
        assert "PlayfairDisplay-Italic.ttf" in names

    def test_the_build_carries_them(self, build_exe):
        pairs = build_exe.font_datas()
        carried = {Path(source).name for source, _dest in pairs}
        assert "Outfit.ttf" in carried
        assert "PlayfairDisplay-Italic.ttf" in carried

    def test_the_build_carries_the_licence_they_are_under(self, build_exe):
        carried = {Path(source).name for source, _dest in build_exe.font_datas()}
        assert any(name.startswith("OFL") for name in carried), (
            "the OFL permits bundling and asks for exactly one thing in return"
        )

    def test_they_go_where_the_theme_looks_for_them(self, build_exe):
        """The two halves of this agreement live in different files."""
        destinations = {destination for _source, destination in build_exe.font_datas()}
        assert destinations == {build_exe.FONT_DEST}
        assert build_exe.FONT_DEST.replace("/", "\\").endswith(
            str(Path("wti_player") / "ui" / "fonts")
        )

    def test_a_built_tree_actually_has_them(self):
        internal = REPO / "dist" / "Player" / "_internal" / "wti_player" / "ui" / "fonts"
        if not (REPO / "dist" / "Player").is_dir():
            pytest.skip("no build to check — run: python tools/build_exe.py")
        assert internal.is_dir(), f"the build has no typefaces at {internal}"
        assert any(internal.glob("*.ttf"))


class TestTheGoldBirdShips:
    def test_the_mark_is_in_the_repository(self):
        assert (REPO / "wti_player" / "ui" / "marks" / "goldwing.png").is_file()

    def test_the_build_carries_it(self, build_exe):
        carried = {Path(source).name for source, _dest in build_exe.mark_datas()}
        assert "goldwing.png" in carried
        destinations = {dest for _source, dest in build_exe.mark_datas()}
        assert destinations == {build_exe.MARK_DEST}


class TestTheThemeFindsThem:
    def test_from_source(self):
        from wti_player.ui import theme

        assert theme.FONT_DIR.is_dir()
        assert any(theme.FONT_DIR.glob("*.ttf"))

    def test_from_a_frozen_build(self, monkeypatch, tmp_path):
        """PyInstaller lays package data beside the modules, not inside them."""
        from wti_player.ui import theme

        fonts = tmp_path / "wti_player" / "ui" / "fonts"
        fonts.mkdir(parents=True)
        (fonts / "Outfit.ttf").write_bytes(b"\x00\x01\x00\x00")

        monkeypatch.setattr(theme, "__file__", str(tmp_path / "nowhere" / "theme.py"))
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        assert theme._font_dir() == fonts

    def test_a_build_with_no_typefaces_is_refused_rather_than_shipped(
        self, build_exe, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(build_exe, "REPO", tmp_path)
        (tmp_path / "wti_player" / "ui" / "fonts").mkdir(parents=True)
        with pytest.raises(SystemExit):
            build_exe.font_datas()


class TestWhatShipsBesideTheExe:
    """The GPL is not satisfied by a sentence in an About box.

    A build that carries GPL code has to carry the licence text with it and
    say where the source is. This program did neither for its first four
    months, while telling people in writing that its engine was LGPL.
    """

    def test_the_licence_texts_are_in_the_build(self):
        import sys

        sys.path.insert(0, "tools")
        import build_exe

        destinations = {dest for _source, dest in build_exe.licence_datas()}
        assert build_exe.LICENCE_DEST in destinations

    def test_every_licence_we_name_is_actually_there(self):
        from pathlib import Path

        folder = Path("licences")
        names = {path.name for path in folder.glob("*.txt")}
        assert {"GPL-3.0.txt", "GPL-2.0.txt", "LGPL-2.1.txt"} <= names
        # The text, not a byte count (GW-3, 15 Sep 2026): the LGPL-3.0 is 7,652
        # bytes because it is written as additional permissions on top of the
        # GPL-3.0, and a 10,000-byte floor failed the real licence.
        for path in folder.glob("*.txt"):
            assert path.stat().st_size > 5_000, f"{path.name} is too short to be a licence"
            if "GPL" in path.name:
                text = path.read_text(encoding="utf-8", errors="replace").upper()
                assert "GNU" in text and "GENERAL PUBLIC LICENSE" in text, f"{path.name} does not read as a GNU licence"

    def test_the_notice_names_the_gpl_decoders_that_are_present(self):
        import sys

        sys.path.insert(0, "tools")
        import licence_notice

        text = licence_notice.notice()
        for description in licence_notice.gpl_plugins_present():
            assert description in text

    def test_the_notice_does_not_claim_the_engine_is_only_lgpl(self):
        """It did, and the vendored libavcodec says GPL in its own strings."""
        import sys

        sys.path.insert(0, "tools")
        import licence_notice

        flat = " ".join(licence_notice.notice().split())
        assert "the program as a whole is under the GNU General Public License, version 3" in flat
        assert "complete source of this program" in flat
        assert "GPL-3.0.txt" in flat

    def test_the_installer_writes_the_same_notice(self):
        import sys

        sys.path.insert(0, "tools")
        import build_installer
        import licence_notice

        assert not hasattr(build_installer, "write_notice")
        assert "licence_notice" in Path("tools/build_installer.py").read_text(
            encoding="utf-8"
        )
        assert "Lesser General Public License version 2.1 or later" not in licence_notice.notice()

    def test_the_exe_carries_an_icon_and_a_version(self):
        import sys

        sys.path.insert(0, "tools")
        import build_exe

        assert build_exe.ICON.is_file(), "run: python tools/make_icon.py"
        written = build_exe.write_version_info(build_exe.VERSION_FILE)
        text = written.read_text(encoding="utf-8")
        assert "Goldwing Media Player" in text
        assert "General Public License" in text


class TestTheExclusionsActuallyExclude:
    """A plugin name that matches nothing is a silent no-op.

    Two entries named files that do not exist — `libmms_plugin.dll` when the
    real name is `libaccess_mms_plugin.dll`, and `libchromecast_plugin.dll`
    when it is `libdemux_chromecast_plugin.dll` — so both plugins shipped
    from every clean build, under a notice saying the Player does not phone
    anywhere.
    """

    def test_every_exclusion_names_a_real_plugin(self):
        import sys

        sys.path.insert(0, "tools")
        import build_exe

        root = build_exe.VENDOR_VLC / "plugins"
        if not root.is_dir():
            import pytest

            pytest.skip("run: python tools/fetch_vlc.py")

        # These two are stripped from the checkout by fetch_vlc.py, so they
        # match nothing on purpose. Everything else must match a file.
        already_gone = {"libdvdread_plugin.dll", "libdvdnav_plugin.dll"}
        missing = [
            name
            for name in sorted(build_exe.PLUGIN_EXCLUDES)
            if name not in already_gone and not any(root.rglob(name))
        ]
        assert missing == [], f"these exclusions match no file: {missing}"
