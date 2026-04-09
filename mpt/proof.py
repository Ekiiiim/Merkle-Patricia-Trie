"""Ethereum-style MPT inclusion proof verification (RLP nodes + embed ref rule)."""

from __future__ import annotations

import rlp

from mpt.constants import keccak256
from mpt.ethereum import decode_hex_prefix, ref_matches_embedded
from mpt.nibbles import key_to_nibbles


def verify_inclusion(
    state_root: bytes, key: bytes, value: bytes, proof: list[bytes]
) -> bool:
    """
    ``proof`` is **root-first**: ``proof[0]`` is RLP(root). Further elements are only
    RLP blobs for children reached via **32-byte hashed** refs. If a child ref is an
    **embedded** RLP (``len(ref) < 32``), that blob is read from ``ref`` itself — no
    separate proof entry (matches ``MerklePatriciaTrie.prove``).

    ``state_root`` is ``keccak256(RLP(root_node))`` (``EMPTY_TRIE_ROOT`` if empty).
    """
    if not proof:
        return False
    if keccak256(proof[0]) != state_root:
        return False

    rem = key_to_nibbles(key)
    i = 0
    raw = proof[i]
    i += 1

    while True:
        try:
            node = rlp.decode(raw)
        except rlp.DecodingError:
            return False

        if not isinstance(node, list):
            return False

        if len(node) == 2:
            if not isinstance(node[0], bytes) or not isinstance(node[1], bytes):
                return False
            nibbles, is_leaf = decode_hex_prefix(node[0])
            if is_leaf:
                return nibbles == rem and node[1] == value

            pl = len(nibbles)
            if len(rem) < pl or tuple(rem[:pl]) != nibbles:
                return False
            rem = rem[pl:]
            ref = node[1]
            if len(ref) < 32:
                nxt = ref
            else:
                if i >= len(proof):
                    return False
                nxt = proof[i]
                i += 1
            if not ref_matches_embedded(ref, nxt):
                return False
            raw = nxt
            continue

        if len(node) == 17:
            # pyrlp returns ``bytes`` for byte strings; reject other shapes.
            for slot in node:
                if not isinstance(slot, bytes):
                    return False
            if len(rem) == 0:
                return node[16] == value

            n = rem[0]
            rem = rem[1:]
            ref = node[n]
            if not ref:
                return False
            if len(ref) < 32:
                nxt = ref
            else:
                if i >= len(proof):
                    return False
                nxt = proof[i]
                i += 1
            if not ref_matches_embedded(ref, nxt):
                return False
            raw = nxt
            continue

        return False
