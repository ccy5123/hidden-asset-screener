"""SQLite key-value cache with TTL (SPEC-CORE-001, AC-2).

Tracks ``hits``/``misses`` so tests can assert "the second identical request did NOT
touch the external API". Pass ``":memory:"`` for an ephemeral test store.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional, Union


class CacheStore:
    def __init__(self, path: Union[str, Path] = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS kv (
                namespace TEXT NOT NULL,
                key       TEXT NOT NULL,
                value     TEXT NOT NULL,
                created_at REAL NOT NULL,
                ttl       REAL,
                PRIMARY KEY (namespace, key)
            )
            """
        )
        self._conn.commit()
        self.hits = 0
        self.misses = 0

    def _now(self) -> float:
        return time.time()

    def get(self, namespace: str, key: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT value, created_at, ttl FROM kv WHERE namespace=? AND key=?",
            (namespace, key),
        ).fetchone()
        if row is None:
            self.misses += 1
            return None
        value, created_at, ttl = row
        if ttl is not None and self._now() - created_at > ttl:
            self.invalidate(namespace, key)
            self.misses += 1
            return None
        self.hits += 1
        return value

    def set(self, namespace: str, key: str, value: str, ttl: Optional[float] = None) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO kv (namespace, key, value, created_at, ttl) "
            "VALUES (?, ?, ?, ?, ?)",
            (namespace, key, value, self._now(), ttl),
        )
        self._conn.commit()

    def get_json(self, namespace: str, key: str) -> Optional[Any]:
        raw = self.get(namespace, key)
        return None if raw is None else json.loads(raw)

    def set_json(self, namespace: str, key: str, value: Any, ttl: Optional[float] = None) -> None:
        self.set(namespace, key, json.dumps(value, ensure_ascii=False, default=str), ttl)

    def invalidate(self, namespace: str, key: Optional[str] = None) -> None:
        if key is None:
            self._conn.execute("DELETE FROM kv WHERE namespace=?", (namespace,))
        else:
            self._conn.execute("DELETE FROM kv WHERE namespace=? AND key=?", (namespace, key))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "CacheStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
