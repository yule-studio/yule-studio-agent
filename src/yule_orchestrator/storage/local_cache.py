from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class LocalCacheEntry:
    namespace: str
    cache_key: str
    provider: str
    range_start: Optional[str]
    range_end: Optional[str]
    scope_hash: str
    payload: dict[str, Any]
    metadata: dict[str, Any]
    fetched_at: float
    expires_at: float
    last_accessed_at: float


def load_json_cache(
    namespace: str,
    cache_key: str,
    ttl_seconds: Optional[int] = None,
) -> Optional[LocalCacheEntry]:
    db_path = _database_path()
    if not db_path.exists():
        return None

    with _connect(db_path) as connection:
        _ensure_schema(connection)
        row = connection.execute(
            """
            SELECT
                namespace,
                cache_key,
                provider,
                range_start,
                range_end,
                scope_hash,
                payload_json,
                metadata_json,
                fetched_at,
                expires_at,
                last_accessed_at
            FROM local_cache_entries
            WHERE namespace = ? AND cache_key = ?
            """,
            (namespace, cache_key),
        ).fetchone()
        if row is None:
            return None

        now = time.time()
        fetched_at = float(row["fetched_at"])
        expires_at = float(row["expires_at"])

        if expires_at <= now:
            connection.execute(
                "DELETE FROM local_cache_entries WHERE namespace = ? AND cache_key = ?",
                (namespace, cache_key),
            )
            return None

        if ttl_seconds is not None and ttl_seconds >= 0 and fetched_at + ttl_seconds <= now:
            return None

        payload = _deserialize_json_object(row["payload_json"])
        if payload is None:
            return None

        metadata = _deserialize_json_object(row["metadata_json"]) or {}
        connection.execute(
            """
            UPDATE local_cache_entries
            SET last_accessed_at = ?
            WHERE namespace = ? AND cache_key = ?
            """,
            (now, namespace, cache_key),
        )
        return LocalCacheEntry(
            namespace=row["namespace"],
            cache_key=row["cache_key"],
            provider=row["provider"],
            range_start=row["range_start"],
            range_end=row["range_end"],
            scope_hash=row["scope_hash"],
            payload=payload,
            metadata=metadata,
            fetched_at=fetched_at,
            expires_at=expires_at,
            last_accessed_at=now,
        )


def save_json_cache(
    namespace: str,
    cache_key: str,
    provider: str,
    range_start: Optional[str],
    range_end: Optional[str],
    scope_hash: str,
    ttl_seconds: int,
    payload: Mapping[str, Any],
    metadata: Optional[Mapping[str, Any]] = None,
) -> None:
    if ttl_seconds <= 0:
        return

    db_path = _database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    now = time.time()
    expires_at = now + ttl_seconds

    with _connect(db_path) as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT INTO local_cache_entries (
                namespace,
                cache_key,
                provider,
                range_start,
                range_end,
                scope_hash,
                payload_json,
                metadata_json,
                fetched_at,
                expires_at,
                last_accessed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(namespace, cache_key) DO UPDATE SET
                provider = excluded.provider,
                range_start = excluded.range_start,
                range_end = excluded.range_end,
                scope_hash = excluded.scope_hash,
                payload_json = excluded.payload_json,
                metadata_json = excluded.metadata_json,
                fetched_at = excluded.fetched_at,
                expires_at = excluded.expires_at,
                last_accessed_at = excluded.last_accessed_at
            """,
            (
                namespace,
                cache_key,
                provider,
                range_start,
                range_end,
                scope_hash,
                json.dumps(dict(payload), ensure_ascii=False, sort_keys=True),
                json.dumps(dict(metadata or {}), ensure_ascii=False, sort_keys=True),
                now,
                expires_at,
                now,
            ),
        )
        connection.execute(
            "DELETE FROM local_cache_entries WHERE expires_at <= ?",
            (now,),
        )


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS local_cache_entries (
            namespace TEXT NOT NULL,
            cache_key TEXT NOT NULL,
            provider TEXT NOT NULL,
            range_start TEXT,
            range_end TEXT,
            scope_hash TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            metadata_json TEXT,
            fetched_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            last_accessed_at REAL NOT NULL,
            PRIMARY KEY(namespace, cache_key)
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_local_cache_entries_expires_at
        ON local_cache_entries (expires_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_local_cache_entries_namespace_range
        ON local_cache_entries (namespace, range_start, range_end)
        """
    )


def _database_path() -> Path:
    configured_path = os.getenv("YULE_CACHE_DB_PATH")
    if configured_path and configured_path.strip():
        return Path(configured_path).expanduser()

    repo_root = os.getenv("YULE_REPO_ROOT")
    base_dir = Path(repo_root) if repo_root else Path.cwd()
    return base_dir / ".cache" / "yule" / "cache.sqlite3"


def _deserialize_json_object(value: Optional[str]) -> Optional[dict[str, Any]]:
    if value is None:
        return {}

    try:
        data = json.loads(value)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    return data
