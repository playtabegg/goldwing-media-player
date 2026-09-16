"""A bit reader for the BD formats, which pack fields across byte boundaries.

Everything in BDMV is big-endian and a lot of it is sub-byte. The readers in
this package are deliberately strict about running off the end of a buffer:
a truncated ``.mpls`` is a disc problem the user must be told about, not a
``struct.error`` three frames up.
"""

from __future__ import annotations


class TruncatedError(ValueError):
    """The buffer ended in the middle of a field."""


class BitReader:
    """Big-endian bit reader over a ``bytes``."""

    __slots__ = ("_data", "_pos")

    def __init__(self, data: bytes, offset: int = 0) -> None:
        self._data = data
        self._pos = offset * 8

    @property
    def byte_pos(self) -> int:
        """Current position in bytes. Only meaningful when byte-aligned."""
        return self._pos // 8

    @property
    def size(self) -> int:
        return len(self._data)

    def seek(self, offset: int) -> None:
        self._pos = offset * 8

    def skip(self, bits: int) -> None:
        self._pos += bits

    def remaining(self) -> int:
        """Bytes left from the current (rounded-up) position."""
        return max(0, len(self._data) - (self._pos + 7) // 8)

    def bits(self, count: int) -> int:
        end = self._pos + count
        if end > len(self._data) * 8:
            raise TruncatedError(
                f"needed {count} bits at bit {self._pos}, buffer is {len(self._data)} bytes"
            )
        value = 0
        pos = self._pos
        while count:
            byte = self._data[pos // 8]
            available = 8 - (pos % 8)
            take = min(available, count)
            shift = available - take
            value = (value << take) | ((byte >> shift) & ((1 << take) - 1))
            pos += take
            count -= take
        self._pos = end
        return value

    def u8(self) -> int:
        return self.bits(8)

    def u16(self) -> int:
        return self.bits(16)

    def u24(self) -> int:
        return self.bits(24)

    def u32(self) -> int:
        return self.bits(32)

    def read(self, count: int) -> bytes:
        if self._pos % 8:
            raise ValueError("read() needs byte alignment")
        start = self._pos // 8
        if start + count > len(self._data):
            raise TruncatedError(f"needed {count} bytes at {start}, buffer is {len(self._data)}")
        self._pos += count * 8
        return self._data[start : start + count]

    def ascii(self, count: int) -> str:
        return self.read(count).decode("ascii", "replace")
