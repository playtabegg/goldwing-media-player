"""What a disc says about itself, and what happens when it says nonsense.

The document comes off a disc somebody else pressed. Half of these tests are
about the half that will not parse.
"""

from __future__ import annotations

import json

import pytest

from wti_player.optical import identify, meta


def write(root, document, *, relative=".wti_meta.json"):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        document if isinstance(document, str) else json.dumps(document), encoding="utf-8"
    )
    return path


def movie_document(**overrides):
    document = {
        "schema": 1,
        "kind": "movie",
        "title": "Sally, Irene and Mary",
        "author": "Tiffany Productions",
        "publisher_text": "© 1938 Tiffany Productions.",
        "id": "sally-irene-and-mary",
        "version": "1.0.0",
        "disc_label": "SALLY_IRENE_MARY",
        "made_by": "We the Indies",
        "movie": {
            "runtime_minutes": 58,
            "aspect_ratio": "1.37:1",
            "chapters": [
                {"title": "The audition", "start": "6:40"},
                {"title": "Opening night", "start": "1:14:12"},
            ],
            "audio_tracks": [{"language": "en", "label": "English 2.0"}],
            "subtitle_tracks": [{"language": "en", "label": ""}],
            "extras": [{"title": "Trailer", "description": ""}],
        },
    }
    document.update(overrides)
    return document


class TestReading:
    def test_a_movie_document_reads(self, tmp_path):
        write(tmp_path, movie_document())
        document = meta.read(tmp_path)

        assert document is not None
        assert document.title == "Sally, Irene and Mary"
        assert document.author == "Tiffany Productions"
        assert document.ours
        assert document.movie is not None
        assert document.movie.runtime_minutes == 58
        assert document.chapter_names() == ("The audition", "Opening night")
        assert document.year == "1938"

    def test_the_year_is_the_first_one_written_even_in_brackets(self, tmp_path):
        # The factory writes "Nosferatu (1922) is in the public domain. ... Murnau died 1931": the film's year, not
        # the director's death, which the header showed while "(1922)" did not read as a year.
        text = "Nosferatu (1922) is in the public domain. Published 1922. Murnau died 1931."
        write(tmp_path, movie_document(publisher_text=text))
        assert meta.read(tmp_path).year == "1922"

    def test_a_game_document_lives_in_the_menu_folder(self, tmp_path):
        write(
            tmp_path,
            {
                "schema": 1,
                "kind": "game",
                "title": "Shooty Shooty",
                "author": "A Studio",
                "id": "shooty-shooty",
                "version": "1.2.0",
                "made_by": "We the Indies",
                "game": {
                    "launch_options": ["Play", "Play windowed"],
                    "has_mod_tool": True,
                    "mac_build": False,
                },
            },
            relative="menu/.wti_meta.json",
        )
        document = meta.read(tmp_path)

        assert document is not None
        assert document.kind == "game"
        assert document.game is not None
        assert document.game.launch_options == ("Play", "Play windowed")
        assert document.game.has_mod_tool
        assert not document.game.mac_build

    def test_the_search_order_matches_the_factory(self):
        # The writer's list, verbatim. Two readers looking in different
        # places is a disc that mysteriously has no name.
        assert meta.SEARCH_PATHS == (".wti_meta.json", "menu/.wti_meta.json")

    def test_the_root_wins_over_the_menu_folder(self, tmp_path):
        write(tmp_path, movie_document(title="At the root"))
        write(tmp_path, movie_document(title="In the menu"), relative="menu/.wti_meta.json")
        assert meta.read(tmp_path).title == "At the root"

    def test_a_disc_with_no_document_reads_as_none(self, tmp_path):
        assert meta.read(tmp_path) is None


class TestChapterTimes:
    @pytest.mark.parametrize(
        ("written", "expected"),
        [
            ("0:00", 0),
            ("6:40", 400_000),
            ("1:14:12", 4_452_000),
            ("00:30", 30_000),
        ],
    )
    def test_a_timecode_becomes_milliseconds(self, written, expected):
        assert meta.Chapter("x", written).start_ms == expected

    @pytest.mark.parametrize("written", ["", "later", "1:2:3:4", "??:??"])
    def test_a_timecode_that_will_not_parse_is_the_start(self, written):
        assert meta.Chapter("x", written).start_ms == 0


class TestNonsense:
    """Everything here must read as "no document", never as an exception."""

    def test_not_json(self, tmp_path):
        write(tmp_path, "{this is not json")
        assert meta.read(tmp_path) is None

    def test_a_list_rather_than_an_object(self, tmp_path):
        write(tmp_path, ["nope"])
        assert meta.read(tmp_path) is None

    def test_empty(self, tmp_path):
        write(tmp_path, "")
        assert meta.read(tmp_path) is None

    def test_a_document_larger_than_a_document(self, tmp_path):
        write(tmp_path, {"schema": 1, "pad": "x" * (meta.MAX_DOCUMENT_BYTES + 10)})
        assert meta.read(tmp_path) is None

    def test_fields_of_the_wrong_type(self, tmp_path):
        write(
            tmp_path,
            {
                "schema": "one",
                "kind": 7,
                "title": ["a", "list"],
                "author": None,
                "movie": "not an object",
                "made_by": {"nested": True},
            },
        )
        document = meta.read(tmp_path)
        assert document is not None
        assert document.title == ""
        assert document.kind == ""
        assert document.movie is None
        assert not document.ours

    def test_chapters_that_are_not_chapters(self, tmp_path):
        document = movie_document()
        document["movie"]["chapters"] = ["nope", {"start": "0:00"}, {"title": "Real", "start": "1:00"}]
        write(tmp_path, document)
        read = meta.read(tmp_path)
        assert read is not None
        assert read.chapter_names() == ("Real",)

    def test_a_later_schema_is_reported_rather_than_guessed_at(self, tmp_path):
        write(tmp_path, movie_document(schema=2))
        document = meta.read(tmp_path)
        assert document is not None
        assert document.newer_than_us
        # Version 1's fields keep their meaning, so they are still read.
        assert document.title == "Sally, Irene and Mary"


