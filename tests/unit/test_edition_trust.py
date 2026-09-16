"""L4 (30 Aug 2026): the signed record on every shelf, verified, never a gate."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

from wti_player import shelf
from wti_player.optical import edition as E

TOOLS = Path(__file__).resolve().parents[3] / "tools"
if not (TOOLS / "wti_ed25519.py").is_file():
    pytest.skip("the estate's tools are not beside this checkout", allow_module_level=True)
sys.path.insert(0, str(TOOLS))
import wti_ed25519  # noqa: E402

SEED = bytes(range(32))
PUB = wti_ed25519.public_key(SEED)


def signed_record(number: int = 7, *, seed: bytes = SEED) -> dict[str, object]:
    record = {"schema": 1, "title": "Foxtail", "title_id": "x", "edition": "standard", "number": number, "issued": "2026-09-19", "order_id": "o", "copy_index": 0, "signed": False}
    body = {k: v for k, v in record.items() if k not in ("signed", "signature", "public_key")}
    message = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    out = dict(record)
    out["signed"] = True
    out["public_key"] = base64.b64encode(wti_ed25519.public_key(seed)).decode()
    out["signature"] = base64.b64encode(wti_ed25519.sign(seed, message)).decode()
    return out


def test_a_record_signed_by_a_trusted_key_is_signed_by_us() -> None:
    trusted = (base64.b64encode(PUB).decode(),)
    assert E.trust_of(signed_record(), trusted) == E.SIGNED


def test_the_same_record_is_untrusted_with_an_empty_list_and_bad_when_tampered() -> None:
    record = signed_record()
    assert E.trust_of(record, ()) == E.UNTRUSTED
    tampered = dict(record, number=8)
    assert E.trust_of(tampered, (base64.b64encode(PUB).decode(),)) == E.BAD
    assert E.trust_of({"schema": 1, "number": 3, "signed": False}, ()) == E.UNSIGNED
    assert E.trust_of({"schema": 1, "number": 3, "signed": True, "public_key": "??", "signature": "??"}, ()) == E.BAD


def test_the_trusted_list_holds_the_factory_key_and_no_other(monkeypatch: pytest.MonkeyPatch) -> None:
    # §G.4 (11 Sep 2026): one 32-byte key at runtime, and a record signed by any
    # other key stays untrusted against it. The green badge is not the check.
    assert len(E.TRUSTED_EDITION_KEYS_B64) == 1
    assert len(base64.b64decode(E.TRUSTED_EDITION_KEYS_B64[0])) == 32
    assert E.TRUSTED_EDITION_KEYS_B64[0] != base64.b64encode(PUB).decode()
    assert E.trust_of(signed_record()) == E.UNTRUSTED


def test_the_shelf_row_says_signed_only_when_it_verifies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "copy"
    root.mkdir()
    (root / ".wti_meta.json").write_text(json.dumps({"schema": 1, "kind": "game", "title": "Foxtail", "author": "Playtable", "id": "x", "version": "1.0.0", "made_by": "We the Indies"}), encoding="utf-8")
    (root / ".wti_edition.json").write_text(json.dumps(signed_record()), encoding="utf-8")
    entry = shelf.read_entry(root)
    assert entry is not None and "Copy 7" in entry.describe() and shelf.SIGNED_BY_US not in entry.describe()
    monkeypatch.setattr(E, "TRUSTED_EDITION_KEYS_B64", (base64.b64encode(PUB).decode(),))
    entry = shelf.read_entry(root)
    assert entry is not None and entry.signed_by_us and entry.describe().endswith(shelf.SIGNED_BY_US)
