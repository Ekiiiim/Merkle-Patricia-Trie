"""Minimal plain (insertion-order) binary Merkle tree (Keccak-256) for benchmarks."""

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


class PlainBinaryMerkleTree:
    """
    Complete binary tree over ``next_pow2(n)`` leaves.

    * Real leaves: ``keccak256(b'\\x00leaf\\x00' + key + b'\\x00' + value)`` in **input order**
      (order of first appearance of each key in the constructor list; later values overwrite).
    * Padding leaves: deterministic dummy hashes so ``n`` need not be a power of two.
    """

    __slots__ = ("pairs", "leaf_index", "layers")

    def __init__(self, pairs: list[tuple[bytes, bytes]]) -> None:
        if not pairs:
            raise ValueError("need at least one (key, value) pair")
        last: dict[bytes, bytes] = {}
        order: list[bytes] = []
        for k, v in pairs:
            if k not in last:
                order.append(k)
            last[k] = v
        self.pairs = [(k, last[k]) for k in order]
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

    def lookup(self, key: bytes) -> bytes:
        """Return the stored value for ``key`` (O(1) via ``leaf_index`` + leaf list)."""
        if key not in self.leaf_index:
            raise KeyError(key)
        return self.pairs[self.leaf_index[key]][1]

    def lookup_without_leaf_index(self, key: bytes) -> bytes:
        """
        Find ``key`` by scanning the ordered leaf preimage list only (no ``leaf_index``).

        Models retrieval when you commit to leaves with a Merkle root but do not keep a
        key→position map: worst-case O(number of real leaves) string compares per query.
        """
        for k, v in self.pairs:
            if k == key:
                return v
        raise KeyError(key)

    def membership_proof_bytes(self, key: bytes) -> tuple[bytes, int]:
        """
        Return (concatenated proof bytes, number of hashes).

        Proof = leaf hash + each sibling along the path to the root (standard binary
        Merkle audit path; verifier is assumed to know root and leaf ordering).
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
