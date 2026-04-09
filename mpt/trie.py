"""Hexary Merkle Patricia Trie: insert, lookup, delete, state root.

Structural normalization uses ``_collapse_node`` only on nodes returned along the
edited path (O(key length)), not a full trie scan after each operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from mpt.nibbles import common_prefix_length, key_to_nibbles
from mpt.ethereum import embed_ref, encode_node, node_hash
from mpt.nodes import Branch, Extension, Leaf, Node


def snapshot_node(node: Optional[Node]) -> Optional[Node]:
    """Deep copy of the trie shape (the live trie mutates in place)."""
    if node is None:
        return None
    if isinstance(node, Leaf):
        return Leaf(node.path, node.value)
    if isinstance(node, Extension):
        return Extension(node.path, snapshot_node(node.child))
    if isinstance(node, Branch):
        return Branch([snapshot_node(c) for c in node.children], node.value)
    raise TypeError(node)


def _empty_branch() -> Branch:
    return Branch([None] * 16, None)


def _prepend_nibble(nib: int, child: Node) -> Node:
    if child is None:
        return None  # type: ignore[return-value]
    if isinstance(child, Leaf):
        return Leaf((nib,) + child.path, child.value)
    if isinstance(child, Extension):
        return Extension((nib,) + child.path, child.child)
    return Extension((nib,), child)


def _merge_extension_path(prefix: tuple[int, ...], child: Node) -> Node:
    if isinstance(child, Leaf):
        return Leaf(prefix + child.path, child.value)
    if isinstance(child, Extension):
        return Extension(prefix + child.path, child.child)
    return Extension(prefix, child)


def _collapse_node(node: Optional[Node]) -> Optional[Node]:
    """
    Normalize this node only; assume children are already normalized (O(depth), not O(N)).

    Branch children are not recursively collapsed here — recursive insert/delete already
    returns collapsed subtrees along the updated path.
    """
    if node is None:
        return None
    if isinstance(node, Leaf):
        return node
    if isinstance(node, Extension):
        c = _collapse_node(node.child)
        if c is None:
            return None
        return _merge_extension_path(node.path, c)
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
                    return _prepend_nibble(i, c)
            return None
        return Branch(new_children, None)
    raise TypeError(node)


def _insert(node: Optional[Node], key: tuple[int, ...], val: bytes) -> Node:
    if node is None:
        return _collapse_node(Leaf(key, val))
    if isinstance(node, Leaf):
        return _collapse_node(_insert_into_leaf(node, key, val))
    if isinstance(node, Extension):
        return _collapse_node(_insert_into_extension(node, key, val))
    if isinstance(node, Branch):
        return _collapse_node(_insert_into_branch(node, key, val))
    raise TypeError(node)


def _insert_into_leaf(leaf: Leaf, key: tuple[int, ...], val: bytes) -> Node:
    lp = leaf.path
    if lp == key:
        return Leaf(lp, val)
    cpl = common_prefix_length(lp, key)

    # Strict prefix of existing leaf path: longer key extends `lp`.
    if cpl == len(lp) < len(key):
        suffix = tuple(key[cpl:])
        nxt = suffix[0]
        children = [None] * 16
        children[nxt] = _insert(None, tuple(suffix[1:]), val)
        br = Branch(children, leaf.value)
        if cpl == 0:
            return br
        return Extension(tuple(lp[:cpl]), br)

    # New key is a strict prefix of the existing leaf path.
    if cpl == len(key) < len(lp):
        nxt = lp[cpl]
        children = [None] * 16
        children[nxt] = _insert(None, tuple(lp[cpl + 1 :]), leaf.value)
        br = Branch(children, val)
        if cpl == 0:
            return br
        return Extension(tuple(key[:cpl]), br)

    # Internal divergence
    common = lp[:cpl]
    br = _empty_branch()
    a, b = lp[cpl], key[cpl]
    children = list(br.children)
    children[a] = _insert(None, tuple(lp[cpl + 1 :]), leaf.value)
    children[b] = _insert(None, tuple(key[cpl + 1 :]), val)
    br = Branch(children, None)
    if cpl == 0:
        return br
    return Extension(common, br)


def _insert_into_extension(ext: Extension, key: tuple[int, ...], val: bytes) -> Node:
    ep = ext.path
    cpl = common_prefix_length(ep, key)
    if cpl == len(ep):
        new_child = _insert(ext.child, tuple(key[cpl:]), val)
        return Extension(ep, new_child)

    common = ep[:cpl]
    tail_e = ep[cpl]
    tail_k = key[cpl]
    rest_e = tuple(ep[cpl + 1 :])
    rest_k = tuple(key[cpl + 1 :])
    br = _empty_branch()
    children = list(br.children)
    children[tail_e] = ext.child if not rest_e else Extension(rest_e, ext.child)
    children[tail_k] = _insert(None, rest_k, val)
    br = Branch(children, None)
    if cpl == 0:
        return br
    return Extension(common, br)


def _insert_into_branch(br: Branch, key: tuple[int, ...], val: bytes) -> Branch:
    if len(key) == 0:
        return Branch(list(br.children), val)
    children = list(br.children)
    idx = key[0]
    children[idx] = _insert(children[idx], tuple(key[1:]), val)
    return Branch(children, br.value)


def _get(node: Optional[Node], key: tuple[int, ...]) -> Optional[bytes]:
    if node is None:
        return None
    if isinstance(node, Leaf):
        return node.value if node.path == key else None
    if isinstance(node, Extension):
        pl = len(node.path)
        if len(key) < pl or tuple(key[:pl]) != node.path:
            return None
        return _get(node.child, key[pl:])
    if isinstance(node, Branch):
        if len(key) == 0:
            return node.value
        return _get(node.children[key[0]], key[1:])
    raise TypeError(node)


def _delete(node: Optional[Node], key: tuple[int, ...]) -> tuple[Optional[Node], bool]:
    if node is None:
        return None, False
    if isinstance(node, Leaf):
        if node.path == key:
            return None, True
        return node, False
    if isinstance(node, Extension):
        pl = len(node.path)
        if len(key) < pl or tuple(key[:pl]) != node.path:
            return node, False
        child2, found = _delete(node.child, tuple(key[pl:]))
        if not found:
            return node, False
        if child2 is None:
            return None, True
        return _collapse_node(Extension(node.path, child2)), True
    if isinstance(node, Branch):
        if len(key) == 0:
            if node.value is None:
                return node, False
            new_b = Branch(list(node.children), None)
            return _collapse_node(new_b), True
        idx = key[0]
        ch2, found = _delete(node.children[idx], tuple(key[1:]))
        if not found:
            return node, False
        children = list(node.children)
        children[idx] = ch2
        return _collapse_node(Branch(children, node.value)), True
    raise TypeError(node)


def _prove_walk(
    node: Optional[Node],
    key: tuple[int, ...],
    acc: list[bytes],
    *,
    embedded: bool = False,
) -> Optional[bytes]:
    """
    If ``embedded`` is True, this node is carried inside the parent's RLP (<32-byte
    ref); do not append it again to ``acc`` (Ethereum-style compact proofs).
    """
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
        child_emb = len(embed_ref(node.child)) < 32
        v = _prove_walk(node.child, key[pl:], acc, embedded=child_emb)
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
        v = _prove_walk(ch, key[1:], acc, embedded=child_emb)
        if v is None and not embedded:
            acc.pop()
        return v
    raise TypeError(node)


@dataclass
class MerklePatriciaTrie:
    """In-memory hexary MPT; keys are raw bytes (expanded to nibbles)."""

    root: Optional[Node] = None

    def state_root(self) -> bytes:
        return node_hash(self.root)

    def snapshot(self) -> Optional[Node]:
        return snapshot_node(self.root)

    def insert(self, key: bytes, value: bytes) -> None:
        nib = key_to_nibbles(key)
        self.root = _insert(self.root, nib, value)

    def lookup(self, key: bytes) -> Optional[bytes]:
        return _get(self.root, key_to_nibbles(key))

    def delete(self, key: bytes) -> bool:
        new_root, found = _delete(self.root, key_to_nibbles(key))
        if not found:
            return False
        self.root = new_root
        return True

    def prove(self, key: bytes) -> Optional[tuple[bytes, list[bytes]]]:
        """Return (value, proof) for inclusion, or None if the key is absent."""
        acc: list[bytes] = []
        v = _prove_walk(self.root, key_to_nibbles(key), acc)
        if v is None:
            return None
        return v, acc

    def to_dot(self, *, title: str = "MPT") -> str:
        from mpt.visualize import trie_to_dot

        return trie_to_dot(self.root, title=title)
