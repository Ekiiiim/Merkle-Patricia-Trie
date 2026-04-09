#!/usr/bin/env python3
"""
Run from the repo root: python demo.py

Prints state roots, lookups, proof verification, and writes Graphviz DOT:
  - demo_steps.dot — one subgraph cluster per step (easy to verify evolution)
  - demo_trie.dot  — final trie only

Render (requires Graphviz): dot -Tpng demo_steps.dot -o demo_steps.png
  macOS: brew install graphviz
"""

from __future__ import annotations

import argparse
from typing import Optional
import shutil
import sys
from pathlib import Path

# Ensure repo root is importable when run as `python demo.py`
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mpt import MerklePatriciaTrie, evolution_to_dot, verify_inclusion
from mpt.nodes import Node


def main() -> None:
    parser = argparse.ArgumentParser(description="MPT interactive demo")
    parser.add_argument(
        "--dot",
        default="demo_trie.dot",
        help="Path for final-trie-only DOT (default: demo_trie.dot)",
    )
    parser.add_argument(
        "--steps-dot",
        default="demo_steps.dot",
        help="Path for step-by-step subgraph DOT (default: demo_steps.dot)",
    )
    args = parser.parse_args()

    t = MerklePatriciaTrie()
    steps: list[tuple[str, Optional[Node], str]] = []

    def record(desc: str) -> None:
        root_snap = t.snapshot()
        steps.append((desc, root_snap, t.state_root().hex()))

    print("=== Merkle Patricia Trie demo ===\n")

    record("0 — empty trie")
    print("Empty trie state root:")
    print(f"  {steps[-1][2]}\n")

    t.insert(b"alice", b"100")
    record("1 — insert(alice → 100)")
    t.insert(b"bob", b"200")
    record("2 — insert(bob → 200)")
    t.insert(b"alma", b"300")
    record("3 — insert(alma → 300)")

    print("After insert(alice→100, bob→200, alma→300):")
    print(f"  state_root = {t.state_root().hex()}")
    print(f"  lookup(alice) = {t.lookup(b'alice')!r}")
    print(f"  lookup(bob)   = {t.lookup(b'bob')!r}")
    print(f"  lookup(alma)  = {t.lookup(b'alma')!r}")
    print(f"  lookup(eve)   = {t.lookup(b'eve')!r}\n")

    key, val = b"alice", t.lookup(b"alice")
    assert val is not None
    got_val, proof = t.prove(key)
    assert got_val == val
    ok = verify_inclusion(t.state_root(), key, val, proof)
    print(f"Inclusion proof for {key!r}:")
    print(f"  proof length = {len(proof)} node(s)")
    print(f"  verify_inclusion(...) = {ok}\n")

    t.delete(b"bob")
    record("4 — delete(bob)")
    print("After delete(bob):")
    print(f"  lookup(bob) = {t.lookup(b'bob')!r}")
    print(f"  state_root  = {t.state_root().hex()}\n")

    steps_path = Path(args.steps_dot)
    steps_path.write_text(
        evolution_to_dot(steps, title="MPT demo — verify each step"),
        encoding="utf-8",
    )
    print(f"Wrote step-by-step DOT (subgraphs) to {steps_path.resolve()}")

    dot_path = Path(args.dot)
    dot_path.write_text(t.to_dot(title="MPT demo — final trie"), encoding="utf-8")
    print(f"Wrote final-trie DOT to {dot_path.resolve()}")

    if shutil.which("dot"):
        sp = steps_path.with_suffix(".png")
        fp = dot_path.with_suffix(".png")
        print("  Render steps:  dot -Tpng", steps_path, "-o", sp)
        print("  Render final: dot -Tpng", dot_path, "-o", fp)
    else:
        print("  `dot` not found — install Graphviz, then run the commands above.")
        print("  macOS (Homebrew): brew install graphviz")
        print("  https://graphviz.org/download/")


if __name__ == "__main__":
    main()
