"""The promises the Player makes in words.

These are not style tests. Each one guards a sentence we have committed to
publicly, so that a refactor cannot quietly take it out of the product.
"""

from __future__ import annotations

import ast
from pathlib import Path

from wti_player import strings
from wti_player.version import VERSION, display_version, window_title


class TestTheLicensingLine:
    def test_the_about_box_names_both_protections_and_our_position(self) -> None:
        text = strings.about_text()
        assert "will not play" in text
        assert "AACS" in text
        assert "CSS" in text
        assert "rather pay for the key than break the lock" in text

    def test_the_about_box_says_why_we_make_discs_at_all(self) -> None:
        assert "outlive the company that sold it to you" in strings.about_text()

    def test_the_about_box_credits_the_engine_and_its_licence(self) -> None:
        text = strings.about_text()
        assert "libVLC" in text
        # The GPL, not the LGPL. The vendored libavcodec was built with
        # --enable-gpl and says so in its own strings, and PyQt6 is GPLv3,
        # so the program as a whole is GPLv3 — and this box used to tell
        # people the opposite.
        assert "General Public License v3" in text
        assert "Lesser" not in text

    def test_the_about_box_tells_people_they_can_have_the_source(self) -> None:
        """Which the GPL requires, and which nobody can act on if unsaid."""
        assert "entitled to its source" in strings.about_text()

    def test_the_about_box_says_there_is_no_telemetry(self) -> None:
        assert "no telemetry" in strings.about_text()

    def test_nothing_promises_a_protected_disc_will_play(self) -> None:
        # The welcome copy is the first thing anyone reads. It must not
        # promise the DVDs on their shelf while we do not ship a decryptor.
        assert "unprotected" in strings.WELCOME_BODY


class TestEarlyBuild:
    """Chandler's word, 1 Sep 2026: this is 1.0.0, not an early build.

    The label is off in the title bar, in the version line, and on the
    empty screen. The version number is not: it is what a bug report
    quotes, so it stays visible everywhere it was.
    """

    def test_the_window_does_not_say_early_build(self) -> None:
        assert "early build" not in window_title()
        assert "early build" not in window_title("A Disc")
        assert window_title() == "Goldwing Media Player"
        assert window_title("A Disc") == "A Disc · Goldwing Media Player"

    def test_the_version_is_the_number_and_nothing_else(self) -> None:
        assert "early build" not in display_version()
        assert display_version() == VERSION

    def test_the_about_box_still_shows_the_version(self) -> None:
        text = strings.about_text()
        assert "early build" not in text.lower()
        assert f"Version {VERSION}" in text


class TestErrorText:
    def test_every_message_is_a_sentence_not_a_code(self) -> None:
        messages = [
            strings.CANNOT_READ_DISC,
            strings.CANNOT_READ_BLU_RAY,
            strings.IMAGE_NOTE_GAME,
            strings.IMAGE_NOTE_DATA,
            strings.GAME_OURS,
            strings.GAME_OURS_IMAGE,
            strings.GAME_OTHER,
            strings.GAME_OTHER_IMAGE,
            strings.NEEDS_JAVA,
            strings.DAMAGED_INDEX,
            strings.NOTHING_TO_PLAY,
            strings.UNEXPECTED_PROBLEM,
        ]
        for message in messages:
            assert message[0].isupper(), message
            assert message.rstrip().endswith("."), message
            assert "!" not in message, message
            assert "error" not in message.lower(), message
            assert "—" not in message, message

    def test_a_failed_read_does_not_call_every_disc_a_blu_ray(self) -> None:
        assert "Blu-ray" not in strings.CANNOT_READ_DISC
        assert "Blu-ray" in strings.CANNOT_READ_BLU_RAY

    def test_game_copy_does_not_say_video_discs(self) -> None:
        for message in (
            strings.GAME_OURS,
            strings.GAME_OURS_IMAGE,
            strings.GAME_OTHER,
            strings.GAME_OTHER_IMAGE,
            strings.IMAGE_NOTE_GAME,
        ):
            assert "video disc" not in message.lower()
            assert "we the indies" in message.lower() or "someone else" in message.lower()


