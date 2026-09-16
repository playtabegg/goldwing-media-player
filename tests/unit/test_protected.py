"""Protected and unsupported discs: what the Player says, and that it does
not try to play them anyway."""

from __future__ import annotations

import shutil

import pytest

from wti_player import strings
from wti_player.optical.identify import DiscKind, identify


class TestAacsDetection:
    def test_an_aacs_folder_marks_the_disc_encrypted(self, menu_disc, tmp_path) -> None:
        commercial = tmp_path / "commercial-bd"
        shutil.copytree(menu_disc, commercial)
        aacs = commercial / "AACS"
        aacs.mkdir()
        (aacs / "Unit_Key_RO.inf").write_bytes(b"\x00" * 64)

        profile = identify(commercial, label="A_REAL_MOVIE")

        assert profile.kind is DiscKind.BLU_RAY
        assert profile.protection == "aacs"
        assert profile.is_encrypted
        assert not profile.playable

    def test_an_empty_aacs_folder_is_not_taken_as_proof(self, menu_disc, tmp_path) -> None:
        # A disc we made could conceivably have a stray empty folder. Only
        # AACS's own files, or something actually in there, count.
        disc = tmp_path / "ours"
        shutil.copytree(menu_disc, disc)
        (disc / "AACS").mkdir()

        assert identify(disc).protection == ""

    def test_our_own_discs_are_never_flagged(self, menu_disc, feature_disc) -> None:
        assert identify(menu_disc).protection == ""
        assert identify(feature_disc).protection == ""
        assert identify(menu_disc).playable


class TestWhatItSays:
    @pytest.mark.parametrize(
        "text",
        [strings.PROTECTED_BLU_RAY, strings.PROTECTED_DVD],
    )
    def test_it_explains_rather_than_refuses(self, text: str) -> None:
        assert len(text.split("\n\n")) >= 2, "one line is not an explanation"
        assert "not supported" not in text.lower()
        assert "error" not in text.lower()
        assert "!" not in text

    def test_the_blu_ray_message_does_not_promise_what_we_cannot_do(self) -> None:
        # No "coming soon" on Blu-ray. There is no licence to go and get.
        text = strings.PROTECTED_BLU_RAY.lower()
        assert "going after it" not in text
        assert "when it lands" not in text

    def test_the_blu_ray_message_does_not_claim_we_were_refused(self) -> None:
        # We have never applied to AACS. Saying they will not sell to us is
        # stronger than anything we know, and someone would rightly call it.
        text = strings.PROTECTED_BLU_RAY.lower()
        for overreach in ("refused us", "will not sell", "not sold to", "at any price"):
            assert overreach not in text, overreach

    def test_the_blu_ray_message_does_not_slam_a_door_we_could_walk_through(
        self,
    ) -> None:
        # AACS does license software players; PowerDVD is one. The barrier is
        # cost, compliance and an ongoing obligation, not a law of physics.
        # Saying we can never do it would be as wrong as promising we will.
        text = strings.PROTECTED_BLU_RAY.lower()
        for absolute in ("never be able", "cannot ever", "impossible", "no one can"):
            assert absolute not in text, absolute

    def test_no_licence_fee_is_quoted_anywhere(self) -> None:
        # One verified number per pitch, and a second-hand licence fee is not
        # a verified number.
        for text in (strings.PROTECTED_BLU_RAY, strings.PROTECTED_DVD, strings.about_text()):
            assert "$" not in text
            assert "dollar" not in text.lower()

    def test_the_dvd_message_says_we_are_going_after_the_licence(self) -> None:
        text = strings.PROTECTED_DVD.lower()
        assert "licence" in text
        assert "going after it" in text
        assert "break the lock" in text

    def test_it_explains_current_support_without_a_platform_generalization(self) -> None:
        text = strings.PROTECTED_BLU_RAY
        assert "licensed playback software" in text
        assert "There is no release date yet" in text

    def test_both_say_why_we_make_discs(self) -> None:
        for text in (strings.PROTECTED_BLU_RAY, strings.PROTECTED_DVD):
            assert "outlive the company that sold it to you" in text


class TestTheBuildCannotShipADescrambler:
    """The guard that matters most, and the cheapest one to keep.

    VideoLAN's DVD plugins have libdvdcss compiled into them. If either ever
    reappears in a build, We The Indies is shipping a CSS descrambler — so
    this is checked on every run, with no build and no VLC needed.
    """

    def test_both_dvd_plugins_are_excluded_from_every_build(self) -> None:
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
        import build_exe

        assert "libdvdread_plugin.dll" in build_exe.PLUGIN_EXCLUDES
        assert "libdvdnav_plugin.dll" in build_exe.PLUGIN_EXCLUDES

    def test_a_built_tree_has_no_dvd_plugin_in_it(self) -> None:
        from pathlib import Path

        plugins = (
            Path(__file__).resolve().parents[2]
            / "dist"
            / "Player"
            / "_internal"
            / "vlc"
            / "plugins"
        )
        if not plugins.is_dir():
            pytest.skip("no build to check — run: python tools/build_exe.py")
        found = [path.name for path in plugins.rglob("*dvd*")]
        assert found == [], f"a DVD plugin got into the build: {found}"
