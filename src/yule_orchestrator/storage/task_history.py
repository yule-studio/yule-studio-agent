from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import time
from typing import Optional

from ._sqlite import SQLITE_WRITE_LOCK

DEFAULT_SQLITE_BUSY_TIMEOUT_MS = 30_000


@dataclass(frozen=True)
class TaskCompletionEvent:
    plan_date: date
    checkpoint_id: str
    status: str
    user_id: int
    responded_at: datetime
    source_event_uid: Optional[str] = None
    source_event_title: Optional[str] = None
    block_title: Optional[str] = None
    checkpoint_kind: Optional[str] = None


@dataclass(frozen=True)
class TaskCompletionStats:
    total_count: int
    done_count: int
    skipped_count: int

    @property
    def done_ratio(self) -> float:
        if self.total_count == 0:
            return 0.0
        return self.done_count / self.total_count


def record_task_completion_event(event: TaskCompletionEvent) -> None:
    db_path = _database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    recorded_at = time.time()

    with SQLITE_WRITE_LOCK, _connect(db_path) as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT INTO task_completion_events (
                plan_date,
                checkpoint_id,
                source_event_uid,
                source_event_title,
                block_title,
                checkpoint_kind,
                status,
                user_id,
                responded_at,
                recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.plan_date.isoformat(),
                event.checkpoint_id,
                event.source_event_uid,
                event.source_event_title,
                event.block_title,
                event.checkpoint_kind,
                event.status,
                event.user_id,
                event.responded_at.isoformat(),
                recorded_at,
            ),
        )


def query_task_completion_stats(
    *,
    user_id: Optional[int] = None,
    source_event_title: Optional[str] = None,
    checkpoint_kind: Optional[str] = None,
    days_back: Optional[int] = 30,
    reference_time: Optional[datetime] = None,
) -> TaskCompletionStats:
    db_path = _database_path()
    if not db_path.exists():
        return TaskCompletionStats(total_count=0, done_count=0, skipped_count=0)

    conditions: list[str] = []
    params: list[object] = []

    if user_id is not None:
        conditions.append("user_id = ?")
        params.append(user_id)
    if source_event_title is not None:
        conditions.append("source_event_title = ?")
        params.append(source_event_title)
    if checkpoint_kind is not None:
        conditions.append("checkpoint_kind = ?")
        params.append(checkpoint_kind)
    if days_back is not None and days_back > 0:
        now = reference_time or datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=days_back)).date().isoformat()
        conditions.append("plan_date >= ?")
        params.append(cutoff)

    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""

    with SQLITE_WRITE_LOCK, _connect(db_path) as connection:
        _ensure_schema(connection)
        row = connection.execute(
            f"""
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done_count,
                SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) AS skipped_count
            FROM task_completion_events
            {where_clause}
            """,
            tuple(params),
        ).fetchone()

    if row is None:
        return TaskCompletionStats(total_count=0, done_count=0, skipped_count=0)
    return TaskCompletionStats(
        total_count=int(row["total_count"] or 0),
        done_count=int(row["done_count"] or 0),
        skipped_count=int(row["skipped_count"] or 0),
    )


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS task_completion_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_date TEXT NOT NULL,
            checkpoint_id TEXT NOT NULL,
            source_event_uid TEXT,
            source_event_title TEXT,
            block_title TEXT,
            checkpoint_kind TEXT,
            status TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            responded_at TEXT NOT NULL,
            recorded_at REAL NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_completion_events_user_status
        ON task_completion_events (user_id, status, plan_date)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_completion_events_source_event
        ON task_completion_events (source_event_title, plan_date)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_completion_events_kind
        ON task_completion_events (checkpoint_kind, plan_date)
        """
    )


def _connect(db_path: Path) -> sqlite3.Connection:
    busy_timeout_ms = _sqlite_busy_timeout_ms()
    connection = sqlite3.connect(db_path, timeout=busy_timeout_ms / 1000)
    connection.row_factory = sqlite3.Row
    connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
    _try_sqlite_pragma(connection, "PRAGMA journal_mode = WAL")
    _try_sqlite_pragma(connection, "PRAGMA synchronous = NORMAL")
    return connection


def _sqlite_busy_timeout_ms() -> int:
    configured_value = os.getenv("YULE_SQLITE_BUSY_TIMEOUT_MS")
    if configured_value and configured_value.strip():
        try:
            return max(1000, int(configured_value.strip()))
        except ValueError:
            return DEFAULT_SQLITE_BUSY_TIMEOUT_MS
    return DEFAULT_SQLITE_BUSY_TIMEOUT_MS


def _try_sqlite_pragma(connection: sqlite3.Connection, statement: str) -> None:
    try:
        connection.execute(statement)
    except sqlite3.OperationalError:
        pass


def _database_path() -> Path:
    configured_path = os.getenv("YULE_CACHE_DB_PATH")
    if configured_path and configured_path.strip():
        return Path(configured_path).expanduser()

    repo_root = os.getenv("YULE_REPO_ROOT")
    base_dir = Path(repo_root) if repo_root else Path.cwd()
    return base_dir / ".cache" / "yule" / "cache.sqlite3"
