

from __future__ import annotations

import os
from pathlib import Path
from types import TracebackType
from typing import Optional, Type, Union

from mpt.constants import EMPTY_TRIE_ROOT
from mpt.nodes import HashNode
from mpt.storage.rocks import RocksKVStore
from mpt.store import (
    MPT_HEAD_KEY, 
    TrieKVStore, 
    commit_trie, 
    load_trie_from_head
)
from mpt.trie import MerklePatriciaTrie



class PersistentMPT:
    """
    Based on the object MerklePatriciaTrie, PersistentMPT is the MPT that support commit in Database.

    Node keys are 32-byte Keccak hashes of RLP (Ethereum-style). The key
    ``mpt\\x00head`` holds the last committed state root from :meth:`commit`.
    """

    __slots__ = ("_kv", "_trie") # Memory optimization: limit attributes and avoid __dict__ (So, we cannot add attributes outside __init__.)
    
    def __init__(self, db_path: Union[str, bytes, Path], *, create_if_missing: bool = True) -> None:
        """Initializes the persistent MPT by connecting to SQLite and restoring the latest committed state.

        Args:
            db_path: The file path to the SQLite database. Use ':memory:' for 
            in-memory storage.

            create_if_missing: If True, a new database file will be created if it 
            does not already exist at the specified path. Defaults to True.
        """
        
        # Our Level DB.
        
        # self._kv = SQLiteKVStore(db_path, create_if_missing=create_if_missing, enable_buffer=True)
        self._kv = RocksKVStore(db_path, create_if_missing=create_if_missing, enable_buffer=True)
        
        # Get the head hash of MPT.
        head_hash = self._kv.get(MPT_HEAD_KEY)
        
        # Start a fresh trie if: 1) no head exists, 2) it's an empty root, or 3) hash length is invalid.
        if head_hash is None or head_hash == EMPTY_TRIE_ROOT or len(head_hash) != 32:
            self._trie = MerklePatriciaTrie(db=self._kv)
        else:
            # Lazy load the existing trie using the head hash.
            self._trie = MerklePatriciaTrie(root=HashNode(head_hash), db=self._kv)

    @property
    def trie(self) -> MerklePatriciaTrie:
        """
        Returns:
            The trie object.
        """
        return self._trie

    def commit(self) -> bytes:
        """Persists all reachable nodes to the database and updates the head.

        This method walks the trie, writes all new or modified nodes to the 
        persistent KV store (via the memory buffer), and updates the 
        'mpt\x00head' key to point to the newly calculated state root (sr).

        Returns:
            bytes: The 32-byte Keccak hash of the new state root.

        Raises:
            Exception: If any error occurs during the trie traversal or 
                database write, both the memory buffer and the database 
                transaction are rolled back.
        """
        # 1. Start the transaction via the Protocol (clears buffer and BEGIN SQL)
        self._kv.begin() 
        
        try:
            # 2. Walk the trie and fill the KVStore buffer.
            # commit_trie calls self._kv.put() many times.
            sr = commit_trie(self._kv, self._trie, write_head=True)
            
            # 3. Finalize: Flush buffer to DB and issue SQL COMMIT
            self._kv.commit()

            # 4. [Memory Optimization] 
            # Replace the in-memory node tree with a HashNode stub.
            # This allows the Python objects to be garbage collected, 
            # relying on lazy-loading for future lookups.
            self._trie.root = HashNode(sr)

            return sr
            
        except Exception as e:
            # 5. Safety: Rollback both the SQL transaction and the memory buffer
            self._kv.rollback()
            raise e

    def close(self) -> None:
        """End the database session.
        """
        self._kv.close()

    def __enter__(self) -> PersistentMPT:
        """Enters the runtime context (with ...) for the persistent trie."""
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        """Closes the database connection upon exiting the context."""
        self.close()

    def insert(self, key: bytes, value: bytes) -> None:
        """Inserts or updates a key-value pair in the underlying trie.

        Note:
            This operation only modifies the in-memory state. You must call 
            :meth:`commit` to persist these changes to the SQLite database.

        Args:
            key: The key to insert, provided as raw bytes.
            value: The corresponding value (e.g., RLP-encoded data) to store.
        """
        self._trie.insert(key, value)

    def lookup(self, key: bytes) -> Optional[bytes]:
        """Retrieves the value associated with the given key.

        Args:
            key: The key to look up in the trie.

        Returns:
            Optional[bytes]: The stored value if the key exists; 
                None if the key is not found in the trie.
        """
        return self._trie.lookup(key)

    def delete(self, key: bytes) -> bool:
        """Deletes a key-value pair from the underlying trie.

        Args:
            key: The key to be removed from the trie.

        Returns:
            True if the key was found and deleted; False if the key did not exist.
        """
        return self._trie.delete(key)

    def state_root(self) -> bytes:
        """Returns the current state root hash of the trie.

        The state root is the cryptographic fingerprint of the entire trie 
        structure. Any change in the trie's data will result in a different root.

        Returns:
            The 32-byte Keccak-256 hash of the current root node.
        """
        return self._trie.state_root()

    def prove(self, key: bytes) -> Optional[tuple[bytes, list[bytes]]]:
        """Generates a Merkle proof for a given key.

        The proof consists of the current state root and a list of RLP-encoded 
        nodes that form the path from the root to the target leaf. This allows 
        clients to verify the value without possessing the entire database.

        Args:
            key: The key for which to generate the Merkle proof.

        Returns:
            A tuple of (state_root, proof_nodes) if the key exists; otherwise, None.
        """
        return self._trie.prove(key)


def open_persistent(path: str, *, create_if_missing: bool = True) -> PersistentMPT:
    """Opens a persistent Merkle Patricia Trie at the specified path.

    This is a convenience wrapper for initializing a :class:`PersistentMPT` instance.
    It is intended to be used with a ``with`` statement to ensure the database 
    connection is properly closed.

    Args:
        path: The file path to the SQLite database.
        create_if_missing: Whether to create a new database file if it 
            doesn't exist. Defaults to True.

    Returns:
        PersistentMPT: A persistent trie instance ready for use.
    """
    return PersistentMPT(path, create_if_missing=create_if_missing)
