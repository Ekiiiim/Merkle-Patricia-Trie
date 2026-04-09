"""Export trie structure as Graphviz DOT (render with `dot -Tpng out.dot -o out.png`)."""

from __future__ import annotations

from typing import Optional

from mpt.ethereum import encode_node, node_hash
from mpt.nodes import Branch, Extension, Leaf, Node


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _wrap_hex(hex_str: str, width: int = 48) -> str:
    """Break long hex into lines for Graphviz labels (use \\n in DOT)."""
    if not hex_str:
        return ""
    return "\\n".join(hex_str[i : i + width] for i in range(0, len(hex_str), width))


def _hash_label(node: Optional[Node]) -> str:
    return _wrap_hex(node_hash(node).hex(), width=32)


def _rlp_label(node: Node) -> str:
    return _wrap_hex(encode_node(node).hex(), width=48)


def _emit_trie(
    lines: list[str],
    root: Optional[Node],
    *,
    id_prefix: str,
    indent: str,
) -> None:
    """Append DOT lines for one trie; node ids start with `id_prefix` (unique per subgraph)."""
    counter = [0]

    def new_id() -> str:
        counter[0] += 1
        return f"{id_prefix}_{counter[0]}"

    def emit(node: Optional[Node]) -> Optional[str]:
        if node is None:
            return None
        if isinstance(node, Leaf):
            nid = new_id()
            path_hex = bytes(node.path).hex()
            val_hex = node.value.hex()
            lines.append(
                f'{indent}{nid} [shape=box,style=filled,fillcolor="#e8f5e9",fontsize=9,'
                f'label="Leaf\\n'
                f"path_nibbles_hex={path_hex}\\n"
                f"value_hex={val_hex}\\n"
                f"node_hash_keccak256=\\n{_hash_label(node)}\\n"
                f"rlp_hex=\\n{_rlp_label(node)}"
                f'"];'
            )
            return nid
        if isinstance(node, Extension):
            nid = new_id()
            path_hex = bytes(node.path).hex()
            lines.append(
                f'{indent}{nid} [shape=ellipse,style=filled,fillcolor="#e3f2fd",fontsize=9,'
                f'label="Extension\\n'
                f"path_nibbles_hex={path_hex}\\n"
                f"node_hash_keccak256=\\n{_hash_label(node)}\\n"
                f"rlp_hex=\\n{_rlp_label(node)}"
                f'"];'
            )
            cid = emit(node.child)
            if cid is not None:
                lines.append(f"{indent}{nid} -> {cid};")
            return nid
        if isinstance(node, Branch):
            nid = new_id()
            lines.append(
                f'{indent}{nid} [shape=box,style=filled,fillcolor="#fff3e0",fontsize=9,'
                f'label="Branch\\n'
                f"node_hash_keccak256=\\n{_hash_label(node)}\\n"
                f"rlp_hex=\\n{_rlp_label(node)}"
                f'"];'
            )
            for i, ch in enumerate(node.children):
                if ch is None:
                    continue
                cid = emit(ch)
                if cid is not None:
                    lines.append(f'{indent}{nid} -> {cid} [label="{i:x}"];')
            if node.value is not None:
                vv = node.value.hex()
                term = new_id()
                lines.append(
                    f'{indent}{term} [shape=note,fillcolor="#fce4ec",fontsize=9,'
                    f'label="branch_terminal_value_hex={vv}"];'
                )
                lines.append(f'{indent}{nid} -> {term} [style=dashed,label="$"];')
            return nid
        raise TypeError(node)

    if root is None:
        lines.append(f'{indent}{id_prefix}_empty [shape=plaintext,label="∅ empty trie"];')
    else:
        emit(root)


def trie_to_dot(root: Optional[Node], *, title: str = "MPT") -> str:
    lines: list[str] = [
        "digraph MPT {",
        '  rankdir=TB;',
        '  graph [fontname="monospace"];',
        '  node [fontname="monospace"];',
        f'  label="{_esc(title)}";',
        "  labelloc=t;",
    ]
    _emit_trie(lines, root, id_prefix="n", indent="  ")
    lines.append("}")
    return "\n".join(lines)


def evolution_to_dot(
    steps: list[tuple[str, Optional[Node], str]],
    *,
    title: str = "MPT — step-by-step",
) -> str:
    """
    One Graphviz file with a `subgraph cluster_*` per step so the audience can
    compare structure and `state_root` after each operation.

    Each step is ``(description, root, state_root_hex)``.
    """
    lines: list[str] = [
        "digraph MPT_evolution {",
        '  graph [fontname="monospace", fontsize=10];',
        '  node [fontname="monospace"];',
        '  rankdir=LR;',
        "  newrank=true;",
        "  compound=true;",
        f'  label="{_esc(title)}";',
        "  labelloc=t;",
    ]
    for i, (desc, root, root_hex) in enumerate(steps):
        cluster = f"cluster_step{i}"
        label = f"{desc}\\nstate_root = {root_hex}"
        lines.append(f"  subgraph {cluster} {{")
        lines.append(f'    label="{_esc(label)}";')
        lines.append("    labelloc=t;")
        lines.append('    style="rounded,filled";')
        lines.append('    fillcolor="#eceff1";')
        lines.append('    color="#546e7a";')
        lines.append("    margin=16;")
        _emit_trie(lines, root, id_prefix=f"s{i}", indent="    ")
        lines.append("  }")
    lines.append("}")
    return "\n".join(lines)


def try_matplotlib_show(root: Optional[Node]) -> None:
    """Optional: layout with networkx + matplotlib if installed."""
    try:
        import matplotlib.pyplot as plt
        import networkx as nx
    except ImportError as e:
        raise ImportError(
            "Install viz extras: pip install matplotlib networkx"
        ) from e

    G = nx.DiGraph()
    labels: dict[str, str] = {}

    def walk(node: Optional[Node], name: str) -> None:
        if node is None:
            return
        if isinstance(node, Leaf):
            G.add_node(name)
            labels[name] = (
                f"L path={bytes(node.path).hex()}\n"
                f"v={node.value.hex()}\nh={node_hash(node).hex()}"
            )
        elif isinstance(node, Extension):
            G.add_node(name)
            labels[name] = (
                f"E path={bytes(node.path).hex()}\nh={node_hash(node).hex()}"
            )
            walk(node.child, f"{name}.c")
            G.add_edge(name, f"{name}.c")
        elif isinstance(node, Branch):
            G.add_node(name)
            labels[name] = f"Br h={node_hash(node).hex()}"
            for i, ch in enumerate(node.children):
                if ch is None:
                    continue
                cn = f"{name}.{i:x}"
                walk(ch, cn)
                G.add_edge(name, cn, label=f"{i:x}")

    walk(root, "r")
    pos = nx.spring_layout(G, seed=0)
    nx.draw(G, pos, with_labels=True, labels=labels, node_size=1200, font_size=6)
    plt.axis("off")
    plt.tight_layout()
    plt.show()
