"""Merkle Patricia Trie inclusion proof verification."""

from __future__ import annotations

from mpt.constants import EMPTY_SUBTREE_HASH, HASH_LEN, h
from mpt.nibbles import key_to_nibbles
from mpt.nodes import unpack_nibbles


def verify_inclusion(
    state_root: bytes, key: bytes, value: bytes, proof: list[bytes]
) -> bool:
    """
    Check that `proof` witnesses `key -> value` under `state_root`.
    Proof nodes are canonical wire encodings (same as `encode_node`).
    """
    if not proof:
        return False
    if h(proof[0]) != state_root:
        return False
    rem = key_to_nibbles(key)
    i = 0
    body = proof[i]
    i += 1

    while True:
        tag = body[0:1]
        if tag == b"L":
            nibbles, pos = unpack_nibbles(body, 1)
            if pos + 4 > len(body):
                return False
            vl = int.from_bytes(body[pos : pos + 4], "big")
            pos += 4
            if pos + vl != len(body):
                return False
            got = body[pos : pos + vl]
            return nibbles == rem and got == value

        if tag == b"E":
            nibbles, pos = unpack_nibbles(body, 1)
            if pos + HASH_LEN != len(body):
                return False
            child_hash = body[pos : pos + HASH_LEN]
            pl = len(nibbles)
            if len(rem) < pl or tuple(rem[:pl]) != nibbles:
                return False
            rem = rem[pl:]
            if i >= len(proof):
                return False
            if h(proof[i]) != child_hash:
                return False
            body = proof[i]
            i += 1
            continue

        if tag == b"B":
            pos = 1
            slots: list[bytes] = []
            for _ in range(16):
                if pos + HASH_LEN > len(body):
                    return False
                slots.append(body[pos : pos + HASH_LEN])
                pos += HASH_LEN
            if pos >= len(body):
                return False
            flag = body[pos]
            pos += 1
            term_val: bytes | None
            if flag == 0:
                term_val = None
            elif flag == 1:
                if pos + 4 > len(body):
                    return False
                vl = int.from_bytes(body[pos : pos + 4], "big")
                pos += 4
                if pos + vl != len(body):
                    return False
                term_val = body[pos : pos + vl]
            else:
                return False

            if len(rem) == 0:
                return term_val == value

            n = rem[0]
            rem = rem[1:]
            need = slots[n]
            if need == EMPTY_SUBTREE_HASH:
                return False
            if i >= len(proof):
                return False
            if h(proof[i]) != need:
                return False
            body = proof[i]
            i += 1
            continue

        return False
