"""Persist and restore MPT nodes in a byte KV store (e.g. LevelDB, or in-memory dict)."""

from __future__ import annotations

from typing import MutableMapping, Optional, Protocol

from mpt.constants import keccak256
from mpt.ethereum import load_root_from_rlp_store, rlp_encode_node, trie_root_hash
from mpt.nodes import Branch, Extension, HashNode, Node
from mpt.trie import MerklePatriciaTrie
from mpt.interfaces import TrieKVStore


# Reserved key for last committed state root (32 bytes), separate from trie node hashes.
MPT_HEAD_KEY = b"mpt\x00head"


def persist_subtree(store: TrieKVStore, node: Node) -> None:
    """Recursively writes trie nodes to the persistent store.

    Following the Ethereum standard, only nodes whose RLP encoding is 32 bytes 
    or longer are stored as individual entries in the database (indexed by 
    their Keccak-256 hash). Shorter nodes are skipped here because they are 
    already 'embedded' within their parent nodes.

    Args:
        store: The KV store where nodes will be persisted.
        node: The root of the subtree to start persisting from.
    """
    # If it's already a HashNode, it's either already persisted or unchanged.
    if isinstance(node, HashNode):
        return
    
    raw = rlp_encode_node(node)
    
    # Ethereum Rule: Only nodes >= 32 bytes are indexed by hash in the database.
    if len(raw) >= 32:
        store.put(keccak256(raw), raw)
        
    # Recursively descend through the trie structure.
    if isinstance(node, Extension):
        persist_subtree(store, node.child)
    elif isinstance(node, Branch):
        for c in node.children:
            if c is not None:
                persist_subtree(store, c)


def persist_trie(store: TrieKVStore, root: Optional[Node]) -> bytes:
    """Persists the entire trie and returns its state root hash.

    This function ensures that the root node itself is always written to the 
    store, even if its RLP encoding is shorter than 32 bytes. This is 
    mandatory so that load_trie can always resolve the starting point 
    from a 32-byte state root.

    Args:
        store: The KV store to write nodes into.
        root: The root node of the trie to persist.

    Returns:
        The 32-byte Keccak-256 state root of the persisted trie.
    """
    state_root = trie_root_hash(root)
    if root is None:
        return state_root
        
    # Mandatory write of the root node to ensure the entry point is resolvable.
    store.put(state_root, rlp_encode_node(root))
    
    # Persist all eligible descendant nodes.
    persist_subtree(store, root)
    return state_root


def commit_trie(
    store: TrieKVStore, trie: MerklePatriciaTrie, *, write_head: bool = True
) -> bytes:
    """Finalizes the trie state and updates the persistence head.

    This is the high-level API used to save the current state of a trie. 
    It persists all modified nodes and optionally updates a special 
    'head' pointer (MPT_HEAD_KEY) to track the latest state root for 
    subsequent session restores.

    Args:
        store: The KV store used for persistence.
        trie: The MerklePatriciaTrie instance to be committed.
        write_head: If True, updates the `MPT_HEAD_KEY` in the store with 
            the new state root.

    Returns:
        bytes: The newly calculated 32-byte state root.
    """
    sr = persist_trie(store, trie.root)
    if write_head:
        # Record the latest state root as the current 'head' of the trie.
        store.put(MPT_HEAD_KEY, sr)
    return sr


def load_trie(store: TrieKVStore, state_root: bytes) -> MerklePatriciaTrie:
    """Rebuilds an in-memory trie structure from a persisted state root.

    This function serves as a factory for restoring a trie from a specific 
    point in history. It uses the provided state root hash to fetch the 
    root node from the store and initializes a MerklePatriciaTrie object.

    Args:
        store: The KV store containing the RLP-encoded trie nodes.
        state_root: The 32-byte Keccak hash of the trie's root node.

    Returns:
        A trie instance with its root node loaded (or 
            a HashNode placeholder for lazy loading).
    """
    
    root = load_root_from_rlp_store(store.get, state_root)
    
    return MerklePatriciaTrie(root=root, db=store)


def load_trie_from_head(store: TrieKVStore) -> MerklePatriciaTrie:
    """Loads the most recently committed version of the trie using the head pointer.

    This function attempts to find the special 'mpt\x00head' key in the store 
    which tracks the latest state root hash. If no head is found or the store 
    represents an empty state, it returns a fresh, empty trie.

    Args:
        store: The KV store to query for the head pointer and node data.

    Returns:
        The restored trie at the latest committed state, 
            or an empty trie if no valid head exists.
    """
    from mpt.constants import EMPTY_TRIE_ROOT

    
    head = store.get(MPT_HEAD_KEY)
    
    # Safety check: If there is not head's record or the length of the hash is incorrect, return an empty MPT.
    if head is None or len(head) != 32:
        return MerklePatriciaTrie(db=store)
    
    if head == EMPTY_TRIE_ROOT:
        return MerklePatriciaTrie(db=store)
        
    return load_trie(store, head)
