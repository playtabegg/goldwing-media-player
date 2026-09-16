"""The factory writes it; we read it. Nobody had ever run the two together.

`.wti_meta.json` is written by `rialto2/rialto_core/disc_meta.py` and read by
`wti_player/optical/meta.py`. Both sides had tests. Neither side had ever
seen the other's output, and a cross-repo audit on 2026-08-23 found three
real breaks that both green suites missed — including a game disc the Player
could not recognise as a game disc, because its fixture was an invention that
looked nothing like a disc the factory makes.

So this imports the real writer and feeds the real reader. It skips when the
factory is not beside us, which is the price of the test being real; when it
does run, it is the only thing in either repository that checks the contract
rather than checking a copy of it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from wti_player.optical import identify, meta

FACTORY = Path(__file__).resolve().parents[2].parent / "rialto2"


@pytest.fixture(scope="module")
def writer():
    """The factory's own writer, imported read-only."""
    if not (FACTORY / "rialto_core" / "disc_meta.py").is_file():
        pytest.skip(f"the factory is not at {FACTORY}")
    # Appended, never prepended: the factory has a `tests` package of its own
    # and putting it first shadows ours.
    if str(FACTORY) not in sys.path:
        sys.path.append(str(FACTORY))
    try:
        from rialto_core import disc_meta
    except ImportError as error:  # pragma: no cover - environment-dependent
        pytest.skip(f"the factory's writer would not import: {error}")
    return disc_meta


class TestTheAgreementItself:
    def test_both_sides_look_in_the_same_places(self, writer):
        """Asserted against the writer, not against a copy of its list.

        The Player's own test pinned these as a literal, so a change on the
        factory side would have stayed green on both until a real disc turned
        up with no name.
        """
        assert meta.SEARCH_PATHS == writer.META_SEARCH_PATHS

    def test_both_sides_agree_on_the_filename(self, writer):
        assert meta.META_NAME == writer.DISC_META_NAME

    def test_both_sides_agree_on_the_version(self, writer):
        assert meta.KNOWN_SCHEMA == writer.DISC_META_VERSION

    def test_the_reader_knows_who_made_a_disc(self, writer):
        document = {"schema": 1, "made_by": writer.MADE_BY}
        assert meta._from_document(document, Path("x")).ours

    def test_each_kind_goes_where_the_reader_looks(self, writer):
        for kind in ("game", "movie"):
            relative = writer.meta_relative_path(kind)
            assert relative in meta.SEARCH_PATHS, kind
        assert writer.meta_relative_path("music") is None


class TestADocumentTheFactoryReallyWrote:
    """Round-trip through the writer's own serialisation, not a hand-made one."""

    def a_document(self, writer, tmp_path, kind, payload):
        folder = tmp_path / kind
        relative = writer.meta_relative_path(kind)
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8", newline="\n")
        return folder

    def test_a_movie_document_reads(self, writer, tmp_path):
        payload = {
            "schema": 1,
            "kind": "movie",
            "title": "Sally, Irene and Mary",
            "author": "Tiffany Productions",
            "publisher_text": "© 1938 Tiffany Productions.",
            "id": "sally-irene-and-mary",
            "version": "1.0.0",
            "disc_label": "SALLY_IRENE",
            "made_by": writer.MADE_BY,
            "movie": {
                "runtime_minutes": 58,
                "aspect_ratio": "4:3",
                "chapters": [{"title": "The audition", "start": "6:40"}],
                "audio_tracks": [{"language": "en", "label": "Stereo"}],
                "subtitle_tracks": [],
                "extras": [],
            },
        }
        folder = self.a_document(writer, tmp_path, "movie", payload)
        read = meta.read(folder)
        assert read is not None
        assert read.title == "Sally, Irene and Mary"
        assert read.movie is not None
        assert read.chapter_names() == ("The audition",)

    def test_a_game_document_reads_from_the_menu_folder(self, writer, tmp_path):
        payload = {
            "schema": 1,
            "kind": "game",
            "title": "Shooty Shooty",
            "author": "A Studio",
            "id": "shooty-shooty",
            "version": "1.2.0",
            "made_by": writer.MADE_BY,
            "game": {
                "launch_options": ["Play"],
                "has_mod_tool": False,
                "has_bonus": True,
                "mac_build": True,
                "linux_build": False,
                "online_updates": False,
                "menu_language": "en",
            },
        }
        folder = self.a_document(writer, tmp_path, "game", payload)
        read = meta.read(folder)
        assert read is not None
        assert read.game is not None
        assert read.game.launch_options == ("Play",)
        assert read.game.mac_build
        assert not read.game.linux_build


