"""Persist / restore MPT via KV store (memory; SQLite persistent)."""

from __future__ import annotations

import pytest
from pathlib import Path

from mpt import MerklePatriciaTrie, verify_inclusion
from mpt.constants import EMPTY_TRIE_ROOT
from mpt.storage.memory import MemoryKVStore
from mpt.store import commit_trie, load_trie, load_trie_from_head, persist_trie


def test_persist_load_roundtrip() -> None:
    t = MerklePatriciaTrie()
    t.insert(b"alice", b"100")
    t.insert(b"bob", b"200")
    sr = t.state_root()
    kv = MemoryKVStore()
    persist_trie(kv, t.root)
    t2 = load_trie(kv, sr)
    assert t2.lookup(b"alice") == b"100"
    assert t2.lookup(b"bob") == b"200"
    assert t2.state_root() == sr


def test_commit_head_reload() -> None:
    kv = MemoryKVStore()
    t = MerklePatriciaTrie()
    t.insert(b"k", b"v")
    commit_trie(kv, t)
    t2 = load_trie_from_head(kv)
    assert t2.lookup(b"k") == b"v"


def test_empty_trie_persist_head() -> None:
    kv = MemoryKVStore()
    t = MerklePatriciaTrie()
    commit_trie(kv, t)
    t2 = load_trie_from_head(kv)
    assert t2.state_root() == EMPTY_TRIE_ROOT
    assert t2.lookup(b"x") is None


def test_proof_valid_after_load() -> None:
    t = MerklePatriciaTrie()
    t.insert(b"k", b"v")
    kv = MemoryKVStore()
    sr = persist_trie(kv, t.root)
    t2 = load_trie(kv, sr)
    p = t2.prove(b"k")
    assert p is not None
    val, proof = p
    assert verify_inclusion(sr, b"k", val, proof)

def test_sqlite_roundtrip(tmp_path: str = "./db") -> None:
    from mpt.persistent import PersistentMPT

    path = str(Path(tmp_path) / "test_mpt.db")
    
    with PersistentMPT(path) as db:
        db.insert(b"a", b"1")
        db.insert(b"b", b"2")
        r1 = db.commit()

    with PersistentMPT(path) as db2:
        assert db2.lookup(b"a") == b"1"
        assert db2.lookup(b"b") == b"2"
        assert db2.state_root() == r1

def test_sqlite_roundtrip2(tmp_path: str = "./db") -> None:
    # W/O write, just read
    from mpt.persistent import PersistentMPT

    print(f'tmp_path = {tmp_path}')

    path = str(Path(tmp_path) / "test_mpt.db")
    

    with PersistentMPT(path) as db2:
        assert db2.lookup(b"a") == b"1"
        assert db2.lookup(b"b") == b"2"

def test_large_random_dataset(tmp_path: str = './db') -> None:
    import random
    import string
    import time
    from mpt.persistent import PersistentMPT

    path = str(Path(tmp_path) / "stress.db")
    
    data = {}
    for _ in range(10000):
        k = "".join(random.choices(string.ascii_lowercase, k=20)).encode()
        v = str(random.randint(1, 1000000)).encode()
        data[k] = v

    insert_time = commit_time = 0.0
    with PersistentMPT(path) as db:
        start_time = time.time()
        for k, v in data.items():
            db.insert(k, v)
        end_time = time.time()

        insert_time += end_time - start_time

        start_time = time.time()
        db.commit()
        end_time = time.time()

        commit_time += end_time - start_time

    lookup_time = 0

    start_time = time.time()
    with PersistentMPT(path) as db2:
        for k, v in data.items():
            assert db2.lookup(k) == v
    end_time = time.time()
    lookup_time += end_time - start_time

    print(f'insert_time = {insert_time}, commit_time = {commit_time}, lookup_time = {lookup_time}')
    return



# if __name__ == "__main__":
#     # test_persist_load_roundtrip()
#     # test_sqlite_roundtrip("./db")
#     test_large_random_dataset("./db")
