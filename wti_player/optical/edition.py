"""The numbered-edition record a We The Indies disc may carry (D3, 30 Aug 2026).

``.wti_edition.json`` sits beside ``.wti_meta.json`` and says which copy this
is: the title, the edition, the number, the day it was issued. The factory
signs it when it has a key; a record without a signature is still a number,
shown as one, and the registry at ``/editions/<slug>/<n>`` is the proof.

Read-only, never a gate. The Player shows the number in the inspector;
Rook certifies it. A disc without a record plays exactly as before.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .meta import SEARCH_PATHS

EDITION_NAME = ".wti_edition.json"
KNOWN_SCHEMA = 1
MAX_DOCUMENT_BYTES = 64 * 1024

#: The factory's edition keys, public halves, base64 (L4, 30 Aug 2026).
#: Populated 11 Sep 2026 (§G) with the 32-byte key from wti-edition.pub, key
#: id 44B413615D64E725 - the 42-byte minisign blob minus "Ed" and the id,
#: which is what a verifier compares. The same list Rook carries in
#: rook_config.json. Read-only, never a gate. What it proves is that the
#: RECORD was signed by We The Indies; it does not bind the record to the
#: disc it sits on (R2CORE-1), so the copy says "signed by", never "genuine".
TRUSTED_EDITION_KEYS_B64: tuple[str, ...] = ("gZCmC2M261o5TQEjs3MTF21PXgRKXDOYFMOh6OzP/90=",)

#: What the signature block on a record amounts to.
SIGNED = "signed"          # verifies against a key in the trusted list
UNTRUSTED = "untrusted"    # verifies against the key it names, not one we trust
UNSIGNED = "unsigned"      # says signed: false
BAD = "bad"                # says it is signed and is not


@dataclass(frozen=True)
class DiscEdition:
    title: str = ""
    edition: str = "standard"
    number: int = 0
    issued: str = ""
    signed: bool = False
    #: SIGNED, UNTRUSTED, UNSIGNED or BAD.
    trust: str = UNSIGNED
    source: Path | None = None

    @property
    def signed_by_us(self) -> bool:
        return self.trust == SIGNED

    @property
    def line(self) -> str:
        """One line for a person: 'Copy 7 of the standard edition'."""
        if self.number < 1:
            return ""
        return f"Copy {self.number:,} of the {self.edition} edition"


def find_record(root: Path) -> Path | None:
    """The record, looked for beside each place a document can live."""
    for rel in SEARCH_PATHS:
        candidate = (root / rel).parent / EDITION_NAME
        if candidate.is_file():
            return candidate
    return None


def read(root: Path | str) -> DiscEdition | None:
    """The disc's edition record, or None when it has none or it will not parse."""
    path = find_record(Path(root))
    if path is None:
        return None
    try:
        if path.stat().st_size > MAX_DOCUMENT_BYTES:
            return None
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("schema") != KNOWN_SCHEMA:
        return None
    number = raw.get("number")
    if not isinstance(number, int) or number < 1:
        return None
    return DiscEdition(
        title=str(raw.get("title") or ""),
        edition=str(raw.get("edition") or "standard"),
        number=number,
        issued=str(raw.get("issued") or ""),
        signed=bool(raw.get("signed")),
        trust=trust_of(raw),
        source=path,
    )


def _signing_bytes(record: dict[str, Any]) -> bytes:
    """What the factory signed: the record without its signature block, canonical JSON.

    Byte for byte `rialto_core.edition._signing_bytes` and Rook's
    `canonical.rs`: sorted keys, no spaces, UTF-8.
    """
    body = {k: v for k, v in record.items() if k not in ("signed", "signature", "public_key")}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def trust_of(record: dict[str, Any], trusted_b64: tuple[str, ...] | None = None) -> str:
    """SIGNED, UNTRUSTED, UNSIGNED or BAD. Never raises, never gates play."""
    if trusted_b64 is None:
        # Read at call time, not bound at import: the list is pasted in later.
        trusted_b64 = TRUSTED_EDITION_KEYS_B64
    if not record.get("signed"):
        return UNSIGNED
    import base64

    from ..update._ed25519 import verify as ed25519_verify

    try:
        pub = base64.b64decode(str(record.get("public_key") or ""))
        sig = base64.b64decode(str(record.get("signature") or ""))
    except (ValueError, TypeError):
        return BAD
    if len(pub) != 32 or len(sig) != 64:
        return BAD
    try:
        ok = bool(ed25519_verify(pub, _signing_bytes(record), sig))
    except Exception:
        return BAD
    if not ok:
        return BAD
    trusted = set()
    for line in trusted_b64:
        try:
            trusted.add(base64.b64decode(line))
        except (ValueError, TypeError):
            continue
    return SIGNED if pub in trusted else UNTRUSTED


__all__ = ["BAD", "EDITION_NAME", "KNOWN_SCHEMA", "SIGNED", "TRUSTED_EDITION_KEYS_B64", "UNSIGNED", "UNTRUSTED", "DiscEdition", "find_record", "read", "trust_of"]
