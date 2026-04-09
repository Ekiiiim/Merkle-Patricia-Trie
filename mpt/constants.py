"""Keccak-256 and Ethereum empty trie root (execution-layer MPT)."""

from __future__ import annotations

import rlp
from Crypto.Hash import keccak

HASH_LEN = 32


def keccak256(data: bytes) -> bytes:
    h = keccak.new(digest_bits=256)
    h.update(data)
    return h.digest()


# Ethereum: root of empty trie = keccak256(RLP('')) where RLP('') = 0x80
EMPTY_TRIE_ROOT: bytes = keccak256(rlp.encode(b""))

# Back-compat alias used in older code paths
h = keccak256
