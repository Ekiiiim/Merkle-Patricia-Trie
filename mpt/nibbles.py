"""Key material as hex nibbles (0–15), matching the usual MPT convention."""

from __future__ import annotations


def key_to_nibbles(key: bytes) -> tuple[int, ...]:
    """Expands a byte sequence into a sequence of 4-bit nibbles.

    Each byte is split into its high-order and low-order nibbles. For example, 
    the byte 0x1A is converted into the integers 1 and 10. This expansion 
    allows the trie to branch at each hexadecimal digit (hexary trie).

    Args:
        key: The raw byte sequence to be expanded.

    Returns:
        Tuple of integers, where each integer is between 0 and 15.
    """
    out: list[int] = []
    for b in key:
        out.append(b >> 4)      # Extract high nibble
        out.append(b & 0x0F)    # Extract low nibble
    return tuple(out)


def nibbles_to_bytes(nibbles: tuple[int, ...]) -> bytes:
    """Compresses a sequence of nibbles back into raw bytes.

    This function pairs consecutive nibbles and packs them into a single byte. 
    Because each byte requires exactly two nibbles, the input sequence must 
    have an even length.

    Args:
        nibbles: A sequence of integers (0-15) to be packed.

    Returns:
        The resulting byte sequence.

    Raises:
        ValueError: If the nibble length is odd, as it cannot be perfectly 
            packed into whole bytes.
    """
    if len(nibbles) % 2:
        raise ValueError("nibble length must be even for full-byte encoding")
    out = bytearray()
    for i in range(0, len(nibbles), 2):
        # Shift the first nibble left and combine with the second
        out.append((nibbles[i] << 4) | nibbles[i + 1])
    return bytes(out)


def common_prefix_length(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    """Calculates the length of the shared prefix between two nibble sequences.

    This is a critical utility for path compression (creating Extensions) and 
    identifying divergence points (splitting into Branches).

    Args:
        a: The first sequence of nibbles.
        b: The second sequence of nibbles.

    Returns:
        The number of leading nibbles that are identical in both sequences.
    """
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i
