"""The BDMV readers, against structures we write ourselves and against a disc.

The round-trip tests are the load-bearing ones: they pin the byte layouts in
place from both directions, so a field that moves breaks a test rather than a
customer's disc.
"""

from __future__ import annotations

import pytest

from tests.fixtures.authoring import bdmv, hdmv
from wti_player.formats import clpi, index_bdmv, mpls

VIDEO = bdmv.StreamSpec(pid=0x1011, coding_type=bdmv.CODING_H264, format_rate=0x51)
AUDIO = bdmv.StreamSpec(pid=0x1100, coding_type=bdmv.CODING_AC3, language="eng", format_rate=0x31)
MENU = bdmv.StreamSpec(pid=hdmv.IG_PID, coding_type=bdmv.CODING_IG, language="eng")

START = 27_000_000
FEATURE_END = START + 90 * 60 * 45_000


class TestPlaylist:
    def test_round_trips_times_streams_and_chapters(self) -> None:
        raw = bdmv.build_playlist(
            items=[
                bdmv.PlayItemSpec(
                    clip_id="00001",
                    in_time=START,
                    out_time=FEATURE_END,
                    streams=(VIDEO, AUDIO),
                )
            ],
            marks=[(0, START), (0, START + 10 * 45_000), (0, START + 20 * 45_000)],
        )
        playlist = mpls.parse(raw, name="00001")

        assert playlist.version == "0200"
        assert len(playlist.play_items) == 1
        item = playlist.play_items[0]
        assert item.clip_id == "00001"
        assert item.codec_id == "M2TS"
        assert item.duration_ms == 90 * 60 * 1000
        assert [(s.kind, s.pid) for s in item.streams] == [
            ("video", 0x1011),
            ("audio", 0x1100),
        ]
        assert item.streams[1].language == "eng"
        assert playlist.chapters_ms == (0, 10_000, 20_000)

    def test_an_interactive_graphics_stream_makes_it_a_menu(self) -> None:
        raw = bdmv.build_playlist(
            items=[
                bdmv.PlayItemSpec(
                    clip_id="00000",
                    in_time=START,
                    out_time=START + 6 * 45_000,
                    streams=(VIDEO, MENU),
                    still_mode=0x02,
                )
            ],
            marks=[(0, START)],
        )
        playlist = mpls.parse(raw)

        assert playlist.has_interactive_graphics
        assert playlist.looks_like_menu
        assert playlist.play_items[0].is_still

    def test_a_short_playlist_is_not_assumed_to_be_a_menu(self) -> None:
        # A trailer is short. Hiding it from the title list because of that
        # would be worse than showing one menu among the titles.
        raw = bdmv.build_playlist(
            items=[
                bdmv.PlayItemSpec(
                    clip_id="00002",
                    in_time=START,
                    out_time=START + 30 * 45_000,
                    streams=(VIDEO, AUDIO),
                )
            ],
            marks=[(0, START)],
        )
        assert not mpls.parse(raw).looks_like_menu

    def test_main_feature_is_the_longest_non_menu(self) -> None:
        def playlist(name: str, seconds: int, menu: bool = False) -> mpls.Playlist:
            raw = bdmv.build_playlist(
                items=[
                    bdmv.PlayItemSpec(
                        clip_id="00000",
                        in_time=START,
                        out_time=START + seconds * 45_000,
                        streams=(VIDEO, MENU) if menu else (VIDEO, AUDIO),
                        still_mode=0x02 if menu else 0,
                    )
                ],
                marks=[(0, START)],
            )
            return mpls.parse(raw, name=name)

        playlists = [
            playlist("00000", 6, menu=True),
            playlist("00001", 5400),
            playlist("00002", 120),
        ]
        assert mpls.main_feature(playlists) is playlists[1]

    def test_a_truncated_playlist_is_an_error_not_a_crash(self) -> None:
        raw = bdmv.build_playlist(
            items=[
                bdmv.PlayItemSpec(
                    clip_id="00001", in_time=START, out_time=FEATURE_END, streams=(VIDEO,)
                )
            ],
            marks=[(0, START)],
        )
        with pytest.raises(mpls.MplsError):
            mpls.parse(raw[: len(raw) // 2])

    def test_something_that_is_not_a_playlist_says_so(self) -> None:
        with pytest.raises(mpls.MplsError, match="not a playlist"):
            mpls.parse(b"NOPE0200" + b"\x00" * 200)


class TestClipInfo:
    def test_round_trips_streams_and_the_presentation_window(self) -> None:
        raw = bdmv.build_clip_info(
            streams=(VIDEO, AUDIO, MENU),
            source_packet_count=19008,
            ts_recording_rate=6_000_000,
            pcr_pid=0x1001,
            pmt_pid=0x0100,
            presentation_start=START,
            presentation_end=START + 12 * 45_000,
            cpi_block=b"\x00\x01\x00\x00",
        )
        info = clpi.parse(raw, name="00000")

        assert info.source_packet_count == 19008
        assert info.ts_recording_rate == 6_000_000
        assert info.pcr_pid == 0x1001
        assert info.duration_ms == 12_000
        assert [stream.kind for stream in info.streams] == ["video", "audio", "interactive"]
        assert info.has_interactive_graphics

    def test_a_clip_without_a_menu_says_so(self) -> None:
        raw = bdmv.build_clip_info(
            streams=(VIDEO, AUDIO),
            source_packet_count=100,
            ts_recording_rate=6_000_000,
            pcr_pid=0x1001,
            pmt_pid=0x0100,
            presentation_start=START,
            presentation_end=START + 45_000,
        )
        assert not clpi.parse(raw).has_interactive_graphics


class TestIndex:
    def test_round_trips_first_play_top_menu_and_titles(self) -> None:
        raw = bdmv.build_index(first_play=0, top_menu=0, titles=[1, 0])
        index = index_bdmv.parse_index(raw)

        assert index.has_top_menu
        assert not index.uses_bdj
        assert index.title_count == 2
        assert index.first_play.id_ref == 0
        assert index.titles[0].id_ref == 1

    def test_movie_objects_round_trip_their_commands(self) -> None:
        raw = bdmv.build_movie_objects(
            [
                bdmv.MovieObjectSpec(
                    commands=(hdmv.cmd_play_playlist(0), hdmv.cmd_jump_object(0))
                ),
                bdmv.MovieObjectSpec(commands=(hdmv.cmd_jump_title(1),)),
            ]
        )
        objects = index_bdmv.parse_movie_objects(raw)

        assert [obj.command_count for obj in objects] == [2, 1]
        assert objects[0].commands[0] == hdmv.cmd_play_playlist(0)
        assert objects[0].resume_intention

    def test_a_bd_j_disc_is_recognised_from_the_index(self, tmp_path) -> None:
        # Hand-build a BD-J slot: object_type 2, a five-character BDJO name.
        raw = bytearray(bdmv.build_index(first_play=0, top_menu=0, titles=[0]))
        indexes_start = int.from_bytes(raw[8:12], "big")
        first_play = indexes_start + 4
        raw[first_play : first_play + 4] = (2 << 30).to_bytes(4, "big")
        raw[first_play + 4 : first_play + 12] = b"\x40\x00" + b"00000" + b"\x00"

        index = index_bdmv.parse_index(bytes(raw))
        assert index.uses_bdj
        assert index.first_play.bdjo_name == "00000"


class TestAgainstARealDisc:
    """The readers are only right if they agree with a disc a tool made."""

    pytestmark = pytest.mark.media

    def test_reads_the_feature_disc(self, feature_disc) -> None:
        bdmv_dir = feature_disc / "BDMV"
        index = index_bdmv.read_index(bdmv_dir)
        playlists = mpls.read_all(bdmv_dir / "PLAYLIST")
        clips = clpi.read_all(bdmv_dir / "CLIPINF")

        assert index.title_count >= 1
        assert not index.uses_bdj
        assert playlists
        assert playlists[0].chapters_ms == (0, 4000, 8000)
        assert clips["00000"].source_packet_count > 0
        assert [stream.kind for stream in clips["00000"].streams] == ["video", "audio"]

    def test_reads_our_menu_disc(self, menu_disc) -> None:
        bdmv_dir = menu_disc / "BDMV"
        playlists = {playlist.name: playlist for playlist in mpls.read_all(bdmv_dir / "PLAYLIST")}
        clips = clpi.read_all(bdmv_dir / "CLIPINF")

        assert playlists["00000"].has_interactive_graphics
        assert not playlists["00001"].has_interactive_graphics
        assert clips["00000"].has_interactive_graphics
        assert mpls.main_feature(list(playlists.values())).name == "00001"
