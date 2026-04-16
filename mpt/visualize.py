"""Export trie structure as Graphviz DOT (render with `dot -Tpng out.dot -o out.png`)."""

from __future__ import annotations

from typing import Any, Optional

from mpt.constants import keccak256
from mpt.ethereum import compact_encoding, embed_ref, encode_hex_prefix, encode_node, node_hash, path_encoding
from mpt.nodes import Branch, Extension, Leaf, Node


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')

def _esc_label_value(s: str) -> str:
    """
    Escape a value that will be embedded inside a DOT label.

    We want to preserve Graphviz newline escapes (``\n``) that we insert for wrapping,
    so we escape first, then re-enable ``\n``.
    """
    out = _esc(s)
    return out.replace("\\\\n", "\\n")


def _wrap_hex(hex_str: str, width: int = 48) -> str:
    """Break long hex into lines for Graphviz labels (use \\n in DOT)."""
    if not hex_str:
        return ""
    return "\\n".join(hex_str[i : i + width] for i in range(0, len(hex_str), width))

def _wrap_text(s: str, width: int = 32) -> str:
    """Wrap plain text for DOT labels using Graphviz ``\n`` escapes."""
    if not s or len(s) <= width:
        return s
    return "\\n".join(s[i : i + width] for i in range(0, len(s), width))


# Max characters per line inside node boxes (prefix + hex must share the same budget).
_LABEL_WRAP = 20

# Inches: space between label text and node border (x, y). Wider x keeps monospace off the sides.
_NODE_MARGIN = "0.32,0.14"


def _hash_label(node: Optional[Node]) -> str:
    return _wrap_hex(node_hash(node).hex(), width=_LABEL_WRAP)


def _rlp_label(node: Node) -> str:
    return _wrap_hex(encode_node(node).hex(), width=_LABEL_WRAP)

def _is_readable_ascii(s: str) -> bool:
    # Prefer a conservative "printable" subset for DOT labels.
    if not s:
        return False
    return all(ch.isprintable() and ch not in {"\n", "\r", "\t"} for ch in s)


def _bytes_readable(b: bytes, *, max_len: int | None = None) -> str:
    """
    Render bytes as a readable string when possible, else as hex.

    - If UTF-8 decodes to mostly-printable text, show it (quoted).
    - Otherwise show hex.
    """
    try:
        s = b.decode("utf-8")
    except UnicodeDecodeError:
        return f"0x{b.hex()}"
    if not _is_readable_ascii(s):
        return f"0x{b.hex()}"
    if max_len is not None and len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return repr(s)

def _nibbles_hex(nibs: tuple[int, ...]) -> str:
    """Render nibble tuple as hex string (length can be odd)."""
    return "".join(format(n & 0xF, "x") for n in nibs)


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

    def emit(node: Optional[Node], prefix: tuple[int, ...]) -> Optional[str]:
        if node is None:
            return None
        if isinstance(node, Leaf):
            nid = new_id()
            full_path = prefix + node.path
            # Wrap the full "key=value" so the prefix does not sit on one long first line.
            path_disp = _esc_label_value(
                _wrap_text("path_nibbles_hex=0x" + _nibbles_hex(full_path), width=_LABEL_WRAP)
            )
            val_disp = _esc_label_value(
                _wrap_text("value=" + _bytes_readable(node.value, max_len=None), width=_LABEL_WRAP)
            )
            lines.append(
                f'{indent}{nid} [shape=box,style=filled,fillcolor="#e8f5e9",fontsize=9,'
                f'label="Leaf\\n'
                f"{path_disp}\\n"
                f"{val_disp}\\n"
                f"node_hash_keccak256=\\n{_hash_label(node)}"
                f'"];'
            )
            return nid
        if isinstance(node, Extension):
            nid = new_id()
            full_path = prefix + node.path
            path_hex = _nibbles_hex(full_path)
            path_disp = _esc_label_value(
                _wrap_text("path_nibbles_hex=0x" + path_hex, width=_LABEL_WRAP)
            )
            lines.append(
                f'{indent}{nid} [shape=ellipse,style=filled,fillcolor="#e3f2fd",fontsize=9,'
                f'label="Extension\\n'
                f"{path_disp}\\n"
                f"node_hash_keccak256=\\n{_hash_label(node)}\\n"
                f"rlp_hex=\\n{_rlp_label(node)}"
                f'"];'
            )
            cid = emit(node.child, full_path)
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
                cid = emit(ch, prefix + (i,))
                if cid is not None:
                    lines.append(f'{indent}{nid} -> {cid} [label="{i:x}"];')
            if node.value is not None:
                vv = node.value.hex()
                term = new_id()
                term_lbl = _esc_label_value(
                    _wrap_text("branch_terminal_value_hex=" + vv, width=_LABEL_WRAP)
                )
                lines.append(
                    f'{indent}{term} [shape=note,fillcolor="#fce4ec",fontsize=9,'
                    f'label="{term_lbl}"];'
                )
                lines.append(f'{indent}{nid} -> {term} [style=dashed,label="$"];')
            return nid
        raise TypeError(node)

    if root is None:
        lines.append(f'{indent}{id_prefix}_empty [shape=plaintext,label="(empty trie)"];')
    else:
        emit(root, ())


