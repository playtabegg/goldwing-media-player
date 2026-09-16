"""Ed25519 (RFC 8032) in the standard library only: sign and verify.

This is the portable publisher's copy. The Player carries a verify-only
copy in ``wti_player/update/_ed25519.py``; the release publisher round-trip
test proves agreement. No private key is stored in this module.

Optimised for auditability, not speed: affine coordinates, one inversion per
addition, the arithmetic reads like the RFC. A verify costs tens of
milliseconds. Malleability: ``S`` is range-checked against the group order
and point decoding rejects non-canonical encodings and small-order keys.
"""

from __future__ import annotations

import hashlib
import secrets

P = 2**255 - 19
Q = 2**252 + 27742317777372353535851937790883648493
SEED_BYTES = 32


def _inv(x: int) -> int:
    return pow(x, P - 2, P)


D = -121665 * _inv(121666) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)

Point = tuple[int, int]


def _x_recover(y: int) -> int:
    xx = (y * y - 1) * _inv(D * y * y + 1)
    x = pow(xx, (P + 3) // 8, P)
    if (x * x - xx) % P != 0:
        x = (x * SQRT_M1) % P
    if x % 2 != 0:
        x = P - x
    return x


_BASE_Y = 4 * _inv(5) % P
BASE: Point = (_x_recover(_BASE_Y), _BASE_Y)
IDENTITY: Point = (0, 1)


def point_add(p1: Point, p2: Point) -> Point:
    x1, y1 = p1
    x2, y2 = p2
    prod = D * x1 * x2 * y1 * y2
    denom_x = (1 + prod) % P
    denom_y = (1 - prod) % P
    both = _inv(denom_x * denom_y % P)
    x3 = (x1 * y2 + x2 * y1) * (both * denom_y)
    y3 = (y1 * y2 + x1 * x2) * (both * denom_x)
    return (x3 % P, y3 % P)


def point_mul(point: Point, scalar: int) -> Point:
    """Double-and-add. Not constant time: the signer runs on the publisher's
    machine with the seed already in memory, and the verifier only ever
    multiplies public values."""
    result = IDENTITY
    addend = point
    while scalar > 0:
        if scalar & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        scalar >>= 1
    return result


def is_on_curve(point: Point) -> bool:
    x, y = point
    return (-x * x + y * y - 1 - D * x * x * y * y) % P == 0


def encode_point(point: Point) -> bytes:
    x, y = point
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def decode_point(data: bytes) -> Point | None:
    if len(data) != 32:
        return None
    encoded = int.from_bytes(data, "little")
    y = encoded & ((1 << 255) - 1)
    if y >= P:
        return None
    sign = encoded >> 255
    x = _x_recover(y)
    if x == 0 and sign == 1:
        return None
    if x & 1 != sign:
        x = P - x
    point = (x % P, y)
    if not is_on_curve(point):
        return None
    return point


def _hash_to_scalar(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little") % Q


def _clamped_scalar(seed: bytes) -> tuple[int, bytes]:
    digest = hashlib.sha512(seed).digest()
    lower = bytearray(digest[:32])
    lower[0] &= 248
    lower[31] &= 127
    lower[31] |= 64
    return int.from_bytes(lower, "little"), digest[32:]


def generate_seed() -> bytes:
    return secrets.token_bytes(SEED_BYTES)


def public_key(seed: bytes) -> bytes:
    if len(seed) != SEED_BYTES:
        raise ValueError(f"Ed25519 seed must be {SEED_BYTES} bytes, got {len(seed)}")
    scalar, _prefix = _clamped_scalar(seed)
    return encode_point(point_mul(BASE, scalar))


def sign(seed: bytes, message: bytes) -> bytes:
    """64-byte detached signature."""
    if len(seed) != SEED_BYTES:
        raise ValueError(f"Ed25519 seed must be {SEED_BYTES} bytes, got {len(seed)}")
    scalar, prefix = _clamped_scalar(seed)
    pub = encode_point(point_mul(BASE, scalar))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % Q
    r_point = encode_point(point_mul(BASE, r))
    k = int.from_bytes(hashlib.sha512(r_point + pub + message).digest(), "little") % Q
    s = (r + k * scalar) % Q
    return r_point + s.to_bytes(32, "little")


def verify(public_key_bytes: bytes, message: bytes, signature: bytes) -> bool:
    """True iff the signature is valid. Never raises: malformed is False."""
    if not isinstance(public_key_bytes, (bytes, bytearray)):
        return False
    if not isinstance(signature, (bytes, bytearray)):
        return False
    if len(public_key_bytes) != 32 or len(signature) != 64:
        return False
    r_point = decode_point(bytes(signature[:32]))
    if r_point is None:
        return False
    a_point = decode_point(bytes(public_key_bytes))
    if a_point is None:
        return False
    if point_mul(a_point, 8) == IDENTITY:
        return False
    s_scalar = int.from_bytes(bytes(signature[32:]), "little")
    if s_scalar >= Q:
        return False
    k = _hash_to_scalar(bytes(signature[:32]) + bytes(public_key_bytes) + bytes(message))
    left = point_mul(BASE, s_scalar)
    right = point_add(r_point, point_mul(a_point, k))
    return left == right


__all__ = ["SEED_BYTES", "generate_seed", "public_key", "sign", "verify"]
