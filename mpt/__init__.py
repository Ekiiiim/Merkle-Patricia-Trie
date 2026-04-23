"""Merkle Patricia Trie (hexary): Ethereum-style RLP + Keccak-256."""

from mpt.constants import EMPTY_TRIE_ROOT, h, keccak256
from mpt.ethereum import (
    compact_encoding,
    decode_hex_prefix,
    decode_trie_node,
    encode_hex_prefix,
    encode_node,
    load_root_from_rlp_store,
    node_hash,
    path_encoding,
    rlp_encode_node,
    trie_root_hash,
)
from mpt.interfaces import TrieKVStore
from mpt.nibbles import common_prefix_length, key_to_nibbles, nibbles_to_bytes
from mpt.nodes import Branch, Extension, Leaf
from mpt.proof import verify_inclusion, verify_inclusion_trace
from mpt.storage.memory import MemoryKVStore
from mpt.storage.sqlite import SQLiteKVStore
from mpt.store import (
    MPT_HEAD_KEY,
    commit_trie,
    load_trie,
    load_trie_from_head,
    persist_trie,
)
from mpt.trie import MerklePatriciaTrie, snapshot_node
from mpt.visualize import evolution_to_dot, trie_to_dot, trie_to_graph, try_matplotlib_show

try:
    from mpt.persistent import PersistentMPT, open_persistent
except ModuleNotFoundError:
    PersistentMPT = None  # type: ignore[assignment]
    open_persistent = None  # type: ignore[assignment]

__all__ = [
    "Branch",
    "EMPTY_TRIE_ROOT",
    "Extension",
    "Leaf",
    "MPT_HEAD_KEY",
    "MemoryKVStore",
    "MerklePatriciaTrie",
    "SQLiteKVStore",
    "TrieKVStore",
    "common_prefix_length",
    "commit_trie",
    "compact_encoding",
    "decode_hex_prefix",
    "decode_trie_node",
    "encode_hex_prefix",
    "encode_node",
    "evolution_to_dot",
    "h",
    "key_to_nibbles",
    "keccak256",
    "load_root_from_rlp_store",
    "load_trie",
    "load_trie_from_head",
    "nibbles_to_bytes",
    "node_hash",
    "path_encoding",
    "persist_trie",
    "rlp_encode_node",
    "snapshot_node",
    "trie_root_hash",
    "trie_to_dot",
    "trie_to_graph",
    "try_matplotlib_show",
    "verify_inclusion",
    "verify_inclusion_trace",
]

if PersistentMPT is not None:
    __all__.append("PersistentMPT")
if open_persistent is not None:
    __all__.append("open_persistent")
