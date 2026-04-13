"""Hexary Merkle Patricia Trie: insert, lookup, delete, state root.

Structural normalization uses ``_collapse_node`` only on nodes returned along the
edited path (O(key length)), not a full trie scan after each operation.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Optional

from mpt.constants import keccak256
from mpt.nibbles import common_prefix_length, key_to_nibbles
from mpt.ethereum import embed_ref, encode_node, node_hash, decode_trie_node
from mpt.nodes import Branch, Extension, Leaf, HashNode, Node
from mpt.interfaces import TrieKVStore

def snapshot_node(node: Optional[Node], db: Optional[TrieKVStore] = None) -> Optional[Node]:
    """Creates a recursive deep copy of a trie node and its descendants.

    This function clones the node structure to ensure thlsat modifications to 
    the new tree do not affect the original.
    It is to visualize the MPT.

    Args:
        node: The root of the node subtree to be copied.
        db: Optional database for resolving the child if it's a HashNode. Default is None.

    Returns:
        A new node instance that is structurally identical 
            to the input, or None if the input was None.

    Raises:
        TypeError: If the provided node is not a recognized Node type 
            (Leaf, Extension, Branch, or HashNode).
    """

    node = _resolve(node, db)

    if node is None:
        return None

    if isinstance(node, Leaf):
        return Leaf(node.path, node.value)
    if isinstance(node, Extension):
        return Extension(node.path, snapshot_node(node.child, db))
    if isinstance(node, Branch):
        # Recursion
        return Branch([snapshot_node(c, db) for c in node.children], node.value)
    raise TypeError(node)


def _empty_branch() -> Branch:
    """Create an empty branch node that is with 16 null children.
    Returns:
        An empty branch node.
    """
    return Branch([None] * 16, None)


def _prepend_nibble(nib: int, child: Node, db: Optional[TrieKVStore] = None) -> Optional[Node]:
    """Prepends a nibble to a node, merging paths if possible.

    This helper function is used during trie transformation (e.g., after deletion)
    to maintain the canonical structure of the MPT. If the child is already a 
    path-based node (Leaf or Extension), the nibble is merged into its existing 
    path to keep the trie compact. Otherwise, a new Extension node is created.

    Args:
        nib: The 4-bit nibble (0-15) to prepend.
        child: The child node which will be preceded by the nibble.
        db: Optional database for resolving the child if it's a HashNode. Default is None.

    Returns:
        A new Leaf or Extension node with the updated path. 
            Returns None if the child is None.
    """
    child = _resolve(child, db)
    if child is None:
        return None
    if isinstance(child, Leaf):
        # Collapse (a.k.a Merge) path: Prepend nibble to the leaf's existing path.
        return Leaf((nib,) + child.path, child.value)
    if isinstance(child, Extension):
        # Collapse (a.k.a Merge) path: Prepend with existing extension to maintain tree compactness.
        return Extension((nib,) + child.path, child.child)
    # Create a new Extension if the child is a Branch (cannot be merged).
    return Extension((nib,), child)


def _merge_extension_path(prefix: tuple[int, ...], child: Node, db: Optional[TrieKVStore] = None) -> Node:
    """Merges a prefix path with a child node, collapsing (a.k.a merging) nodes if possible.

    This helper function ensures the trie remains in its canonical compressed form. 
    If the child is a path-based node (Leaf or Extension), the prefix is 
    prepended to the child's existing path, effectively merging two nodes 
    into one. If the child is a Branch, a new Extension node is created to 
    house the prefix.

    Args:
        prefix: A tuple of nibbles to be prepended.
        child: The child node to merge with the prefix.
        db: Optional database backend to resolve the child if it's a HashNode. Default is None.

    Returns:
        A new Leaf or Extension node with the combined path, 
            or None if the resolved child is None.
    """
    child = _resolve(child, db)
    if isinstance(child, Leaf):
        return Leaf(prefix + child.path, child.value)
    if isinstance(child, Extension):
        return Extension(prefix + child.path, child.child)
    return Extension(prefix, child)


def _collapse_node(node: Optional[Node], db: Optional[TrieKVStore] = None) -> Optional[Node]:
    """Normalizes a node by collapsing (a.k.a. merging) redundant structures along the path.

    This function ensures the trie maintains its compressed form. It handles
    three cases:
    1. Extension simplification: Merges nested extensions or leaves.
    2. Branch elimination: If a Branch has no value and only one child, it 
       collapses into an Extension or Leaf.
    3. Empty Branch: If a Branch has no children and no value, it's removed.

    This operation is $O(\text{depth})$ as it assumes child subtrees are already 
    normalized, typically called during the unwinding phase of recursive 
    updates.

    Args:
        node: The node to normalize.
        db: Optional database backend to resolve HashNodes. Default is None.

    Returns:
       The normalized/collapsed (a.k.a merged) node, or None if the 
            subtree becomes empty.

    Raises:
        TypeError: If the node is not a recognized MPT Node type.
    """
    node = _resolve(node, db)
    if node is None:
        return None
    if isinstance(node, Leaf):
        return node
    if isinstance(node, Extension):
        c = _collapse_node(node.child, db)
        if c is None:
            return None
        return _merge_extension_path(node.path, c, db)
    if isinstance(node, Branch):
        new_children = list(node.children)
        nchildren = sum(1 for x in new_children if x is not None)
        if node.value is not None:
            return Branch(new_children, node.value)
        if nchildren == 0:
            return None
        if nchildren == 1:
            for i, c in enumerate(new_children):
                if c is not None:
                    return _prepend_nibble(i, c, db)
            return None
        return Branch(new_children, None)
    raise TypeError(node)


def _insert(node: Optional[Node], key: tuple[int, ...], val: bytes, db: Optional[TrieKVStore] = None) -> Node:
    """Recursively inserts a key-value pair into the trie.

    This is the main entry point for the trie's insertion logic. It resolves 
    placeholder HashNodes and dispatches the operation to type-specific handlers 
    (Leaf, Extension, or Branch). 

    After the insertion, it ensures the resulting subtree is normalized 
    (collapsed, a.k.a. merged) to maintain the MPT's structural integrity 
    and canonical form.

    Args:
        node: The current root of the subtree where the insertion occurs.
        key: The remaining path (as a tuple of nibbles) to be inserted.
        val: The value to be associated with the key.
        db: Optional database backend for resolving nodes. Default is None.

    Returns:
        The new root of the updated and collapsed subtree.

    Raises:
        TypeError: If an unrecognized node type is encountered.
    """
    node = _resolve(node, db)
    if node is None:
        return _collapse_node(Leaf(key, val), db)
    if isinstance(node, Leaf):
        return _collapse_node(_insert_into_leaf(node, key, val, db), db)
    if isinstance(node, Extension):
        return _collapse_node(_insert_into_extension(node, key, val, db), db)
    if isinstance(node, Branch):
        return _collapse_node(_insert_into_branch(node, key, val, db), db)
    raise TypeError(node)


def _insert_into_leaf(leaf: Leaf, key: tuple[int, ...], val: bytes, db: Optional[TrieKVStore] = None) -> Node:
    """Handles insertion logic when the current node is a Leaf.

    This function compares the existing leaf's path with the insertion key and 
    performs one of the following structural transformations:
    1. Update: If paths match exactly, it returns an updated Leaf.
    2. Extension/Branch Split: If one path is a prefix of the other, 
       it creates a Branch to handle the divergence.
    3. Internal Divergence: If the paths diverge mid-way, it creates a 
       common Extension (if applicable) followed by a Branch to split the 
       two paths.

    Args:
        leaf: The existing Leaf node.
        key: The remaining nibbles of the key being inserted.
        val: The value to be associated with the key.
        db: Optional database backend for recursive insertions. Default is None.

    Returns:
        The new subtree root (could be a Leaf, Extension, or Branch).
    """

    lp = leaf.path
    if lp == key:
        return Leaf(lp, val)
    cpl = common_prefix_length(lp, key)

    # Case 1: Strict prefix of existing leaf path: longer key extends `lp`.
    if cpl == len(lp) < len(key):
        suffix = tuple(key[cpl:])
        nxt = suffix[0]
        children = [None] * 16
        children[nxt] = _insert(None, tuple(suffix[1:]), val, db)
        br = Branch(children, leaf.value)
        if cpl == 0:
            return br
        return Extension(tuple(lp[:cpl]), br)

    # Case 2: New key is a strict prefix of the existing leaf path.
    if cpl == len(key) < len(lp):
        nxt = lp[cpl]
        children = [None] * 16
        children[nxt] = _insert(None, tuple(lp[cpl + 1 :]), leaf.value, db)
        br = Branch(children, val)
        if cpl == 0:
            return br
        return Extension(tuple(key[:cpl]), br)

    # Case 3: Internal divergence
    common = lp[:cpl]
    br = _empty_branch()
    a, b = lp[cpl], key[cpl]
    children = list(br.children)
    children[a] = _insert(None, tuple(lp[cpl + 1 :]), leaf.value, db)
    children[b] = _insert(None, tuple(key[cpl + 1 :]), val, db)
    br = Branch(children, None)
    if cpl == 0:
        return br
    return Extension(common, br)


def _insert_into_extension(ext: Extension, key: tuple[int, ...], val: bytes, db: Optional[TrieKVStore] = None) -> Node:
    """Handles insertion logic when the current node is an Extension.

    This function compares the extension's path with the insertion key and 
    decides whether to descend further or split the extension. It covers 
    two scenarios:
    1. Pass-through: The key contains the entire extension path as a 
       prefix. The insertion continues recursively into the child node.
    2. Structural Split: The key diverges from the extension path. 
       A new Branch is created at the divergence point, potentially 
       re-wrapping the remaining extension path.

    Args:
        ext: The existing Extension node.
        key: The remaining nibbles of the key being inserted.
        val: The value to be associated with the key.
        db: Optional database backend for recursive insertions and resolution. Default is None.

    Returns:
        The updated subtree root, typically a modified Extension 
            or a new Branch structure.
    """
    ep = ext.path
    cpl = common_prefix_length(ep, key)

    # Case 1: Extension path is a complete prefix of the key.
    # We simply "pass through" this extension and insert into the child.
    if cpl == len(ep):
        new_child = _insert(ext.child, tuple(key[cpl:]), val, db)
        return Extension(ep, new_child)

    # Case 2: Divergence - The extension path must be split.
    # Example: Extension path 'abc' meets key 'abd'. 
    # 'ab' becomes a common Extension, 'c' and 'd' become children of a Branch.
    common = ep[:cpl]
    tail_e = ep[cpl]
    tail_k = key[cpl]
    rest_e = tuple(ep[cpl + 1 :])
    rest_k = tuple(key[cpl + 1 :])
    br = _empty_branch()
    children = list(br.children)

    # Handle the existing extension's remnant
    # If rest_e is empty, the child of the new branch is the old child directly.
    # Otherwise, we create a shorter Extension for the remaining path.
    children[tail_e] = ext.child if not rest_e else Extension(rest_e, ext.child)

    # Handle the new key's remnant
    children[tail_k] = _insert(None, rest_k, val, db)
    br = Branch(children, None)

    # If there is no common prefix, the new Branch becomes the root of this subtree.
    if cpl == 0:
        return br
    return Extension(common, br)


def _insert_into_branch(br: Branch, key: tuple[int, ...], val: bytes, db: Optional[TrieKVStore] = None) -> Branch:
    """Handles insertion logic when the current node is a Branch.

    A Branch node represents a 16-way junction (0-f). This function either:
    1. Updates the node value: If the key is exhausted (empty), the 
       provided value is associated with this Branch itself.
    2. Recursively descends: If the key still has nibbles, it follows 
       the path by delegating the insertion to the child at index `key[0]`.

    Args:
        br: The existing Branch node.
        key: The remaining nibbles of the key being inserted.
        val: The value to be associated with the key.
        db: Optional database backend for recursive insertions. Default is None.

    Returns:
        A new Branch node with the updated value or modified child list.
    """
    # Case 1: The key ends exactly at this branch.
    # We update the branch's own value and keep the existing children.
    if len(key) == 0:
        return Branch(list(br.children), val)

    # Case 2: The key continues through one of the 16 possible paths.
    children = list(br.children)
    idx = key[0]

    # Delegate the remaining path (key[1:]) to the appropriate child.
    # Note: _insert will handle resolving the child if it's currently a HashNode.
    children[idx] = _insert(children[idx], tuple(key[1:]), val, db)

    # Return a new branch with the updated child, preserving the branch's original value.
    return Branch(children, br.value)


def _get(node: Optional[Node], key: tuple[int, ...], db: Optional[TrieKVStore] = None) -> Optional[bytes]:
    """Recursively retrieves the value associated with a key in the trie.

    This function traverses the trie by matching the key's nibbles against node 
    paths and branch indices. It handles lazy-loading by resolving HashNodes 
    from the database as needed during the search.

    Args:
        node: The current root of the subtree to search within.
        key: The remaining path (as a tuple of nibbles) to look up.
        db: Optional database backend for resolving encountered HashNodes. Default is None.

    Returns:
        The retrieved value if the key exists; 
            None if the path is not found in the trie.

    Raises:
        TypeError: If an unrecognized node type is encountered during traversal.
    """

    # Ensure the node is loaded into memory if it's currently a HashNode stub.
    node = _resolve(node, db)
    
    # Case 1: Reached a dead end in the trie.
    if node is None:
        return None
    
    # Case 2: Encountered a Leaf.
    # The value is found only if the remaining key exactly matches the leaf's path.
    if isinstance(node, Leaf):
        return node.value if node.path == key else None
    
    # Case 3: Encountered an Extension.
    # We must match the full extension path before descending to its child.
    if isinstance(node, Extension):
        pl = len(node.path)
        # If the key is too short or the prefix doesn't match, the key doesn't exist.
        if len(key) < pl or tuple(key[:pl]) != node.path:
            return None
        # Skip the common path and continue the search.
        return _get(node.child, key[pl:], db)
    
    # Case 4: Encountered a Branch.
    if isinstance(node, Branch):
        # If no nibbles remain, the value must reside on the Branch itself.
        if len(key) == 0:
            return node.value
        # Use the next nibble as an index to traverse the correct child.
        return _get(node.children[key[0]], key[1:], db)
    raise TypeError(f"Unexpected node type: {type(node).__name__}")


def _delete(node: Optional[Node], key: tuple[int, ...], db: Optional[TrieKVStore] = None) -> tuple[Optional[Node], bool]:
    """Recursively deletes a key from the trie and simplifies its structure.

    This function traverses the trie to find the target key. If the key is 
    found and removed, it triggers a bottom-up normalization process using 
    `_collapse_node` to merge redundant nodes (e.g., converting a Branch 
    with one remaining child back into an Extension or Leaf).

    Args:
        node: The current root of the subtree to perform deletion on.
        key: The remaining nibbles of the key to be deleted.
        db: Optional database backend for resolving HashNodes. Default is None.

    Returns:
        A tuple containing:
            - The updated (and potentially collapsed) subtree root.
            - A boolean indicating if the key was actually found and deleted.

    Raises:
        TypeError: If an unrecognized node type is encountered.
    """
    node = _resolve(node, db)
    
    # Case 1: Empty slot or key not found
    if node is None:
        return None, False
    
    # Case 2: Encountered a Leaf
    if isinstance(node, Leaf):
        if node.path == key:
            return None, True  # Key found and deleted
        return node, False     # Path mismatch
    
    # Case 3: Encountered an Extension
    if isinstance(node, Extension):
        pl = len(node.path)
        if len(key) < pl or tuple(key[:pl]) != node.path:
            return node, False
        
        # Recursively delete from child
        child2, found = _delete(node.child, tuple(key[pl:]), db)
        if not found:
            return node, False
            
        # If the child becomes None, this extension also disappears
        if child2 is None:
            return None, True
            
        # Re-wrap and collapse to handle cases where the child changed structure
        return _collapse_node(Extension(node.path, child2), db), True
    
    # Case 4: Encountered a Branch
    if isinstance(node, Branch):
        # The key ends at this branch's value slot
        if len(key) == 0:
            if node.value is None:
                return node, False
            # Clear the value and collapse if necessary (e.g., branch now has < 2 children)
            new_b = Branch(list(node.children), None)
            return _collapse_node(new_b, db), True
            
        # The key continues through one of the children
        idx = key[0]
        ch2, found = _delete(node.children[idx], tuple(key[1:]), db)
        if not found:
            return node, False
            
        # Update children list and collapse to handle structural shrinkage
        children = list(node.children)
        children[idx] = ch2
        return _collapse_node(Branch(children, node.value), db), True
    
    raise TypeError(f"Unexpected node type: {type(node).__name__}")


def _key_to_path(key: bytes) -> tuple[int, ...]:
    """
    Ethereum-style state trie behavior: keys are hashed with keccak256 before
    being expanded into nibbles for the hexary trie path.
    """
    return key_to_nibbles(keccak256(key))


def _prove_walk(
    node: Optional[Node],
    key: tuple[int, ...],
    acc: list[bytes],
    *,
    embedded: bool = False,
    db: Optional[TrieKVStore] = None
) -> Optional[bytes]:
    """Traverses the trie to collect nodes for a Merkle inclusion proof.

    This function performs a recursive walk down the trie. While searching 
    for the key, it accumulates the RLP-encoded nodes encountered along 
    the path. It correctly handles Ethereum's node embedding rule: nodes 
    shorter than 32 bytes are already included in their parent's encoding 
    and should not be added to the proof as independent elements.

    If the search fails (key not found), it cleans up the accumulator (`acc`) 
    during recursion unwinding to ensure only valid path nodes remain.

    Args:
        node: The current node to inspect.
        key: The remaining nibbles of the key being proved.
        acc: An accumulator list that stores RLP-encoded nodes for the proof.
        embedded: Whether the current node is embedded in its parent. 
            If True, the node is skipped to avoid redundant proof data.
        db: Optional database backend for resolving HashNodes. Default is None.

    Returns:
        The value of the key if found; None if the key 
            does not exist in the trie.

    Raises:
        TypeError: If an unrecognized node type is encountered.
    """
    node = _resolve(node, db)
    if node is None:
        return None
        
    if isinstance(node, Leaf):
        if node.path != key:
            return None
        if not embedded:
            acc.append(encode_node(node))
        return node.value
        
    if isinstance(node, Extension):
        pl = len(node.path)
        if len(key) < pl or tuple(key[:pl]) != node.path:
            return None
        
        if not embedded:
            acc.append(encode_node(node))
        
        # Check if the child should be treated as an embedded node
        child_emb = len(embed_ref(node.child)) < 32
        v = _prove_walk(node.child, key[pl:], acc, embedded=child_emb, db=db)
        
        # Unwinding: if the path didn't lead to the key, remove this node from proof
        if v is None and not embedded:
            acc.pop()
        return v
        
    if isinstance(node, Branch):
        if not embedded:
            acc.append(encode_node(node))
            
        if len(key) == 0:
            if node.value is None:
                if not embedded:
                    acc.pop()
                return None
            return node.value
            
        ch = node.children[key[0]]
        if ch is None:
            if not embedded:
                acc.pop()
            return None
            
        child_emb = len(embed_ref(ch)) < 32
        v = _prove_walk(ch, key[1:], acc, embedded=child_emb, db=db)
        
        if v is None and not embedded:
            acc.pop()
        return v
        
    raise TypeError(f"Unexpected node type: {type(node).__name__}")


@functools.lru_cache(maxsize=65536)
def _resolve_cached(node_hash: bytes, db: TrieKVStore) -> Node:
    """Fetches and decodes a trie node from the database with LRU caching.

    This function serves as the performance-critical caching layer for the MPT. 
    By caching the decoded Node objects instead of raw bytes, it bypasses both 
    the database I/O and the expensive RLP decoding process for frequently 
    accessed nodes (especially those near the trie root).

    Since MPT nodes are content-addressed (immutable by hash), this cache 
    never requires manual invalidation.

    Args:
        node_hash: The 32-byte Keccak-256 hash used as the lookup key.
        db: The persistent storage backend implementing the TrieKVStore protocol.

    Returns:
        The decoded Node object (Branch, Extension, or Leaf).

    Raises:
        RuntimeError: If the hash is missing from the database, indicating 
            a trie corruption or incomplete persistence.
    """
    raw_bytes = db.get(node_hash)

    # To prevent the database error.
    if raw_bytes is None:
        raise RuntimeError(f"Database integrity error: Hash {node_hash.hex()} not found.")

    return decode_trie_node(raw_bytes)

def _resolve(node: Node, db: Optional[TrieKVStore] = None) -> Node:
    """Decodes a HashNode into a physical node using the database.

    If the node is a HashNode, this function fetches its RLP-encoded data 
    from the database and decodes it. For other node types, it returns 
    the node as-is.

    Args:
        node: The node to resolve (could be a physical node or a HashNode).
        db: The database instance used to retrieve RLP data. Default is None.

    Returns:
        The resolved physical node (Leaf, Extension, or Branch).

    Raises:
        ValueError: If a HashNode is encountered but no database is provided.
        RuntimeError: If the node hash is not found in the database.
    """
    if not isinstance(node, HashNode):
        return node


    if db is None:
        raise ValueError(
            f"Resolution failed: Encountered HashNode({node.hash.hex()}) "
            "but no database backend was provided to fetch the data."
        )

    
    # return decode_trie_node(raw_bytes)
    return _resolve_cached(node.hash, db)

@dataclass
class MerklePatriciaTrie:
    """In-memory hexary Merkle Patricia Trie (MPT).

    This class manages the lifecycle of an MPT where keys are processed as 
    hexadecimal nibbles (4-bit chunks). It supports both in-memory operations 
    and persistent storage via an optional KV store.

    Attributes:
        root: The current root node of the trie. Can be a physical node 
            (Branch, Extension, Leaf) or a placeholder (HashNode).
        db: An optional database backend for resolving HashNodes and 
            persisting trie state.
    """

    root: Optional[Node] = None
    db: Optional[TrieKVStore] = None

    def state_root(self) -> bytes:
        """Calculates the cryptographic fingerprint of the current trie.

        Returns:
            The 32-byte Keccak-256 hash of the root node.
        """
        return node_hash(self.root)

    def snapshot(self) -> Optional[Node]:
        """Creates a recursive deep copy of the trie's node structure.

        This is primarily used by visualization tools to traverse and resolve 
        the tree without affecting the original trie's lazy-loading state.

        Returns:
            The root of a new, independent node tree that 
                is structurally identical to the current state.
        """
        return snapshot_node(self.root, self.db)

    def insert(self, key: bytes, value: bytes) -> None:
        """Inserts or updates a value for a given key.

        The key is expanded into nibbles before traversing the trie.

        Args:
            key: The raw byte key.
            value: The byte value to be stored.
        """
        nib = _key_to_path(key)
        self.root = _insert(self.root, nib, value, self.db)

    def lookup(self, key: bytes) -> Optional[bytes]:
        """Retrieves the value associated with a key.

        Args:
            key: The raw byte key to search for.

        Returns:
            The stored value if the key exists; 
                None otherwise.
        """
        return _get(self.root, _key_to_path(key), self.db)

    def delete(self, key: bytes) -> bool:
        """Removes a key and its associated value from the trie.

        Args:
            key: The raw byte key to be deleted.

        Returns:
            True if the key was found and removed; False otherwise.
        """
        new_root, found = _delete(self.root, _key_to_path(key), self.db)
        if not found:
            return False
        self.root = new_root
        return True

    def prove(self, key: bytes) -> Optional[tuple[bytes, list[bytes]]]:
        """Generates a Merkle proof for a given key.

        The proof is a list of RLP-encoded nodes encountered on the path 
        from the root to the target leaf.

        Args:
            key: The raw byte key to prove.

        Returns:
            A tuple containing 
                (value, proof_nodes) if the key exists; None otherwise.
        """
        acc: list[bytes] = []
        v = _prove_walk(self.root, _key_to_path(key), acc, db=self.db)
        if v is None:
            return None
        return v, acc

    def to_dot(self, *, title: str = "MPT") -> str:
        """Generates a DOT representation of the trie for Graphviz visualization.

        Args:
            title: The label/title for the generated graph.

        Returns:
            A string in DOT format, or an empty string when the trie has no nodes.
        """

        from mpt.visualize import trie_to_dot

        return trie_to_dot(self.root, title=title)
