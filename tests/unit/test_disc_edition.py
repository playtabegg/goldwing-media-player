"""The numbered-edition record reader (D3, 30 Aug 2026)."""

from __future__ import annotations

import json
from pathlib import Path

from wti_player.optical import edition as E


def _write(root: Path, rel: str, record: dict[str, object]) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


def test_reads_a_record_beside_the_document_on_a_game_disc(tmp_path: Path) -> None:
    _write(tmp_path, "menu/.wti_edition.json", {"schema": 1, "title": "Foxtail", "edition": "standard", "number": 7, "issued": "2026-09-19", "signed": False})
    rec = E.read(tmp_path)
    assert rec is not None
    assert rec.number == 7 and rec.title == "Foxtail" and rec.signed is False
    assert rec.line == "Copy 7 of the standard edition"
    assert rec.source == tmp_path / "menu" / ".wti_edition.json"


def test_a_disc_without_a_record_or_with_a_bad_one_reads_as_none(tmp_path: Path) -> None:
    assert E.read(tmp_path) is None
    _write(tmp_path, ".wti_edition.json", {"schema": 1, "number": 0})
    assert E.read(tmp_path) is None
    (tmp_path / ".wti_edition.json").write_text("{nope", encoding="utf-8")
    assert E.read(tmp_path) is None
    _write(tmp_path, ".wti_edition.json", {"schema": 2, "number": 3})
    assert E.read(tmp_path) is None


def test_a_large_number_reads_with_a_thousands_separator(tmp_path: Path) -> None:
    _write(tmp_path, ".wti_edition.json", {"schema": 1, "title": "X", "edition": "deluxe", "number": 12345, "issued": "2026-09-19", "signed": True})
    rec = E.read(tmp_path)
    assert rec is not None and rec.line == "Copy 12,345 of the deluxe edition" and rec.signed is True
