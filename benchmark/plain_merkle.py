"""Minimal sorted-leaf binary Merkle tree (Keccak-256) for proof-size comparison."""

from __future__ import annotations

from Crypto.Hash import keccak


def keccak256(data: bytes) -> bytes:
    h = keccak.new(digest_bits=256)
    h.update(data)
    return h.digest()


def _leaf_hash(key: bytes, value: bytes) -> bytes:
    """Domain-separated leaf commitment (not the same as MPT path semantics)."""
    return keccak256(b"\x00leaf\x00" + key + b"\x00" + value)


def _next_pow2(n: int) -> int:
    if n <= 1:
        return 1
    return 1 << (n - 1).bit_length()


def _padding_leaf(slot: int) -> bytes:
    return keccak256(b"\xffpad\x00" + slot.to_bytes(8, "big"))


class SortedLeafBinaryMerkleTree:
    """
    Complete binary tree over ``next_pow2(n)`` leaves.

    * Real leaves: ``keccak256(b'\\x00leaf\\x00' + key + b'\\x00' + value)`` in **key-sorted** order.
    * Padding leaves: deterministic dummy hashes so ``n`` need not be a power of two.
    """

    __slots__ = ("pairs", "leaf_index", "layers")

    def __init__(self, pairs: list[tuple[bytes, bytes]]) -> None:
        if not pairs:
            raise ValueError("need at least one (key, value) pair")
        uniq: dict[bytes, bytes] = {}
        for k, v in pairs:
            uniq[k] = v
        self.pairs = sorted(uniq.items(), key=lambda kv: kv[0])
        leaf_hashes = [_leaf_hash(k, v) for k, v in self.pairs]
        self.leaf_index: dict[bytes, int] = {k: i for i, (k, _) in enumerate(self.pairs)}
        cap = _next_pow2(len(leaf_hashes))
        pad_n = cap - len(leaf_hashes)
        for j in range(pad_n):
            leaf_hashes.append(_padding_leaf(j))
        self.layers: list[list[bytes]] = [leaf_hashes]
        cur = leaf_hashes
        while len(cur) > 1:
            nxt: list[bytes] = []
            for i in range(0, len(cur), 2):
                nxt.append(keccak256(cur[i] + cur[i + 1]))
            self.layers.append(nxt)
            cur = nxt

    @property
    def root(self) -> bytes:
        return self.layers[-1][0]

    def membership_proof_bytes(self, key: bytes) -> tuple[bytes, int]:
        """
        Return (concatenated proof bytes, number of hashes).

        Proof = leaf hash + each sibling along the path to the root (Ethereum-style
        audit path; verifier is assumed to know root and key ordering rule).
        """
        if key not in self.leaf_index:
            raise KeyError(key)
        idx = self.leaf_index[key]
        parts: list[bytes] = [self.layers[0][idx]]
        i = idx
        for level in range(len(self.layers) - 1):
            layer = self.layers[level]
            sib = layer[i ^ 1]
            parts.append(sib)
            i //= 2
        blob = b"".join(parts)
        return blob, len(parts)
