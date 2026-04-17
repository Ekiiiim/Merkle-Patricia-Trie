#!/usr/bin/env python3
"""
Compare inclusion proof payload sizes: Ethereum-style MPT vs sorted-leaf binary Merkle tree.

Run from repository root::

    python benchmark/run_proof_size.py
    python benchmark/run_proof_size.py --n 500 --seed 1

**MPT proof size** is the total number of bytes in the Ethereum-style inclusion payload:
each proof element is the full **RLP encoding** of one trie node (branch, extension, or
leaf) on the path from the state root to the leaf for ``keccak256(key)``; nodes that are
**embedded** in a parent (child reference shorter than 32 bytes) are not counted again as
their own element. The implementation exposes the same list via ``MerklePatriciaTrie.prove``;
verifiers walk it root-first together with the state root.

**Plain Merkle proof size** is the length of ``SortedLeafBinaryMerkleTree.membership_proof_bytes``:
the leaf commitment plus each 32-byte sibling hash on the sorted-leaf binary tree path.
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BENCH = Path(__file__).resolve().parent
# Repo root: ``mpt`` package. Benchmark dir: ``plain_merkle`` (works when cwd is not the repo).
for _p in (_ROOT, _BENCH):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from plain_merkle import SortedLeafBinaryMerkleTree
from mpt.trie import MerklePatriciaTrie


def _random_pairs(n: int, seed: int) -> list[tuple[bytes, bytes]]:
    rng = random.Random(seed)
    out: list[tuple[bytes, bytes]] = []
    seen: set[bytes] = set()
    while len(out) < n:
        k = f"k{rng.randint(0, 10**9)}".encode()
        if k in seen:
            continue
        seen.add(k)
        v = f"v{rng.randint(0, 10**6)}".encode()
        out.append((k, v))
    return out


def _mpt_proof_bytes(trie: MerklePatriciaTrie, key: bytes) -> int:
    """Total proof bytes: sum of lengths of standalone path-node RLP blobs (see module doc)."""
    proved = trie.prove(key)
    if proved is None:
        return -1
    _val, nodes = proved
    return sum(len(x) for x in nodes)


def collect_proof_sizes(
    n: int, seed: int
) -> tuple[list[int], list[int], bytes, bytes]:
    """
    Build one random ``n``-key dataset (``seed``), insert into MPT and plain tree,
    return ``(mpt_sizes, plain_sizes, plain_merkle_root, mpt_state_root)``.
    """
    pairs = _random_pairs(n, seed)
    keys = [k for k, _ in pairs]

    trie = MerklePatriciaTrie()
    for k, v in pairs:
        trie.insert(k, v)

    mt = SortedLeafBinaryMerkleTree(pairs)

    mpt_sizes: list[int] = []
    plain_sizes: list[int] = []
    for k in keys:
        mpt_sizes.append(_mpt_proof_bytes(trie, k))
        blob, _n = mt.membership_proof_bytes(k)
        plain_sizes.append(len(blob))

    if any(s < 0 for s in mpt_sizes):
        raise RuntimeError("internal error: missing MPT proof for inserted key")
    return mpt_sizes, plain_sizes, mt.root, trie.state_root()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n", type=int, default=64, help="number of distinct keys (default 64)")
    p.add_argument("--seed", type=int, default=0, help="RNG seed for synthetic keys")
    args = p.parse_args()

    mpt_sizes, plain_sizes, plain_root, mpt_root = collect_proof_sizes(args.n, args.seed)

    print("Proof size benchmark (same key/value set)")
    print(f"  keys: {args.n}  seed: {args.seed}")
    print(f"  plain Merkle root (32 B): {plain_root.hex()}")
    print(f"  MPT state root (32 B):    {mpt_root.hex()}")
    print()
    print("MPT: sum of |RLP(node)| over path nodes sent as separate proof elements")
    print("     (Ethereum embedding rule: short child RLP inside parent is not duplicated).")
    print("Plain: leaf commitment + each 32-byte sibling hash on the binary Merkle path.")
    print()
    print(f"{'metric':<22} {'MPT (bytes)':>14} {'plain (bytes)':>16}")
    print("-" * 54)
    for label, xs, ys in (
        ("mean", mpt_sizes, plain_sizes),
        ("median", mpt_sizes, plain_sizes),
        ("min", mpt_sizes, plain_sizes),
        ("max", mpt_sizes, plain_sizes),
    ):
        if label == "mean":
            a, b = statistics.mean(xs), statistics.mean(ys)
        elif label == "median":
            a, b = statistics.median(xs), statistics.median(ys)
        elif label == "min":
            a, b = min(xs), min(ys)
        else:
            a, b = max(xs), max(ys)
        print(f"{label:<22} {a:>14.1f} {b:>16.1f}")

    ratio = statistics.mean(mpt_sizes) / statistics.mean(plain_sizes) if plain_sizes else 0.0
    print()
    print(f"  mean size ratio (MPT / plain): {ratio:.2f}x")


if __name__ == "__main__":
    main()