class TestArt:
    def test_the_conventional_names_are_found(self, tmp_path):
        write(tmp_path, movie_document())
        (tmp_path / "cover.jpg").write_bytes(b"\xff\xd8\xff")
        (tmp_path / "disc.jpg").write_bytes(b"\xff\xd8\xff")

        document = meta.read(tmp_path)
        assert document.art.cover == tmp_path / "cover.jpg"
        assert document.art.face == tmp_path / "disc.jpg"
        assert document.art.any

    def test_the_document_may_name_its_own(self, tmp_path):
        write(tmp_path, movie_document(art={"cover": "poster.png", "disc": "label.png"}))
        (tmp_path / "poster.png").write_bytes(b"\x89PNG")
        (tmp_path / "label.png").write_bytes(b"\x89PNG")
        (tmp_path / "cover.jpg").write_bytes(b"\xff\xd8\xff")

        document = meta.read(tmp_path)
        assert document.art.cover == tmp_path / "poster.png"
        assert document.art.face == tmp_path / "label.png"

    def test_a_disc_with_no_art_is_not_a_problem(self, tmp_path):
        write(tmp_path, movie_document())
        document = meta.read(tmp_path)
        assert not document.art.any

    @pytest.mark.parametrize(
        "name",
        [
            "../secret.jpg",
            "..\\secret.jpg",
            "sub/cover.jpg",
            "C:\\Windows\\System32\\x.jpg",
            "C:secret.jpg",
            "\\\\server\\share\\x.jpg",
            "\\\\?\\C:\\x.jpg",
            "cover.jpg:evil",
            ".hidden.jpg",
            "",
        ],
    )
    def test_art_never_escapes_the_folder_it_was_named_in(self, tmp_path, name):
        """The name comes off a disc. It points at a sibling or at nothing.

        The file each name aims at is CREATED first. Without that, this test
        passes with the guard deleted: an empty folder returns None for every
        path, and it is the missing file doing the work rather than the code
        under test. A mutation audit proved exactly that on 2026-08-23.
        """
        folder = tmp_path / "disc"
        folder.mkdir()
        jpeg = b"\xff\xd8\xff" + b"\x00" * 64
        for target in (
            tmp_path / "secret.jpg",
            folder / "sub" / "cover.jpg",
            folder / ".hidden.jpg",
            folder / "cover.jpg",
        ):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(jpeg)

        assert meta._art_file(folder, name) is None

    def test_a_plain_sibling_is_still_found(self, tmp_path):
        """The guard refuses the escapes and nothing else."""
        (tmp_path / "cover.jpg").write_bytes(b"\xff\xd8\xff")
        assert meta._art_file(tmp_path, "cover.jpg") == tmp_path / "cover.jpg"

    def test_art_too_large_to_be_art_is_refused(self, tmp_path):
        big = tmp_path / "cover.jpg"
        big.write_bytes(b"\x00" * (meta.MAX_ART_BYTES + 1))
        assert meta.find_art(tmp_path).cover is None


class TestProfileIntegration:
    def test_identify_attaches_the_document(self, tmp_path):
        disc = tmp_path / "DISC"
        (disc / "VIDEO_TS").mkdir(parents=True)
        write(disc, movie_document())

        profile = identify.identify(disc)
        assert profile.meta is not None
        assert profile.display_name == "Sally, Irene and Mary"

    def test_a_bdmv_folder_opened_directly_still_finds_it(self, tmp_path):
        disc = tmp_path / "DISC"
        (disc / "BDMV" / "PLAYLIST").mkdir(parents=True)
        write(disc, movie_document())

        # Opened at the BDMV, not at the disc root — which is what menu
        # preview mode does every time.
        profile = identify.identify(disc / "BDMV")
        assert profile.meta is not None
        assert profile.display_name == "Sally, Irene and Mary"

    def test_a_disc_that_is_not_ours_still_has_a_name(self, tmp_path):
        disc = tmp_path / "SOME_MOVIE"
        (disc / "VIDEO_TS").mkdir(parents=True)

        profile = identify.identify(disc, label="SOME_MOVIE")
        assert profile.meta is None
        assert profile.display_name == "SOME_MOVIE"
        assert not profile.art.any

    def test_the_display_name_falls_back_to_the_folder(self, tmp_path):
        disc = tmp_path / "unnamed"
        (disc / "VIDEO_TS").mkdir(parents=True)
        assert identify.identify(disc).display_name == "unnamed"
