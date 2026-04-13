"""Abstract interfaces for the Merkle Patricia Trie components."""

from __future__ import annotations
from typing import Optional, Protocol

class TrieKVStore(Protocol):
    """An abstract structural interface for a Key-Value storage backend.

    This protocol defines the minimal set of methods required for any storage 
    layer used by the Merkle Patricia Trie. By adhering to this protocol, 
    the trie logic remains agnostic of the underlying storage implementation 
    (e.g., in-memory dict, SQLite, or LevelDB).
    """

    def get(self, key: bytes) -> Optional[bytes]:
        """Retrieves the value associated with a given key (node hash).

        Args:
            key: The key to lookup, typically a 32-byte Keccak-256 hash.

        Returns:
            The RLP-encoded node data if found; None otherwise.
        """
        ...

    def put(self, key: bytes, value: bytes) -> None:
        """Persists a key-value pair in the storage.

        Args:
            key: The 32-byte Keccak-256 hash used as the storage key.
            value: The RLP-encoded node content to be stored.
        """
        ...
    
    def begin(self) -> None:
        """Starts a new storage transaction.

        This method prepares the store for a series of atomic operations. 
        In a buffered implementation, this typically ensures the internal 
        memory buffer is clean and signals the underlying database (e.g., 
        SQLite) to open a transaction block.
        """
        ...

    def commit(self) -> None:
        """Finalizes the current transaction and persists all changes.

        This is the most critical operation for performance. It should:
        1. Execute a batch write (e.g., ``executemany``) to move all 
           entries from the memory buffer to the physical database.
        2. Issue a formal COMMIT command to the database to ensure 
           Atomicity and Durability (ACID).
        3. Clear the internal memory buffer upon success.

        """
        ...

    def rollback(self) -> None:
        """Aborts the current transaction and discards pending changes.

        This serves as the safety mechanism during failures. It must:
        1. Clear the internal memory buffer to prevent "dirty data" from 
           leaking into the next transaction.
        2. Issue a ROLLBACK command to the underlying database to revert 
           to the last committed state.
        """
        ...
