"""In-memory MPT nodes and Merkle hashing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

from mpt.constants import EMPTY_SUBTREE_HASH, h

Node = Union["Branch", "Extension", "Leaf", None]


@dataclass
class Leaf:
    path: tuple[int, ...]
    value: bytes


@dataclass
class Extension:
    path: tuple[int, ...]
    child: Node


@dataclass
class Branch:
    children: list[Optional["Branch | Extension | Leaf"]]
    value: Optional[bytes]

    def __post_init__(self) -> None:
        if len(self.children) != 16:
            raise ValueError("branch must have 16 children")


def _pack_nibbles(nibbles: tuple[int, ...]) -> bytes:
    return len(nibbles).to_bytes(2, "big") + bytes(nibbles)


def unpack_nibbles(data: bytes, offset: int = 0) -> tuple[tuple[int, ...], int]:
    if offset + 2 > len(data):
        raise ValueError("truncated nibble length")
    ln = int.from_bytes(data[offset : offset + 2], "big")
    start = offset + 2
    end = start + ln
    if end > len(data):
        raise ValueError("truncated nibbles")
    nibbles = tuple(data[start:end])
    for n in nibbles:
        if n > 15:
            raise ValueError("invalid nibble")
    return nibbles, end


def canonical_bytes(node: Node) -> bytes:
    if node is None:
        raise TypeError("canonical_bytes(None) undefined")
    if isinstance(node, Leaf):
        return (
            b"L"
            + _pack_nibbles(node.path)
            + len(node.value).to_bytes(4, "big")
            + node.value
        )
    if isinstance(node, Extension):
        return b"E" + _pack_nibbles(node.path) + node_hash(node.child)
    if isinstance(node, Branch):
        buf = bytearray(b"B")
        for c in node.children:
            buf.extend(node_hash(c))
        if node.value is None:
            buf.append(0)
        else:
            buf.append(1)
            buf.extend(len(node.value).to_bytes(4, "big"))
            buf.extend(node.value)
        return bytes(buf)
    raise TypeError(type(node))


def node_hash(node: Node) -> bytes:
    if node is None:
        return EMPTY_SUBTREE_HASH
    return h(canonical_bytes(node))


def encode_node(node: Node) -> bytes:
    return canonical_bytes(node)