class TestAGameDiscTheFactoryWouldRecognise:
    """The fixture that was an invention, and the detection written against it."""

    def test_it_reads_as_a_game_disc(self, game_disc):
        assert identify.identify(game_disc).kind is identify.DiscKind.GAME_DISC

    def test_the_launcher_is_in_the_menu_folder(self, game_disc):
        """Where Rialto puts it. If the fixture drifts back, this fails."""
        assert (game_disc / "menu" / "menu.exe").is_file()
        assert not (game_disc / "menu.exe").exists()

    def test_the_autorun_opens_the_installer_not_the_launcher(self, game_disc):
        text = (game_disc / "autorun.inf").read_text(encoding="cp1252")
        assert "Open=setup.exe" in text

    def test_the_disc_root_is_the_fileset_the_factory_writes(self, game_disc):
        present = {path.name for path in game_disc.iterdir()}
        for required in ("setup.exe", "autorun.inf", "README.txt", "menu"):
            assert required in present, required

    def test_the_label_survives_its_own_encoding(self, game_disc):
        """The autorun is cp1252. Read as latin-1, a dash becomes a control code."""
        profile = identify.identify(game_disc)
        assert profile.label == "Shooty Shooty — Director’s Cut"  # noqa: RUF001

    def test_the_document_on_it_is_found(self, game_disc):
        profile = identify.identify(game_disc)
        assert profile.meta is not None
        assert profile.display_name == "Shooty Shooty"
        assert profile.meta.game is not None


class TestChapterNamesLandOnTheRightMarks:
    """The factory presses a mark at zero whether or not a chapter is there.

    So the two lists are different lengths on most films, and pairing them by
    position shifts every name onto the chapter before it. Matching is by
    time, and these are the cases that proves it.
    """

    def names_for(self, marks, chapters):
        from wti_player.ui.main_window import _name_for

        return [_name_for(mark, chapters) for mark in marks]

    def chapters(self, *pairs):
        return tuple(meta.Chapter(title, start) for title, start in pairs)

    def test_an_implicit_mark_at_zero_does_not_steal_the_first_name(self):
        chapters = self.chapters(("The audition", "6:40"), ("Opening night", "1:14:12"))
        marks = [0, 400_000, 4_452_000]
        assert self.names_for(marks, chapters) == ["", "The audition", "Opening night"]

    def test_a_named_chapter_at_zero_keeps_its_name(self):
        chapters = self.chapters(("Opening", "0:00"), ("The audition", "6:40"))
        assert self.names_for([0, 400_000], chapters) == ["Opening", "The audition"]

    def test_a_mark_snapped_to_a_keyframe_still_matches(self):
        """An encoder moves a mark by a second or two. That is not a new chapter."""
        chapters = self.chapters(("The audition", "6:40"))
        assert self.names_for([401_800], chapters) == ["The audition"]

    def test_a_mark_nowhere_near_a_chapter_gets_no_name(self):
        chapters = self.chapters(("The audition", "6:40"))
        assert self.names_for([2_000_000], chapters) == [""]

    def test_more_marks_than_names_does_not_run_off_the_end(self):
        chapters = self.chapters(("One", "0:00"))
        assert self.names_for([0, 60_000, 120_000], chapters) == ["One", "", ""]

    def test_more_names_than_marks_is_fine(self):
        """The factory drops marks past the end of the film; the document keeps them."""
        chapters = self.chapters(("One", "0:00"), ("Two", "1:00"), ("Three", "99:00"))
        assert self.names_for([0, 60_000], chapters) == ["One", "Two"]

    def test_no_chapters_at_all_names_nothing(self):
        assert self.names_for([0, 1000], ()) == ["", ""]


class TestTrackLabels:
    """A language and a label are two different things and both are on the disc."""

    def test_both_are_kept(self):
        read = meta._labels([{"language": "en", "label": "Stereo"}])
        assert read == ("Stereo (EN)",)

    def test_a_label_with_no_language_stands_alone(self):
        assert meta._labels([{"label": "Commentary"}]) == ("Commentary",)

    def test_a_language_with_no_label_stands_alone(self):
        assert meta._labels([{"language": "ja"}]) == ("JA",)

    def test_two_tracks_labelled_the_same_are_still_told_apart(self):
        """The bug this replaces: both of these read as "Stereo"."""
        read = meta._labels(
            [{"language": "en", "label": "Stereo"}, {"language": "ja", "label": "Stereo"}]
        )
        assert len(set(read)) == 2, read


