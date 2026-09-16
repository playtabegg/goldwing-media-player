"""The menu preview report — what it says when a disc is right, and when not."""

from __future__ import annotations

import shutil

from tests.fixtures.authoring import bdmv, hdmv
from wti_player.optical.inspect import inspect_bdmv

VIDEO = bdmv.StreamSpec(pid=0x1011, coding_type=bdmv.CODING_H264, format_rate=0x51)
AUDIO = bdmv.StreamSpec(pid=0x1100, coding_type=bdmv.CODING_AC3, language="eng", format_rate=0x31)
MENU = bdmv.StreamSpec(pid=hdmv.IG_PID, coding_type=bdmv.CODING_IG, language="eng")
START = 27_000_000


def _flatten(report) -> str:
    return report.as_text()


class TestAGoodDisc:
    def test_our_menu_disc_reports_healthy(self, menu_disc) -> None:
        report = inspect_bdmv(menu_disc)

        assert report.healthy, report.problems
        text = _flatten(report)
        assert "interactive graphics" in text
        assert "0x1400" in text
        assert "HDMV movie object" in text

    def test_a_disc_with_no_menu_is_still_healthy(self, feature_disc) -> None:
        # No menu is not a fault. Plenty of discs are a film and nothing else.
        report = inspect_bdmv(feature_disc)
        assert "interactive graphics" not in _flatten(report)


class TestWhatItCatches:
    def test_a_playlist_pointing_at_a_missing_clip(self, menu_disc, tmp_path) -> None:
        broken = tmp_path / "missing-clip"
        shutil.copytree(menu_disc, broken)
        (broken / "BDMV" / "CLIPINF" / "00001.clpi").unlink()

        report = inspect_bdmv(broken)
        assert not report.healthy
        assert any("00001" in problem for problem in report.problems)

    def test_a_clip_with_no_stream_file(self, menu_disc, tmp_path) -> None:
        broken = tmp_path / "missing-stream"
        shutil.copytree(menu_disc, broken)
        (broken / "BDMV" / "STREAM" / "00000.m2ts").unlink()

        report = inspect_bdmv(broken)
        assert any("m2ts" in problem for problem in report.problems)

    def test_a_top_menu_with_no_interactive_graphics_anywhere(self, tmp_path) -> None:
        # The failure Rialto's menu designer will hit first: an index that
        # promises a Top Menu over a playlist with no buttons in it.
        root = tmp_path / "menuless"
        bdmv.write_bdmv(
            root,
            {
                "BDMV/index.bdmv": bdmv.build_index(first_play=0, top_menu=0, titles=[0]),
                "BDMV/MovieObject.bdmv": bdmv.build_movie_objects(
                    [bdmv.MovieObjectSpec(commands=(hdmv.cmd_play_playlist(0),))]
                ),
                "BDMV/PLAYLIST/00000.mpls": bdmv.build_playlist(
                    items=[
                        bdmv.PlayItemSpec(
                            clip_id="00000",
                            in_time=START,
                            out_time=START + 45_000,
                            streams=(VIDEO, AUDIO),
                        )
                    ],
                    marks=[(0, START)],
                ),
                "BDMV/CLIPINF/00000.clpi": bdmv.build_clip_info(
                    streams=(VIDEO, AUDIO),
                    source_packet_count=32,
                    ts_recording_rate=6_000_000,
                    pcr_pid=0x1001,
                    pmt_pid=0x0100,
                    presentation_start=START,
                    presentation_end=START + 45_000,
                    cpi_block=b"\x00\x01\x00\x00",
                ),
            },
        )
        (root / "BDMV" / "STREAM").mkdir(parents=True)
        (root / "BDMV" / "STREAM" / "00000.m2ts").write_bytes(b"\x00" * 192)

        report = inspect_bdmv(root)
        assert not report.healthy
        assert any("no buttons" in problem for problem in report.problems)

    def test_an_index_pointing_past_the_last_movie_object(self, tmp_path) -> None:
        root = tmp_path / "dangling"
        bdmv.write_bdmv(
            root,
            {
                "BDMV/index.bdmv": bdmv.build_index(first_play=0, top_menu=0, titles=[7]),
                "BDMV/MovieObject.bdmv": bdmv.build_movie_objects(
                    [bdmv.MovieObjectSpec(commands=(hdmv.cmd_nop(),))]
                ),
            },
        )
        report = inspect_bdmv(root)
        assert any("movie object 7" in problem for problem in report.problems)

    def test_a_folder_that_is_not_a_disc_says_so_rather_than_throwing(self, tmp_path) -> None:
        report = inspect_bdmv(tmp_path)
        assert not report.healthy
        assert "index.bdmv" in _flatten(report)
