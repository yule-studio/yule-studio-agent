from __future__ import annotations

import os
from pathlib import Path
import shutil
import sqlite3
import time
import unittest

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401
from yule_orchestrator.storage import (
    cleanup_json_cache,
    list_json_cache_entries,
    load_json_cache,
    save_json_cache,
)


class LocalCacheTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path("tests/.tmp/local-cache-tests")
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.temp_dir / "cache.sqlite3"
        self.previous_db_path = os.environ.get("YULE_CACHE_DB_PATH")
        os.environ["YULE_CACHE_DB_PATH"] = str(self.db_path)

    def tearDown(self) -> None:
        if self.previous_db_path is None:
            os.environ.pop("YULE_CACHE_DB_PATH", None)
        else:
            os.environ["YULE_CACHE_DB_PATH"] = self.previous_db_path
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_load_json_cache_returns_fresh_entry(self) -> None:
        save_json_cache(
            namespace="calendar-query-results",
            cache_key="fresh-entry",
            provider="naver-caldav",
            range_start="2026-04-22",
            range_end="2026-04-22",
            scope_hash="scope-1",
            ttl_seconds=60,
            payload={"value": 1},
            metadata={"todo_count": 2},
        )

        entry = load_json_cache("calendar-query-results", "fresh-entry", ttl_seconds=60)
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertFalse(entry.is_stale)
        self.assertEqual(entry.payload["value"], 1)
        self.assertEqual(entry.metadata["todo_count"], 2)

    def test_allow_stale_returns_expired_entry(self) -> None:
        save_json_cache(
            namespace="calendar-query-results",
            cache_key="stale-entry",
            provider="naver-caldav",
            range_start="2026-04-22",
            range_end="2026-04-22",
            scope_hash="scope-2",
            ttl_seconds=60,
            payload={"value": 2},
        )

        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE local_cache_entries SET expires_at = ?, fetched_at = ? WHERE namespace = ? AND cache_key = ?",
                (
                    time.time() - 10,
                    time.time() - 10,
                    "calendar-query-results",
                    "stale-entry",
                ),
            )

        fresh_entry = load_json_cache("calendar-query-results", "stale-entry", ttl_seconds=60)
        stale_entry = load_json_cache(
            "calendar-query-results",
            "stale-entry",
            ttl_seconds=60,
            allow_stale=True,
        )

        self.assertIsNone(fresh_entry)
        self.assertIsNotNone(stale_entry)
        assert stale_entry is not None
        self.assertTrue(stale_entry.is_stale)

    def test_cleanup_json_cache_deletes_old_expired_entries(self) -> None:
        save_json_cache(
            namespace="calendar-query-results",
            cache_key="cleanup-entry",
            provider="naver-caldav",
            range_start="2026-04-22",
            range_end="2026-04-22",
            scope_hash="scope-3",
            ttl_seconds=60,
            payload={"value": 3},
        )

        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE local_cache_entries SET expires_at = ? WHERE namespace = ? AND cache_key = ?",
                (
                    time.time() - 100,
                    "calendar-query-results",
                    "cleanup-entry",
                ),
            )

        deleted_count = cleanup_json_cache(
            namespace="calendar-query-results",
            stale_retention_seconds=0,
        )
        entries = list_json_cache_entries(namespace="calendar-query-results")

        self.assertEqual(deleted_count, 1)
        self.assertEqual(entries, [])

    def test_shorter_runtime_ttl_marks_cache_as_stale(self) -> None:
        save_json_cache(
            namespace="calendar-query-results",
            cache_key="runtime-ttl-entry",
            provider="naver-caldav",
            range_start="2026-04-22",
            range_end="2026-04-22",
            scope_hash="scope-4",
            ttl_seconds=3600,
            payload={"value": 4},
        )

        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE local_cache_entries SET fetched_at = ? WHERE namespace = ? AND cache_key = ?",
                (
                    time.time() - 120,
                    "calendar-query-results",
                    "runtime-ttl-entry",
                ),
            )

        fresh_entry = load_json_cache("calendar-query-results", "runtime-ttl-entry", ttl_seconds=3600)
        stale_entry = load_json_cache("calendar-query-results", "runtime-ttl-entry", ttl_seconds=60)

        self.assertIsNotNone(fresh_entry)
        self.assertIsNone(stale_entry)