def trie_to_dot(root: Optional[Node], *, title: str = "MPT") -> str:
    """
    Return Graphviz DOT for ``root``.

    For an empty trie (``root is None``), returns an empty string so UIs that run
    Graphviz in WASM can show a blank canvas instead of a malformed SVG.
    """
    if root is None:
        return ""
    lines: list[str] = [
        "digraph MPT {",
        '  rankdir=TB;',
        '  graph [charset="UTF-8", fontname="monospace"];',
        f'  node [fontname="monospace", margin="{_NODE_MARGIN}"];',
        f'  label="{_esc(title)}";',
        "  labelloc=t;",
    ]
    _emit_trie(lines, root, id_prefix="n", indent="  ")
    lines.append("}")
    return "\n".join(lines)


def evolution_to_dot(
    steps: list[tuple[str, Optional[Node], str]],
    *,
    title: str = "MPT - step-by-step",
) -> str:
    """
    One Graphviz file with a `subgraph cluster_*` per step so the audience can
    compare structure and `state_root` after each operation.

    Each step is ``(description, root, state_root_hex)``.
    """
    lines: list[str] = [
        "digraph MPT_evolution {",
        '  graph [charset="UTF-8", fontname="monospace", fontsize=10];',
        f'  node [fontname="monospace", margin="{_NODE_MARGIN}"];',
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
                f"L path=0x{_nibbles_hex(node.path)}\n"
                f"v={_bytes_readable(node.value)}\nh={node_hash(node).hex()}"
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


def trie_to_graph(root: Optional[Node]) -> dict[str, Any]:
    """
    Return a JSON-serializable graph representation of ``root``.

    Node IDs are stable: ``keccak256(RLP(node))`` (same as ``node_hash(node)``).
    This is designed for interactive frontends (Cytoscape, etc.).
    """

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_node(node: Node, *, kind: str, path_prefix: tuple[int, ...]) -> str:
        hid = node_hash(node).hex()
        if hid in seen:
            return hid
        seen.add(hid)

        # Common fields
        row: dict[str, Any] = {
            "id": hid,
            "kind": kind,
            "hash_hex": hid,
            "rlp_hex": encode_node(node).hex(),
        }

        # Human-friendly extras per kind
        if isinstance(node, Leaf):
            full_path = path_prefix + node.path
            row.update(
                {
                    "node_path_nibbles_hex": "0x" + _nibbles_hex(node.path),
                    "compact_path_hex": compact_encoding(node.path, True).hex(),
                    "path_nibbles_hex": "0x" + _nibbles_hex(full_path),
                    "key_utf8": (node.key.decode("utf-8", errors="replace") if getattr(node, "key", None) else None),
                    "key_keccak_hex": (keccak256(node.key).hex() if getattr(node, "key", None) else None),
                    "value_utf8": node.value.decode("utf-8", errors="replace"),
                    "value_hex": node.value.hex(),
                }
            )
        elif isinstance(node, Extension):
            full_path = path_prefix + node.path
            ref = embed_ref(node.child)
            row.update(
                {
                    "node_path_nibbles_hex": "0x" + _nibbles_hex(node.path),
                    "compact_path_hex": compact_encoding(node.path, False).hex(),
                    "path_nibbles_hex": "0x" + _nibbles_hex(full_path),
                    "child_ref_hex": ref.hex(),
                    "child_ref_kind": ("embedded" if 0 < len(ref) < 32 else "hash" if len(ref) == 32 else "empty"),
                }
            )
        elif isinstance(node, Branch):
            child_refs = [embed_ref(c) for c in node.children]
            if node.value is not None:
                row.update(
                    {
                        "terminal_value_hex": node.value.hex(),
                        "terminal_value_utf8": node.value.decode("utf-8", errors="replace"),
                    }
                )
            row.update(
                {
                    "path_nibbles_hex": "0x" + _nibbles_hex(path_prefix),
                    "child_refs_hex": [r.hex() for r in child_refs],
                    "child_refs_kind": [
                        ("empty" if len(r) == 0 else "embedded" if len(r) < 32 else "hash") for r in child_refs
                    ],
                    "value_slot_hex": (node.value.hex() if node.value is not None else ""),
                }
            )
        nodes.append(row)
        return hid

    def add_edge(src: str, dst: str, *, label: str | None, kind: str) -> None:
        eid = f"{src}->{dst}"
        edges.append(
            {
                "id": eid,
                "source": src,
                "target": dst,
                "label": label,
                "kind": kind,
            }
        )

    def walk(node: Optional[Node], prefix: tuple[int, ...]) -> Optional[str]:
        if node is None:
            return None
        if isinstance(node, Leaf):
            return add_node(node, kind="leaf", path_prefix=prefix)
        if isinstance(node, Extension):
            src = add_node(node, kind="extension", path_prefix=prefix)
            full = prefix + node.path
            cid = walk(node.child, full)
            if cid is not None:
                add_edge(src, cid, label=None, kind="child")
            return src
        if isinstance(node, Branch):
            src = add_node(node, kind="branch", path_prefix=prefix)
            for i, ch in enumerate(node.children):
                if ch is None:
                    continue
                cid = walk(ch, prefix + (i,))
                if cid is not None:
                    add_edge(src, cid, label=f"{i:x}", kind="branch-child")
            # Represent branch terminal value as a separate node for UI clarity.
            if node.value is not None:
                term_id = f"{src}:$"
                nodes.append(
                    {
                        "id": term_id,
                        "kind": "branch-terminal",
                        "label": "$",
                        "path_nibbles_hex": "0x" + _nibbles_hex(prefix),
                        "value_hex": node.value.hex(),
                        "value_utf8": node.value.decode("utf-8", errors="replace"),
                        "hash_hex": None,
                        "rlp_hex": None,
                    }
                )
                add_edge(src, term_id, label="$", kind="terminal")
            return src
        raise TypeError(node)

    walk(root, ())
    return {"nodes": nodes, "edges": edges}
