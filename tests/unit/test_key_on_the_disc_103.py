"""1.0.3: a copy's preservation key, read from the disc and shown only when asked (his word of 2 Oct 2026).

"Only that it has a key, but you can click that button to reveal the key ... if the prints for some reason just goes
away ... and you lose your account information, you can still put your disc into Goldwing and it'll be able to get
that code." So the copy's record on the disc may carry the key; the Player reads it, shows it on the button, copies
it on the other, stores nothing, and never shows the copy's number.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

from wti_player import shelf, strings
from wti_player.optical import edition as E
from wti_player.optical import meta as disc_meta
from wti_player.optical.identify import DiscKind, DiscProfile

KEY = "7KQ4-M2XP-9D3A"
GAME = {"launch_options": [], "has_mod_tool": False, "has_bonus": False, "mac_build": False, "linux_build": False, "online_updates": False, "menu_language": "English"}


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


def _disc(folder: Path, record: dict | None) -> Path:
    (folder / "menu").mkdir(parents=True, exist_ok=True)
    meta = {"schema": 1, "kind": "game", "title": "Foxtail", "author": "Playtable", "id": "x", "version": "1.0.0", "made_by": "We the Indies", "game": GAME}
    (folder / "menu" / ".wti_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if record is not None:
        (folder / "menu" / ".wti_edition.json").write_text(json.dumps(record), encoding="utf-8")
    return folder


def _record(**over) -> dict:
    return {"schema": 1, "title": "Foxtail", "title_id": "x", "edition": "standard", "number": 7, "issued": "2026-10-02", "order_id": "o", "copy_index": 1, "signed": False, **over}


def _profile(root: Path, *, ours: bool = True) -> DiscProfile:
    return DiscProfile(kind=DiscKind.GAME_DISC, root=root, ours=ours, meta=disc_meta.read(root))


class TestReadingTheKey:
    def test_a_key_is_read_as_it_is_printed(self, tmp_path: Path) -> None:
        # As a person might have typed or pasted it: lower case, spaced, or with a typographer's dash.
        typeset = KEY.replace("-", chr(0x2013))
        for index, written in enumerate((KEY, "7kq4m2xp9d3a", " 7KQ4 M2XP 9D3A ", typeset)):
            record = E.read(_disc(tmp_path / str(index), _record(key=written)))
            assert record is not None and record.key == KEY

    def test_a_record_from_before_has_no_key_and_still_reads(self, tmp_path: Path) -> None:
        record = E.read(_disc(tmp_path, _record()))
        assert record is not None and record.key == "" and record.number == 7

    @pytest.mark.parametrize("bad", ["", "7KQ4-M2XP-9D3", "7KQ4-M2XP-9D3AA", "0KQ4-M2XP-9D3A", "7KQ4-M2XP-9D3!", "7KQ4-M2XP-9D3C", 7, None, ["7KQ4-M2XP-9D3A"], "A" * 200])
    def test_what_is_not_a_key_is_never_offered_as_one(self, tmp_path: Path, bad) -> None:
        record = E.read(_disc(tmp_path, _record(key=bad)))
        assert record is not None and record.key == ""

    def test_a_record_that_claims_a_signature_it_does_not_have_offers_nothing(self, tmp_path: Path) -> None:
        forged = _record(key=KEY, signed=True, public_key="AAAA", signature="AAAA")
        record = E.read(_disc(tmp_path, forged))
        assert record is not None and record.trust == E.BAD and record.key == ""

    def test_an_unsigned_record_still_says_its_key(self, tmp_path: Path) -> None:
        # A disc built by hand on a machine with no edition key: the record is a number and a key, said as such.
        record = E.read(_disc(tmp_path, _record(key=KEY)))
        assert record is not None and record.trust == E.UNSIGNED and record.key == KEY


class TestTheButton:
    def _view(self, qt_app):
        from wti_player.ui.views import GameView

        return GameView()

    def test_a_copy_with_its_key_on_the_disc_offers_the_button_and_shows_nothing_until_asked(self, qt_app, tmp_path: Path) -> None:
        view = self._view(qt_app)
        view.show_disc(_profile(_disc(tmp_path, _record(key=KEY))))
        assert not view.key_button.isHidden() and view.key_button.text() == strings.SHOW_KEY
        assert view.key_text.isHidden() and view.key_text.text() == "" and view.key_copy.isHidden()
        assert KEY not in view.carries.text() and strings.KEY_ON_DISC in view.carries.text()

    def test_show_key_reveals_it_and_hide_key_takes_it_off_the_screen(self, qt_app, tmp_path: Path) -> None:
        view = self._view(qt_app)
        view.show_disc(_profile(_disc(tmp_path, _record(key=KEY))))
        view.key_button.click()
        assert not view.key_text.isHidden() and view.key_text.text() == KEY
        assert not view.key_copy.isHidden() and view.key_button.text() == strings.HIDE_KEY
        view.key_button.click()
        assert view.key_text.isHidden() and view.key_text.text() == "" and view.key_copy.isHidden()
        assert view.key_button.text() == strings.SHOW_KEY

    def test_an_unsigned_record_says_so_under_the_key_and_a_signed_one_does_not(self, qt_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        view = self._view(qt_app)
        view.show_disc(_profile(_disc(tmp_path / "unsigned", _record(key=KEY))))
        assert view.key_note.isHidden()  # nothing is said before the key is asked for
        view.key_button.click()
        assert not view.key_note.isHidden() and view.key_note.text() == strings.KEY_NOT_SIGNED
        view.key_button.click()
        assert view.key_note.isHidden()
        # Signed by an unknown key reads the same as unsigned: shown, and not vouched for.
        monkeypatch.setattr(E, "trust_of", lambda _record, _trusted=None: E.UNTRUSTED)
        view.show_disc(_profile(_disc(tmp_path / "untrusted", _record(key=KEY, signed=True))))
        view.key_button.click()
        assert view.key_text.text() == KEY and not view.key_note.isHidden()
        # Signed by us: the key, and no caveat.
        monkeypatch.setattr(E, "trust_of", lambda _record, _trusted=None: E.SIGNED)
        view.show_disc(_profile(_disc(tmp_path / "signed", _record(key=KEY, signed=True))))
        view.key_button.click()
        assert view.key_text.text() == KEY and view.key_note.isHidden()

    def test_leaving_the_page_takes_the_key_with_it(self, qt_app, tmp_path: Path) -> None:
        view = self._view(qt_app)
        view.show_disc(_profile(_disc(tmp_path, _record(key=KEY))))
        view.key_button.click()
        view.forget()
        assert view._key == "" and view.key_text.text() == ""
        assert all(w.isHidden() for w in (view.key_text, view.key_copy, view.key_note, view.key_button))
        view.toggle_key()
        view.copy_key()
        assert view.key_text.text() == ""

    def test_copy_puts_the_key_on_the_clipboard_and_says_so_once(self, qt_app, tmp_path: Path) -> None:
        view = self._view(qt_app)
        said: list[bool] = []
        view.key_copied.connect(lambda: said.append(True))
        view.show_disc(_profile(_disc(tmp_path, _record(key=KEY))))
        view.key_button.click()
        view.key_copy.click()
        assert QApplication.clipboard().text() == KEY and said == [True]

    def test_the_next_disc_starts_hidden_and_a_disc_without_a_key_offers_no_button(self, qt_app, tmp_path: Path) -> None:
        view = self._view(qt_app)
        view.show_disc(_profile(_disc(tmp_path / "a", _record(key=KEY))))
        view.key_button.click()
        view.show_disc(_profile(_disc(tmp_path / "b", _record(key="2346-789A-CDEZ"))))
        assert view.key_text.isHidden() and view.key_text.text() == "" and view.key_button.text() == strings.SHOW_KEY
        # A record with no key (every disc made before): the key is on the label, and there is nothing to press.
        view.show_disc(_profile(_disc(tmp_path / "c", _record())))
        assert view.key_button.isHidden() and view.key_copy.isHidden()
        assert strings.KEY_ON_LABEL in view.carries.text()
        view.toggle_key()
        view.copy_key()
        assert view.key_text.isHidden() and view.key_text.text() == ""
        # No record at all, and a game that is not ours: no button, no key line.
        view.show_disc(_profile(_disc(tmp_path / "d", None)))
        assert view.key_button.isHidden() and view.carries.isHidden()
        view.show_disc(_profile(_disc(tmp_path / "e", _record(key=KEY)), ours=False))
        assert view.key_button.isHidden()


class TestNoCopyNumberIsShown:
    def test_the_header_says_the_copy_has_a_key_and_where_never_its_number(self, qt_app, tmp_path: Path) -> None:
        from wti_player.ui.views import DiscHeader

        header = DiscHeader()
        header.show_disc(_profile(_disc(tmp_path / "a", _record(key=KEY))))
        assert strings.KEY_FACT_ON_DISC in header.facts.text() and "Copy 7" not in header.facts.text() and KEY not in header.facts.text()
        header.show_disc(_profile(_disc(tmp_path / "b", _record())))
        assert strings.KEY_FACT in header.facts.text() and "Copy 7" not in header.facts.text()

    def test_the_shelf_says_the_same(self, tmp_path: Path) -> None:
        with_key = shelf.read_entry(_disc(tmp_path / "a", _record(key=KEY)))
        without = shelf.read_entry(_disc(tmp_path / "b", _record()))
        assert with_key is not None and strings.KEY_FACT_ON_DISC in with_key.describe() and KEY not in with_key.describe()
        assert without is not None and strings.KEY_FACT in without.describe()
        assert "Copy" not in with_key.describe() and "Copy" not in without.describe()

    def test_the_words_say_what_the_key_is_and_is_not(self) -> None:
        assert "not a lock" in strings.KEY_ON_DISC and "wetheindies.com/editions" in strings.KEY_ON_DISC
        # A key that is only seen takes nothing: it names the copy, it does not make it anyone's.
        assert "as yours" not in strings.KEY_ON_DISC and "as yours" not in strings.KEY_ON_LABEL
        assert "keeps no note" in strings.KEY_COPIED and "clipboard" in strings.KEY_COPIED
