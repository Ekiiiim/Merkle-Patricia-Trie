"""Trie operations and state root."""

from __future__ import annotations

from mpt import MerklePatriciaTrie, node_hash
from mpt.constants import EMPTY_SUBTREE_HASH, h


def test_empty_root() -> None:
    t = MerklePatriciaTrie()
    assert t.state_root() == EMPTY_SUBTREE_HASH


def test_insert_lookup_single() -> None:
    t = MerklePatriciaTrie()
    t.insert(b"foo", b"bar")
    assert t.lookup(b"foo") == b"bar"
    assert t.lookup(b"other") is None
    assert t.state_root() != EMPTY_SUBTREE_HASH


def test_insert_updates_value() -> None:
    t = MerklePatriciaTrie()
    t.insert(b"k", b"v1")
    r1 = t.state_root()
    t.insert(b"k", b"v2")
    assert t.lookup(b"k") == b"v2"
    assert t.state_root() != r1


def test_shared_prefix_keys() -> None:
    t = MerklePatriciaTrie()
    t.insert(b"\xab\xcd", b"1")
    t.insert(b"\xab\xef", b"2")
    assert t.lookup(b"\xab\xcd") == b"1"
    assert t.lookup(b"\xab\xef") == b"2"


def test_prefix_key_and_extension() -> None:
    t = MerklePatriciaTrie()
    t.insert(b"\x01\x02", b"long")
    t.insert(b"\x01", b"short")
    assert t.lookup(b"\x01\x02") == b"long"
    assert t.lookup(b"\x01") == b"short"


def test_delete() -> None:
    t = MerklePatriciaTrie()
    t.insert(b"a", b"1")
    t.insert(b"b", b"2")
    assert t.delete(b"a") is True
    assert t.lookup(b"a") is None
    assert t.lookup(b"b") == b"2"
    assert t.delete(b"a") is False


def test_delete_only_key_empties_trie() -> None:
    t = MerklePatriciaTrie()
    t.insert(b"x", b"y")
    assert t.delete(b"x") is True
    assert t.state_root() == EMPTY_SUBTREE_HASH


def test_root_stable_for_same_map() -> None:
    t1 = MerklePatriciaTrie()
    t1.insert(b"a", b"1")
    t1.insert(b"b", b"2")
    t2 = MerklePatriciaTrie()
    t2.insert(b"b", b"2")
    t2.insert(b"a", b"1")
    assert t1.state_root() == t2.state_root()


def test_prove_first_node_hashes_to_root() -> None:
    t = MerklePatriciaTrie()
    t.insert(b"k", b"v")
    p = t.prove(b"k")
    assert p is not None
    val, nodes = p
    assert val == b"v"
    assert nodes and h(nodes[0]) == node_hash(t.root)
