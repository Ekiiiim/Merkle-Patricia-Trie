"""
Ethereum-compatible Merkle Patricia Trie node encoding (RLP + Keccak-256).

Matches execution-layer conventions:
  * Paths in leaf/extension nodes use **hex-prefix (compact)** encoding.
  * Branch nodes are RLP lists of **17** byte-strings (16 children + value slot).
  * A child reference is **RLP(child)** if len < 32, else **keccak256(RLP(child))**.
  * Trie **state root** is always **keccak256(RLP(root_node))**; empty trie uses
    ``keccak256(RLP(b''))`` → ``EMPTY_TRIE_ROOT``.

Notes:
  * This project follows the **mainnet state trie keying rule**: trie paths are
    derived from ``keccak256(key)`` expanded into nibbles (hex digits).
  * Stored values are still treated as opaque ``bytes`` (Ethereum state trie
    commonly stores structured RLP payloads such as RLP(account)).
"""

from __future__ import annotations

from typing import Callable, Optional

import rlp

from mpt.constants import EMPTY_TRIE_ROOT, keccak256
from mpt.nodes import Branch, Extension, Leaf, HashNode, Node


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


def path_encoding(nibbles: tuple[int, ...], is_leaf: bool) -> bytes:
    """Backwards-compatible alias for :func:`compact_encoding`."""
    return compact_encoding(nibbles, is_leaf)


def compact_encoding(nibbles: tuple[int, ...], is_leaf: bool) -> bytes:
    """Readable name for Ethereum's hex-prefix (compact) encoding."""
    return encode_hex_prefix(nibbles, is_leaf)


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
    if isinstance(node, HashNode):
        return node.hash
    raw = rlp_encode_node(node)
    if len(raw) < 32:
        return raw
    return keccak256(raw)


def rlp_encode_node(node: Node) -> bytes:
    """Full RLP serialization of a non-None trie node."""
    if isinstance(node, Leaf):
        return rlp.encode([compact_encoding(node.path, True), node.value])
    if isinstance(node, Extension):
        return rlp.encode([compact_encoding(node.path, False), embed_ref(node.child)])
    if isinstance(node, Branch):
        slots = [embed_ref(c) for c in node.children]
        val = node.value if node.value is not None else b""
        return rlp.encode(slots + [val])
    raise TypeError(node)


def trie_root_hash(node: Optional[Node]) -> bytes:
    """32-byte state root (block header style)."""
    if node is None:
        return EMPTY_TRIE_ROOT
    if isinstance(node, HashNode):
        return node.hash
    return keccak256(rlp_encode_node(node))


def ref_matches_embedded(ref: bytes, child_rlp: bytes) -> bool:
    """Whether ``ref`` from a parent node points to ``child_rlp``."""
    if not ref:
        return False
    if len(child_rlp) < 32:
        return ref == child_rlp
    return ref == keccak256(child_rlp)


def trie_root_hash(node: Optional[Node]) -> bytes:
    if node is None:
        return EMPTY_TRIE_ROOT
    if isinstance(node, HashNode):
        return node.hash
    return keccak256(rlp_encode_node(node))

def decode_trie_node(raw: bytes) -> Node:
    """Decodes a raw RLP byte string into a functional MPT Node object.

    This function implements the Ethereum node parsing logic by inspecting 
    the structure of the RLP-decoded list:
    - A list of length 2 represents either a Leaf or an Extension.
    - A list of length 17 represents a Branch.

    It also handles the critical 'embedded node' rule: if a child reference 
    is shorter than 32 bytes, it is decoded immediately; otherwise, it is 
    stored as a HashNode for lazy resolution.

    Args:
        raw: The RLP-encoded bytes of the trie node.

    Returns:
        Node: A Leaf, Extension, or Branch object.

    Raises:
        ValueError: If the RLP is malformed, not a list, or has an 
            unsupported length.
    """
    try:
        decoded = rlp.decode(raw)
    except rlp.DecodingError as e:
        raise ValueError("invalid trie RLP") from e
    
    if not isinstance(decoded, list):
        raise ValueError("trie node must be an RLP list")

    # Leaf or Extension
    if len(decoded) == 2:
        a, b = decoded[0], decoded[1]
        nibbles, is_leaf = decode_hex_prefix(a)
        
        if is_leaf:
            # Case 1: Leaf: Include path and value. (Key preimage is not recoverable from RLP.)
            return Leaf(nibbles, b, None)
        
        # Case 2: Extension.
        ref = b
        if len(ref) < 32:
            return Extension(nibbles, decode_trie_node(ref))
        else:
            return Extension(nibbles, HashNode(ref))

    # Branch
    if len(decoded) == 17:
        children: list[Optional[Node]] = []
        for i in range(16):
            ref = decoded[i]
            if not ref:
                children.append(None)
            elif len(ref) < 32:
                children.append(decode_trie_node(ref))
            else:
                children.append(HashNode(ref))
        
        tail = decoded[16]
        value: Optional[bytes] = None if tail == b"" else tail
        return Branch(children, value)

    raise ValueError(f"unsupported trie RLP list length {len(decoded)}")


def load_root_from_rlp_store(
    fetch_rlp: Callable[[bytes], Optional[bytes]], state_root: bytes
) -> Optional[Node]:
    """Return the in-memory root node for ``state_root``, or ``None`` if empty trie."""
    if state_root == EMPTY_TRIE_ROOT:
        return None
    raw = fetch_rlp(state_root)
    if raw is None:
        raise ValueError("state root not found in store")
    return decode_trie_node(raw)


# Proof / API aliases
encode_node = rlp_encode_node
node_hash = trie_root_hash
