"""Key material as hex nibbles (0–15), matching the usual MPT convention."""

from __future__ import annotations


def key_to_nibbles(key: bytes) -> tuple[int, ...]:
    out: list[int] = []
    for b in key:
        out.append(b >> 4)
        out.append(b & 0x0F)
    return tuple(out)


def nibbles_to_bytes(nibbles: tuple[int, ...]) -> bytes:
    if len(nibbles) % 2:
        raise ValueError("nibble length must be even for full-byte encoding")
    out = bytearray()
    for i in range(0, len(nibbles), 2):
        out.append((nibbles[i] << 4) | nibbles[i + 1])
    return bytes(out)


def common_prefix_length(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i
