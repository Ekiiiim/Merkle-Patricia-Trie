"""Visualization smoke test."""

from __future__ import annotations

from typing import Optional

from mpt import MerklePatriciaTrie, evolution_to_dot, node_hash
from mpt.nodes import Node
from mpt.trie import snapshot_node


def test_to_dot_contains_graph() -> None:
    t = MerklePatriciaTrie()
    t.insert(b"a", b"1")
    dot = t.to_dot(title="test")
    assert "digraph MPT" in dot
    assert "Leaf" in dot


def test_evolution_to_dot_subgraphs() -> None:
    t = MerklePatriciaTrie()
    steps: list[tuple[str, Optional[Node], str]] = []
    steps.append(("empty", snapshot_node(t.root), t.state_root().hex()))
    t.insert(b"a", b"1")
    steps.append(("+a", snapshot_node(t.root), t.state_root().hex()))
    dot = evolution_to_dot(steps)
    assert "digraph MPT_evolution" in dot
    assert "cluster_step0" in dot
    assert "cluster_step1" in dot
    assert "state_root" in dot
    assert node_hash(steps[0][1]) == node_hash(None)