class TestTheFactorysDocumentValidatesAgainstItsSchema:
    """The other half of the contract: the factory's output against the
    factory's own authority, checked from the reader's side.

    The names are pinned by the factory's exact-set-equality test. The
    constraints (patterns, minimums, `additionalProperties: false`) were
    pinned by nothing in either repository until 29 Aug 2026. This builds
    real documents through the writer, validates each against
    `disc_meta.schema.json`, and then reads it, so a document that is
    valid but unreadable, or readable but invalid, fails here.
    """

    @pytest.fixture(scope="class")
    def validate(self, writer):
        fastjsonschema = pytest.importorskip("fastjsonschema")
        schema = json.loads(
            (FACTORY / "rialto_core" / "disc_meta.schema.json").read_text(encoding="utf-8")
        )
        return fastjsonschema.compile(schema)

    @pytest.fixture(scope="class")
    def factory_spec(self, writer):
        from rialto_core.project_spec import MovieProject, TrackInfo
        from rialto_core.types import AssetSpec, BuildSpec, MenuButton, MenuSpec

        def make(kind: str, project, **over):
            payload = {
                "game_id": "sally-irene-and-mary",
                "title": "Sally, Irene and Mary",
                "developer": "Tiffany Productions",
                "publisher_text": "© 1938 Tiffany Productions.",
                "version": "1.0.0",
                "product_kind": kind,
                "project": project,
                "menu_spec": MenuSpec(buttons=[MenuButton(label="PLAY", action="play")]),
                "asset_spec": AssetSpec(
                    game_build_r2_path="wti-uploads/s/film.zip",
                    box_front_r2_path="wti-uploads/s/f.png",
                    box_back_r2_path="wti-uploads/s/b.png",
                    box_spine_r2_path="wti-uploads/s/s.png",
                    disc_face_r2_path="wti-uploads/s/d.png",
                ),
            }
            payload.update(over)
            return BuildSpec.model_validate(payload)

        def movie(**over):
            fields = {
                "kind": "movie",
                "version": 1,
                "runtime_minutes": 58,
                "aspect_ratio": "1.37:1",
                "audio_tracks": [TrackInfo(language="en", label="Stereo")],
            }
            fields.update(over)
            return MovieProject.model_validate(fields)

        return make, movie

    def test_a_1_37_film_is_valid_and_reads_as_1_37(self, writer, validate, factory_spec, tmp_path):
        make, movie = factory_spec
        spec = make("movie", movie())
        written = writer.write_disc_meta(tmp_path, spec, disc_label="SALLY_IRENE")
        assert written is not None
        document = json.loads(written.read_text(encoding="utf-8"))
        assert validate(document) == document
        read = meta.read(tmp_path)
        assert read is not None and read.movie is not None
        # A ratio, shown verbatim. Never the word "other".
        assert read.movie.aspect_ratio == "1.37:1"

    def test_a_game_document_is_valid_and_reads(self, writer, validate, factory_spec, tmp_path):
        from rialto_core.project_spec import GameProject

        make, _ = factory_spec
        spec = make("game", GameProject(kind="game", version=1), game_id="makis-adventure")
        written = writer.write_disc_meta(tmp_path, spec, disc_label="MAKIS")
        assert written is not None
        document = json.loads(written.read_text(encoding="utf-8"))
        assert validate(document) == document
        read = meta.read(tmp_path)
        assert read is not None and read.game is not None

    def test_the_schema_refuses_the_word_other(self, writer, validate, factory_spec):
        fastjsonschema = pytest.importorskip("fastjsonschema")
        make, movie = factory_spec
        document = writer.build_disc_meta(make("movie", movie()))
        document["movie"]["aspect_ratio"] = "other"
        with pytest.raises(fastjsonschema.JsonSchemaException):
            validate(document)


class TestTheArtTheFactoryWrites:
    """C12: the factory writes cover.jpg and disc.jpg beside the document and
    names them in it; the reader finds them through the field, not a guess."""

    def test_a_movie_disc_with_art_reads_with_its_art(self, writer, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image
        from rialto_core import disc_art
        from rialto_core.project_spec import MovieProject, TrackInfo
        from rialto_core.types import AssetSpec, BuildSpec, MenuButton, MenuSpec

        art_dir = tmp_path / "art"
        art_dir.mkdir()
        Image.new("RGB", (1800, 2700), (120, 30, 40)).save(art_dir / "box_front.png")
        Image.new("RGBA", (1600, 1600), (20, 20, 20, 255)).save(art_dir / "disc_face.png")
        disc = tmp_path / "disc"
        disc.mkdir()
        spec = BuildSpec.model_validate(
            {
                "game_id": "sally-irene-and-mary",
                "title": "Sally, Irene and Mary",
                "developer": "Tiffany Productions",
                "version": "1.0.0",
                "product_kind": "movie",
                "project": MovieProject.model_validate(
                    {"kind": "movie", "version": 1, "runtime_minutes": 58, "aspect_ratio": "1.37:1",
                     "audio_tracks": [TrackInfo(language="en", label="Stereo")]}
                ),
                "menu_spec": MenuSpec(buttons=[MenuButton(label="PLAY", action="play")]),
                "asset_spec": AssetSpec(
                    game_build_r2_path="wti-uploads/s/film.zip",
                    box_front_r2_path="wti-uploads/s/f.png",
                    box_back_r2_path="wti-uploads/s/b.png",
                    box_spine_r2_path="wti-uploads/s/s.png",
                    disc_face_r2_path="wti-uploads/s/d.png",
                ),
            }
        )
        art = disc_art.write_disc_art(disc, *disc_art.art_sources(art_dir))
        writer.write_disc_meta(disc, spec, disc_label="SALLY", art=art)

        read = meta.read(disc)
        assert read is not None
        assert read.art.cover == disc / "cover.jpg"
        assert read.art.face == disc / "disc.jpg"
        # Downsampled on the way onto the disc, not riding at print size.
        with Image.open(read.art.cover) as cover:
            assert max(cover.size) <= 1200
        assert read.art.cover.stat().st_size < 8 * 1024 * 1024
