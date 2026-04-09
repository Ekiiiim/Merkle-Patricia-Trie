"""Cryptographic constants (SHA-256; Ethereum mainnet uses Keccak-256)."""

from __future__ import annotations

import hashlib

HASH_LEN = 32


def h(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


# Hash of an empty subtrie (no node). Used for empty branch slots and proof verification.
EMPTY_SUBTREE_HASH: bytes = h(b"\x00mpt:empty\x00")
