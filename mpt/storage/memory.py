
import os
from pathlib import Path
from typing import MutableMapping, Optional, Union

from typing import Optional, MutableMapping, Dict

class MemoryKVStore:
    """An in-memory implementation of the TrieKVStore protocol.

    This class provides a dictionary-backed storage for trie nodes with 
    transactional support via a memory buffer. This ensures consistent 
    behavior across different storage backends during testing.
    """

    # Use __slots__ for memory efficiency, consistent with SQLite implementation.
    __slots__ = ("_data", "_buffer")

    def __init__(self, data: Optional[MutableMapping[bytes, bytes]] = None) -> None:
        """Initializes the store with an optional existing mapping.

        Args:
            data: An optional dictionary-like object to initialize the store.
        """
        self._data: MutableMapping[bytes, bytes] = data if data is not None else {}
        # The staging area for uncommitted changes.
        self._buffer: Dict[bytes, Optional[bytes]] = {}

    def get(self, key: bytes) -> Optional[bytes]:
        """Retrieves data, checking the uncommitted buffer first."""
        # 1. Read-your-writes consistency: check the buffer first.
        if key in self._buffer:
            return self._buffer[key]
            
        # 2. Fallback to the main storage.
        return self._data.get(key)

    def put(self, key: bytes, value: bytes) -> None:
        """Stages data in the memory buffer.
        
        Data is not moved to the primary storage until :meth:`commit` is called.
        """
        self._buffer[key] = value

    def begin(self) -> None:
        """Starts a new transaction by ensuring the buffer is clean.
        
        In memory-only mode, this mainly serves as a logical boundary.
        """
        # Note: If a previous transaction wasn't committed, 
        # begin() traditionally might throw or clear. We choose to clear.
        self._buffer.clear()

    def commit(self) -> None:
        """Persists all buffered changes to the main in-memory mapping."""
        if self._buffer:
            for key, value in self._buffer.items():
                if value is None:
                    # Handle deletions (Tombstones)
                    self._data.pop(key, None)
                else:
                    self._data[key] = value
            self._buffer.clear()

    def rollback(self) -> None:
        """Discards all changes staged in the buffer."""
        self._buffer.clear()

    def close(self) -> None:
        """No-op for in-memory storage."""
        pass
