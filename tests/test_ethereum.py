"""Ethereum encoding constants and hex-prefix roundtrip."""

from __future__ import annotations

from mpt.constants import EMPTY_TRIE_ROOT, keccak256
from mpt.ethereum import compact_encoding, decode_hex_prefix, encode_hex_prefix, rlp_encode_node
from mpt.nodes import Leaf


def test_empty_trie_root_matches_mainnet_convention() -> None:
    # keccak256(RLP('')) with RLP('') = 0x80
    assert (
        EMPTY_TRIE_ROOT.hex()
        == "56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421"
    )


def test_path_encoding_roundtrip_examples() -> None:
    for nibbles in (
        (),
        (1, 2, 3, 4),
        (10, 11, 12),
        tuple(range(16)),
    ):
        for leaf in (False, True):
            enc = compact_encoding(nibbles, leaf)
            got, is_leaf = decode_hex_prefix(enc)
            assert got == nibbles and is_leaf == leaf


def test_small_leaf_rlp_under_32_bytes_uses_embed_in_parent() -> None:
    leaf = Leaf((1, 2), b"x")
    raw = rlp_encode_node(leaf)
    assert len(raw) < 32
    assert keccak256(raw) != raw
