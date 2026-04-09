"""In-memory MPT node shapes (Ethereum-style branch / extension / leaf)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

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
