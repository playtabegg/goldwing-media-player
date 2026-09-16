"""Test-only minisign signer. The Player never signs; its tests must.

A copy of the signing half of ``tools/wti_minisign.py`` at the estate root,
kept here so this repository's suite runs on its own checkout.
"""

from __future__ import annotations

import base64
import hashlib
import os

from wti_player.update._ed25519 import BASE, Q, encode_point, point_mul


def _clamped(seed: bytes) -> tuple[int, bytes]:
    digest = hashlib.sha512(seed).digest()
    lower = bytearray(digest[:32])
    lower[0] &= 248
    lower[31] &= 127
    lower[31] |= 64
    return int.from_bytes(lower, "little"), digest[32:]


def public_key(seed: bytes) -> bytes:
    scalar, _ = _clamped(seed)
    return encode_point(point_mul(BASE, scalar))


def sign(seed: bytes, message: bytes) -> bytes:
    scalar, prefix = _clamped(seed)
    pub = encode_point(point_mul(BASE, scalar))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % Q
    r_point = encode_point(point_mul(BASE, r))
    k = int.from_bytes(hashlib.sha512(r_point + pub + message).digest(), "little") % Q
    s = (r + k * scalar) % Q
    return r_point + s.to_bytes(32, "little")


class Signer:
    def __init__(self, seed: bytes | None = None, key_id: bytes | None = None) -> None:
        self.seed = seed or os.urandom(32)
        self.key_id = key_id or os.urandom(8)
        self.pub_raw = public_key(self.seed)

    @property
    def pub_line(self) -> str:
        return base64.b64encode(b"Ed" + self.key_id + self.pub_raw).decode()

    def minisig(self, content: bytes, trusted: str = "timestamp:0\tfile:x", alg: bytes = b"ED") -> str:
        digest = hashlib.blake2b(content, digest_size=64).digest()
        signature = sign(self.seed, digest if alg == b"ED" else content)
        global_sig = sign(self.seed, signature + trusted.encode())
        return (
            "untrusted comment: test\n"
            f"{base64.b64encode(alg + self.key_id + signature).decode()}\n"
            f"trusted comment: {trusted}\n"
            f"{base64.b64encode(global_sig).decode()}\n"
        )
