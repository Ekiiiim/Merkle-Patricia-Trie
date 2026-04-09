"""
Ethereum-compatible Merkle Patricia Trie node encoding (RLP + Keccak-256).

Matches execution-layer conventions:
  * Paths in leaf/extension nodes use **hex-prefix (compact)** encoding.
  * Branch nodes are RLP lists of **17** byte-strings (16 children + value slot).
  * A child reference is **RLP(child)** if len < 32, else **keccak256(RLP(child))**.
  * Trie **state root** is always **keccak256(RLP(root_node))**; empty trie uses
    ``keccak256(RLP(b''))`` → ``EMPTY_TRIE_ROOT``.

**Intentional differences from mainnet state trie usage** (structure still matches):
  * Keys are expanded from raw bytes to nibbles without ``keccak256(key)`` (Ethereum
    state trie uses hashed keys; generic MPT / tests often use raw paths).
  * Stored values are opaque ``bytes`` (state trie stores RLP(account)).
"""

from __future__ import annotations

from typing import Optional

import rlp

from mpt.constants import EMPTY_TRIE_ROOT, keccak256
from mpt.nodes import Branch, Extension, Leaf, Node


def encode_hex_prefix(nibbles: tuple[int, ...], is_leaf: bool) -> bytes:
    """Compact path encoding (Ethereum yellow paper / py-trie)."""
    nibbles = list(nibbles)
    odd = len(nibbles) % 2
    flags = (2 if is_leaf else 0) + odd
    if odd:
        out = [flags << 4 | nibbles[0]]
        nibbles = nibbles[1:]
    else:
        out = [flags << 4]
    for i in range(0, len(nibbles), 2):
        out.append((nibbles[i] << 4) | nibbles[i + 1])
    return bytes(out)


def decode_hex_prefix(data: bytes) -> tuple[tuple[int, ...], bool]:
    """Decode compact path → (nibbles, is_leaf)."""
    if not data:
        return (), False
    first = data[0]
    flags = first >> 4
    is_leaf = flags >= 2
    odd = flags % 2
    nibbles: list[int] = []
    if odd:
        nibbles.append(first & 0x0F)
    for b in data[1:]:
        nibbles.append(b >> 4)
        nibbles.append(b & 0x0F)
    return tuple(nibbles), is_leaf


def embed_ref(node: Optional[Node]) -> bytes:
    """
    Reference stored in a parent branch/extension: ``b''`` if missing; otherwise
    RLP(node) if short, else keccak256(RLP(node)).
    """
    if node is None:
        return b""
    raw = rlp_encode_node(node)
    if len(raw) < 32:
        return raw
    return keccak256(raw)


def rlp_encode_node(node: Node) -> bytes:
    """Full RLP serialization of a non-None trie node."""
    if isinstance(node, Leaf):
        return rlp.encode([encode_hex_prefix(node.path, True), node.value])
    if isinstance(node, Extension):
        return rlp.encode([encode_hex_prefix(node.path, False), embed_ref(node.child)])
    if isinstance(node, Branch):
        slots = [embed_ref(c) for c in node.children]
        val = node.value if node.value is not None else b""
        return rlp.encode(slots + [val])
    raise TypeError(node)


def trie_root_hash(node: Optional[Node]) -> bytes:
    """32-byte state root (block header style)."""
    if node is None:
        return EMPTY_TRIE_ROOT
    return keccak256(rlp_encode_node(node))


def ref_matches_embedded(ref: bytes, child_rlp: bytes) -> bool:
    """Whether ``ref`` from a parent node points to ``child_rlp``."""
    if not ref:
        return False
    if len(child_rlp) < 32:
        return ref == child_rlp
    return ref == keccak256(child_rlp)


# Proof / API aliases
encode_node = rlp_encode_node
node_hash = trie_root_hash
