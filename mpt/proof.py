"""Ethereum-style MPT inclusion proof verification (RLP nodes + embed ref rule)."""

from __future__ import annotations

from typing import Any

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

    # Ethereum state trie uses keccak256(key) as the trie path material.
    rem = key_to_nibbles(keccak256(key))
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


def verify_inclusion_trace(
    state_root: bytes, key: bytes, value: bytes, proof: list[bytes]
) -> tuple[bool, list[dict[str, Any]]]:
    """
    Same rules as :func:`verify_inclusion`, but record human-readable steps for demos.

    Each step dict has at least ``title`` and ``detail`` (strings). Optional keys:
    ``ok`` (bool), ``hash_hex``, ``proof_index``.
    """
    steps: list[dict[str, Any]] = []

    def add(title: str, detail: str, **extra: Any) -> None:
        row: dict[str, Any] = {"title": title, "detail": detail}
        row.update(extra)
        steps.append(row)

    if not proof:
        add("Stopped", "Proof is empty - cannot verify.", ok=False)
        return False, steps

    rh = keccak256(proof[0])
    add(
        "State root from proof[0]",
        "state_root must equal keccak256(RLP(root_node)).",
        hash_hex=rh.hex(),
        expected_state_root_hex=state_root.hex(),
        ok=rh == state_root,
    )
    if rh != state_root:
        add("Failed", "keccak256(proof[0]) does not match the claimed state root.", ok=False)
        return False, steps

    # Ethereum state trie uses keccak256(key) as the trie path material.
    rem = key_to_nibbles(keccak256(key))
    rem_hex = bytes(rem).hex()
    add(
        "Key path (nibbles)",
        f"Key expanded to {len(rem)} nibbles (hex pairs).",
        n_nibbles=len(rem),
        key_path_nibbles_hex=rem_hex,
        detail_hexes=[{"label": "path", "hex": rem_hex}],
    )

    i = 0
    raw = proof[i]
    i += 1
    depth = 0

    while True:
        cur_hash_hex = keccak256(raw).hex()
        try:
            node = rlp.decode(raw)
        except rlp.DecodingError as e:
            add("RLP decode error", str(e), ok=False)
            return False, steps

        if not isinstance(node, list):
            add("Invalid node", "Decoded RLP is not a list.", ok=False)
            return False, steps

        if len(node) == 2:
            if not isinstance(node[0], bytes) or not isinstance(node[1], bytes):
                add("Invalid extension/leaf", "Expected two byte strings.", ok=False)
                return False, steps
            nibbles, is_leaf = decode_hex_prefix(node[0])
            path_hex = bytes(nibbles).hex()
            if is_leaf:
                add(
                    f"Depth {depth}: leaf node",
                    "Compact path nibbles (hex); compare to remaining path.",
                    depth=depth,
                    node_kind="leaf",
                    node_hash_hex=cur_hash_hex,
                    detail_hexes=[{"label": "path", "hex": path_hex}],
                )
                match = nibbles == tuple(rem) and node[1] == value
                add(
                    "Leaf check",
                    "Remaining nibbles must equal leaf path and value must match.",
                    ok=match,
                )
                if match:
                    add(
                        "Verification succeeded",
                        "Inclusion proof is valid for this key, value, and state root.",
                        ok=True,
                    )
                return match, steps

            pl = len(nibbles)
            add(
                f"Depth {depth}: extension node",
                f"Shared path ({pl} nibbles, hex); descend if key has this prefix.",
                depth=depth,
                node_kind="extension",
                node_hash_hex=cur_hash_hex,
                detail_hexes=[{"label": "path", "hex": path_hex}],
            )
            if len(rem) < pl or tuple(rem[:pl]) != nibbles:
                add(
                    "Path mismatch",
                    "Key does not contain extension path - proof invalid for this key.",
                    ok=False,
                )
                return False, steps
            rem = rem[pl:]
            ref = node[1]
            if len(ref) < 32:
                nxt = ref
                add(
                    "Embedded child",
                    "Child ref is short (<32 bytes): next node RLP is embedded in ref (no extra proof slot).",
                    ok=True,
                )
            else:
                if i >= len(proof):
                    add("Missing proof node", "Expected another proof entry for hashed ref.", ok=False)
                    return False, steps
                nxt = proof[i]
                add(
                    "Hashed child",
                    f"Load proof[{i}] as RLP of child (ref is 32-byte keccak digest).",
                    proof_index=i,
                    ok=True,
                )
                i += 1
            if not ref_matches_embedded(ref, nxt):
                add(
                    "Ref mismatch",
                    "Child blob does not match embedded/hash rule for this ref.",
                    ok=False,
                )
                return False, steps
            raw = nxt
            depth += 1
            continue

        if len(node) == 17:
            for slot in node:
                if not isinstance(slot, bytes):
                    add("Invalid branch", "Branch slots must be byte strings.", ok=False)
                    return False, steps
            if len(rem) == 0:
                add(
                    f"Depth {depth}: branch (terminal value)",
                    "Key exhausted at branch: value is in slot 16.",
                depth=depth,
                node_kind="branch",
                node_hash_hex=cur_hash_hex,
                )
                ok = node[16] == value
                add(
                    "Terminal value check",
                    "Slot 16 must equal claimed value (hex).",
                    ok=ok,
                    detail_hexes=[{"label": "value", "hex": value.hex()}],
                )
                if ok:
                    add(
                        "Verification succeeded",
                        "Inclusion proof is valid for this key, value, and state root.",
                        ok=True,
                    )
                return ok, steps

            n = rem[0]
            rem = rem[1:]
            add(
                f"Depth {depth}: branch node",
                f"Next nibble {n:x} - follow child slot {n:x}.",
                depth=depth,
                node_kind="branch",
                node_hash_hex=cur_hash_hex,
            )
            ref = node[n]
            if not ref:
                add("Empty child", "Branch child slot is empty - cannot prove this key.", ok=False)
                return False, steps
            if len(ref) < 32:
                nxt = ref
                add(
                    "Embedded child",
                    "Child RLP embedded in branch ref (<32 bytes).",
                    ok=True,
                )
            else:
                if i >= len(proof):
                    add("Missing proof node", "Expected proof entry for hashed child.", ok=False)
                    return False, steps
                nxt = proof[i]
                add(
                    "Hashed child",
                    f"Load proof[{i}] for child node.",
                    proof_index=i,
                    ok=True,
                )
                i += 1
            if not ref_matches_embedded(ref, nxt):
                add("Ref mismatch", "Child blob does not match ref.", ok=False)
                return False, steps
            raw = nxt
            depth += 1
            continue

        add("Unknown node shape", f"RLP list length {len(node)} is not 2 or 17.", ok=False)
        return False, steps
