"""Inclusion proof generation and verification."""

from __future__ import annotations

from mpt import MerklePatriciaTrie, verify_inclusion, verify_inclusion_trace
from mpt.constants import keccak256


def test_proof_roundtrip_simple() -> None:
    t = MerklePatriciaTrie()
    t.insert(b"key", b"value")
    root = t.state_root()
    got = t.prove(b"key")
    assert got is not None
    val, proof = got
    assert verify_inclusion(root, b"key", val, proof)


def test_proof_branched_keys() -> None:
    t = MerklePatriciaTrie()
    for i in range(4):
        t.insert(bytes([i]), bytes([i, i]))
    root = t.state_root()
    for i in range(4):
        p = t.prove(bytes([i]))
        assert p is not None
        val, proof = p
        assert verify_inclusion(root, bytes([i]), val, proof)


def test_proof_fails_wrong_value() -> None:
    t = MerklePatriciaTrie()
    t.insert(b"k", b"v")
    root = t.state_root()
    p = t.prove(b"k")
    assert p is not None
    _, proof = p
    assert not verify_inclusion(root, b"k", b"other", proof)


def test_proof_missing_key() -> None:
    t = MerklePatriciaTrie()
    t.insert(b"a", b"1")
    assert t.prove(b"missing") is None


def test_proof_single_node_small_trie_still_verifies() -> None:
    """Small RLP roots still use keccak(root_rlp) as state_root; proof may be one blob."""
    t = MerklePatriciaTrie()
    t.insert(b"k", b"v")
    got = t.prove(b"k")
    assert got is not None
    val, proof = got
    assert len(proof) >= 1
    assert keccak256(proof[0]) == t.state_root()
    assert verify_inclusion(t.state_root(), b"k", val, proof)


def test_proof_fails_tampered_node() -> None:
    t = MerklePatriciaTrie()
    t.insert(b"k", b"v")
    root = t.state_root()
    p = t.prove(b"k")
    assert p is not None
    val, proof = p
    bad = list(proof)
    bad[-1] = bad[-1][:-1] + bytes([(bad[-1][-1] ^ 1) & 0xFF])
    assert not verify_inclusion(root, b"k", val, bad)


def test_verify_inclusion_trace_matches_verify() -> None:
    t = MerklePatriciaTrie()
    for key, val in [(b"alice", b"100"), (b"bob", b"200"), (b"alma", b"300")]:
        t.insert(key, val)
    root = t.state_root()
    for key in (b"alice", b"bob", b"alma"):
        p = t.prove(key)
        assert p is not None
        val, proof = p
        ok = verify_inclusion(root, key, val, proof)
        ok_t, steps = verify_inclusion_trace(root, key, val, proof)
        assert ok_t is ok
        assert len(steps) >= 2