class TestHouseStyle:
    """No em-dash, and never "pressed" or "burned", anywhere in the copy.

    The old guard walked a hand-written list of twelve messages, so four
    em-dashes sat in the file for weeks: two inside PROTECTED_BLU_RAY and
    PROTECTED_DVD, one in PREVIEW_NO_MENU, one in about_text(). None of the
    four was on the list, so nothing failed. These two tests read the whole
    module instead, once through its source and once through what it
    actually renders, so a new string cannot be added outside the net.
    """

    #: The dash itself, and the two words that are not ours to say.
    EM_DASH = "—"
    BANNED_WORDS = ("pressed", "burned")

    def _literals(self) -> list[tuple[int, str]]:
        """Every string literal in strings.py that is not a docstring."""
        source = Path(strings.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        docstrings: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                first = node.body[0] if node.body else None
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    if isinstance(first.value.value, str):
                        docstrings.add(id(first.value))
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstrings:
                    continue
                found.append((node.lineno, node.value))
        assert len(found) > 60, "the scan found almost nothing, so it is not scanning"
        return found

    def test_no_em_dash_in_any_string_in_the_file(self) -> None:
        for line, text in self._literals():
            assert self.EM_DASH not in text, f"strings.py:{line}: {text[:70]}"

    def test_nothing_says_pressed_or_burned(self) -> None:
        """Made by hand, never pressed, never burned. The one house word."""
        for line, text in self._literals():
            lowered = text.lower()
            for word in self.BANNED_WORDS:
                assert word not in lowered, f"strings.py:{line}: {text[:70]}"

    def test_what_the_file_actually_renders_is_clean_too(self) -> None:
        """The literals are the source; these are the finished sentences.

        Anything built at call time (about_text, an update offer, a disc
        summary) is only a string once it is called, so it is called.
        """
        rendered = [
            value
            for name, value in vars(strings).items()
            if not name.startswith("_") and isinstance(value, str)
        ]
        rendered += [
            strings.about_text(),
            strings.update_offer("1.1.0", "1.0.0"),
            strings.engine_would_not_start(RuntimeError("no engine")),
            strings.cannot_open_file("a-file.txt"),
            strings.menu_command_unsupported("a reason"),
            strings.game_note(ours=True, image=False),
            strings.game_note(ours=False, image=True),
            strings.disc_summary("blu-ray", "A DISC", 2),
        ]
        for text in rendered:
            assert self.EM_DASH not in text, text[:70]
            lowered = text.lower()
            for word in self.BANNED_WORDS:
                assert word not in lowered, text[:70]


class TestSayWhatToDoNext:
    """Every failure names a next step. A dead end is the thing we do not ship."""

    def test_the_encrypted_disc_dialogs_say_what_goldwing_does_play(self) -> None:
        for text in (strings.PROTECTED_BLU_RAY, strings.PROTECTED_DVD):
            assert "locked commercial" in text
            assert strings.UNPROTECTED_ONLY in text
            assert strings.PLAYER_PAGE in text

    def test_the_encrypted_headlines_name_the_disc_not_a_codec(self) -> None:
        assert strings.PROTECTED_BLU_RAY_TITLE == "This is a locked commercial Blu-ray"
        assert strings.PROTECTED_DVD_TITLE == "This is a locked commercial DVD"

    def test_a_failure_is_never_only_a_diagnosis(self) -> None:
        # Two sentences at least: what happened, then what to do about it.
        for text in (
            strings.DRIVE_EMPTY,
            strings.NOT_A_COPY,
            strings.GAME_MENU_MISSING,
            strings.CANNOT_READ_DISC,
            strings.CANNOT_READ_BLU_RAY,
            strings.DAMAGED_INDEX,
            strings.NOTHING_TO_PLAY,
            strings.UNEXPECTED_PROBLEM,
            strings.NOTHING_TO_FILL_THE_SCREEN,
            strings.UPDATE_UNEXPECTED,
            strings.UPDATE_NOT_OURS,
            strings.UPDATE_COULD_NOT_START,
        ):
            assert len([bit for bit in text.split(". ") if bit.strip()]) >= 2, text

    def test_the_update_check_reads_like_the_menu_that_starts_it(self) -> None:
        # Help > "Check for a new Goldwing…", so the sentence under it says
        # who is being asked, not which server answered.
        assert strings.UPDATE_MENU == "Check for a new Goldwing…"
        assert "We The Indies" in strings.UPDATE_CHECKING
        assert "Goldwing" in strings.UPDATE_CHECKING
        assert "server" not in strings.UPDATE_CHECKING.lower()


class TestFormatting:
    def test_a_timecode_drops_the_hour_when_there_is_not_one(self) -> None:
        assert strings.timecode(0) == "0:00"
        assert strings.timecode(65_000) == "1:05"
        assert strings.timecode(3_600_000) == "1:00:00"
        assert strings.timecode(-5) == "0:00"

    def test_a_disc_summary_reads_like_a_sentence_fragment(self) -> None:
        assert strings.disc_summary("blu-ray", "WTI_MENU", 2) == "Blu-ray · “WTI_MENU” · 2 titles"
        assert strings.disc_summary("blu-ray", "", 1) == "Blu-ray · 1 title"
        assert strings.disc_summary("data", "ARCHIVE", 0) == "Data disc · “ARCHIVE”"

    def test_file_sizes_are_readable(self) -> None:
        assert strings.file_size(512) == "512 bytes"
        assert strings.file_size(2048) == "2.0 KB"
        assert strings.file_size(5 * 1024 * 1024) == "5.0 MB"
