
import os
import sqlite3
from pathlib import Path
from typing import Optional, Union


import os
import sqlite3
from pathlib import Path
from typing import Optional, Union, Dict

class SQLiteKVStore:
    """A lightweight ``TrieKVStore`` implementation over Python's built-in sqlite3.
    
    This store implements the TrieKVStore protocol and serves as the database interface,
    optionally utilizing a memory buffer to optimize write performance.
    """

    # Memory optimization: limit attributes and avoid __dict__
    __slots__ = ("_conn", "enable_buffer", "_buffer") 

    def __init__(self, db_path: Union[str, bytes, Path], *, create_if_missing: bool = True, enable_buffer: bool = True) -> None:
        """Initializes the database connection and ensures the schema exists.

        Args:
            db_path: The file path to the SQLite database. Use ':memory:' for 
                in-memory storage.
            create_if_missing: If True, a new database file will be created if it 
                does not already exist. Defaults to True.
            enable_buffer: If True, all entries are stored in a memory buffer 
                and batched upon commit. Defaults to True.
        
        Note:
            Isolation level is set to None to enable autocommit mode, allowing 
            us to manually manage transactions using BEGIN/COMMIT/ROLLBACK.
        """
        exists = os.path.exists(db_path) or db_path == ":memory:"

        # Missing the data but cannot create
        if not exists and not create_if_missing:
            raise FileNotFoundError(f"Database doesn't exist: {db_path}")

        self._conn = sqlite3.connect(db_path, isolation_level=None)
        
        # Ensure the MPT store table is initialized if it doesn't exist.
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS mpt_store (
                key BLOB PRIMARY KEY,
                value BLOB
            )
        """)

        self.enable_buffer = enable_buffer

        self._buffer: Dict[bytes, Optional[bytes]] = {}

    def get(self, key: bytes) -> Optional[bytes]:
        """Retrieves the RLP-encoded value associated with a given key (hash).

        If buffering is enabled, it checks the uncommitted memory buffer first.
        Otherwise, it queries the physical database directly.

        Args:
            key: The 32-byte Keccak hash of the node.
        
        Returns:
            The RLP-encoded data if found, else None.
        """
        # 1. Check the buffer first (supports reading uncommitted changes)
        if self.enable_buffer and key in self._buffer:
            return self._buffer[key]
            
        # 2. Buffer miss (or buffer disabled): query the database
        cursor = self._conn.execute("SELECT value FROM mpt_store WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else None

    def put(self, key: bytes, value: bytes) -> None:
        """Writes a node to the store, overwriting the entry if the key already exists.

        If buffering is enabled, data is stored in memory and must be persisted 
        by calling :meth:`commit`. Otherwise, it writes directly to the database.

        Args:
            key: The 32-byte Keccak hash of the node.
            value: The RLP-encoded content of the node.
        """
        if self.enable_buffer:
            self._buffer[key] = value
        else:
            self._conn.execute("INSERT OR REPLACE INTO mpt_store (key, value) VALUES (?, ?)", (key, value))
    
    def begin(self) -> None:
        """Starts a new storage transaction.

        Ensures the environment is ready for a series of atomic operations and 
        opens a SQLite transaction block.
        """
        self._conn.execute("BEGIN TRANSACTION")
    
    def commit(self) -> None:
        """Finalizes the current transaction and persists all changes.

        If buffering is enabled, it uses ``executemany`` to batch write 
        buffer data to the physical database for maximum performance.
        """
        if self.enable_buffer and self._buffer:
            # Separate insert/update operations from potential deletions (tombstones)
            items_to_save = [(k, v) for k, v in self._buffer.items() if v is not None]
            if items_to_save:
                self._conn.executemany(
                    "INSERT OR REPLACE INTO mpt_store (key, value) VALUES (?, ?)",
                    items_to_save
                )
            
            # Future-proofing for delete operations
            items_to_delete = [(k,) for k, v in self._buffer.items() if v is None]
            if items_to_delete:
                self._conn.executemany("DELETE FROM mpt_store WHERE key = ?", items_to_delete)

        # Commit to disk
        self._conn.execute("COMMIT")
        
        # Clear the memory buffer upon success
        if self.enable_buffer:
            self._buffer.clear()
    
    def rollback(self) -> None:
        """Aborts the current transaction and discards pending changes.

        Executes SQL ROLLBACK to revert the database to the last committed state, 
        and clears the internal memory buffer to prevent dirty data leakage.
        """
        self._conn.execute("ROLLBACK")
        
        if self.enable_buffer:
            self._buffer.clear()

    def close(self) -> None:
        """Ends the database session."""
        self._conn.close()

