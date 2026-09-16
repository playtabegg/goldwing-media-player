"""minisign keygen, sign and verify for WTI app releases. Standard library only.

Goldwing Media Player verifies ``latest.json`` and
the installer with a minisign public key compiled into them. This writes the
signatures in minisign's prehashed format (algorithm tag ``ED``: the
signature covers BLAKE2b-512 of the file), which is what the Rust
``minisign-verify`` crate accepts by default and what our Python clients
read. The legacy ``Ed`` tag is not produced and not accepted.

The private key is a 40-byte file: 8-byte key id, 32-byte Ed25519 seed. It is
not minisign's scrypt container, because nothing here consumes one; the
public key and the signatures are the parts that must be minisign-shaped,
and they are. Keep it off the bucket it protects, out of git, and backed up
offline in the operator's protected backup workflow.

    python tools/wti_minisign.py keygen --out <dir>/wti-app-release
    python tools/wti_minisign.py sign   <file> --key <dir>/wti-app-release.key
    python tools/wti_minisign.py verify <file> --pub <dir>/wti-app-release.pub
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wti_ed25519

SIG_ALG = b"ED"
PUB_ALG = b"Ed"
KEY_FILE_BYTES = 8 + wti_ed25519.SEED_BYTES


class MinisignError(Exception):
    """A key or signature file is not what it claims to be."""


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    try:
        return base64.b64decode(text.strip(), validate=True)
    except (ValueError, TypeError) as error:
        raise MinisignError(f"not base64: {error}") from error


@dataclass(frozen=True)
class PublicKey:
    key_id: bytes
    raw: bytes

    @property
    def line(self) -> str:
        return _b64(PUB_ALG + self.key_id + self.raw)


@dataclass(frozen=True)
class Signature:
    key_id: bytes
    signature: bytes
    trusted_comment: str
    global_signature: bytes


def keygen(out_base: Path) -> tuple[Path, Path]:
    key_path = out_base.with_suffix(".key")
    pub_path = out_base.with_suffix(".pub")
    if key_path.exists():
        raise SystemExit(
            f"REFUSING TO OVERWRITE {key_path}. A new key orphans every build carrying "
            "the old public key. Move the old one aside deliberately."
        )
    out_base.parent.mkdir(parents=True, exist_ok=True)
    seed = wti_ed25519.generate_seed()
    key_id = os.urandom(8)
    pub = PublicKey(key_id, wti_ed25519.public_key(seed))
    key_path.write_bytes(key_id + seed)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    pub_path.write_text(
        f"untrusted comment: minisign public key {key_id.hex().upper()}\n{pub.line}\n",
        encoding="utf-8",
    )
    return key_path, pub_path


def load_key(key_path: Path) -> tuple[bytes, bytes]:
    raw = key_path.read_bytes()
    if len(raw) != KEY_FILE_BYTES:
        raise MinisignError(f"{key_path} is not a {KEY_FILE_BYTES}-byte key file (8 id + 32 seed)")
    return raw[:8], raw[8:]


def parse_public_key(text: str) -> PublicKey:
    """Accept a whole ``.pub`` file or just its base64 line."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    payload = [line for line in lines if not line.startswith("untrusted comment:")]
    if len(payload) != 1:
        raise MinisignError("a public key is one base64 line, optionally under an untrusted comment")
    blob = _unb64(payload[0])
    if len(blob) != 42 or blob[:2] != PUB_ALG:
        raise MinisignError("not a minisign Ed25519 public key")
    return PublicKey(blob[2:10], blob[10:])


def load_public_key(pub_path: Path) -> PublicKey:
    return parse_public_key(pub_path.read_text(encoding="utf-8"))


def prehash(content: bytes) -> bytes:
    return hashlib.blake2b(content, digest_size=64).digest()


def sign_bytes(content: bytes, key_id: bytes, seed: bytes, trusted_comment: str) -> str:
    """The text of a ``.minisig`` file for ``content``."""
    signature = wti_ed25519.sign(seed, prehash(content))
    global_sig = wti_ed25519.sign(seed, signature + trusted_comment.encode("utf-8"))
    return (
        "untrusted comment: signature from We The Indies app release key\n"
        f"{_b64(SIG_ALG + key_id + signature)}\n"
        f"trusted comment: {trusted_comment}\n"
        f"{_b64(global_sig)}\n"
    )


def sign_file(target: Path, key_path: Path, comment: str | None = None) -> Path:
    key_id, seed = load_key(key_path)
    trusted = comment or f"timestamp:0\tfile:{target.name}"
    sig_path = target.with_name(target.name + ".minisig")
    sig_path.write_text(sign_bytes(target.read_bytes(), key_id, seed, trusted), encoding="utf-8")
    return sig_path


def parse_signature(text: str) -> Signature:
    lines = text.splitlines()
    if len(lines) < 4:
        raise MinisignError("a .minisig file has four lines")
    blob = _unb64(lines[1])
    if len(blob) != 74:
        raise MinisignError("signature line is not 2 + 8 + 64 bytes")
    if blob[:2] != SIG_ALG:
        raise MinisignError(
            f"signature algorithm {blob[:2]!r} is not the prehashed 'ED' we produce and accept"
        )
    if not lines[2].startswith("trusted comment: "):
        raise MinisignError("third line must be the trusted comment")
    trusted = lines[2][len("trusted comment: "):]
    global_sig = _unb64(lines[3])
    if len(global_sig) != 64:
        raise MinisignError("global signature is not 64 bytes")
    return Signature(blob[2:10], blob[10:], trusted, global_sig)


def verify_bytes(content: bytes, sig_text: str, pub: PublicKey) -> bool:
    """True iff ``sig_text`` is a valid prehashed minisign signature over
    ``content`` by ``pub``. Never raises: anything malformed is False."""
    try:
        sig = parse_signature(sig_text)
    except MinisignError:
        return False
    if sig.key_id != pub.key_id:
        return False
    if not wti_ed25519.verify(pub.raw, prehash(content), sig.signature):
        return False
    return wti_ed25519.verify(
        pub.raw, sig.signature + sig.trusted_comment.encode("utf-8"), sig.global_signature
    )


def verify_file(target: Path, pub_path: Path) -> bool:
    sig_path = target.with_name(target.name + ".minisig")
    if not sig_path.is_file():
        return False
    return verify_bytes(
        target.read_bytes(), sig_path.read_text(encoding="utf-8"), load_public_key(pub_path)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="minisign keygen/sign/verify for WTI app releases")
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("keygen")
    g.add_argument("--out", type=Path, required=True, help="path base, e.g. ~/keys/wti-app-release")
    s = sub.add_parser("sign")
    s.add_argument("file", type=Path)
    s.add_argument("--key", type=Path, required=True)
    s.add_argument("--comment", default=None)
    v = sub.add_parser("verify")
    v.add_argument("file", type=Path)
    v.add_argument("--pub", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.cmd == "keygen":
        key_path, pub_path = keygen(args.out)
        print(f"private key: {key_path}  (BACK THIS UP, keep it out of git and off the bucket)")
        print(f"public  key: {pub_path}")
        print(f"\nEmbed this line in the apps:\n{load_public_key(pub_path).line}")
        return 0
    if args.cmd == "sign":
        if not args.key.exists():
            raise SystemExit(f"No private key at {args.key}. Run keygen first.")
        sig_path = sign_file(args.file, args.key, args.comment)
        print(f"signed: {args.file} -> {sig_path}")
        return 0
    ok = verify_file(args.file, args.pub)
    print(f"{'OK' if ok else 'BAD'}: {args.file}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
