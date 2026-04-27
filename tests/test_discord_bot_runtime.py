from __future__ import annotations

import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

from yule_orchestrator.discord.bot import (
    _checkpoint_window_minutes,
    _filter_unsent_checkpoints,
    _mark_checkpoints_sent,
    _next_checkpoint_scan,
    _resolve_due_checkpoints,
)
from yule_orchestrator.discord.planning_runtime import (
    build_due_checkpoints,
    load_prefetched_due_checkpoints,
    prefetch_checkpoint_snapshots,
)
from yule_orchestrator.planning.models import PlanningCheckpoint


class DiscordBotRuntimeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path("tests/.tmp/discord-bot-runtime")
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
        try:
            self.temp_dir.mkdir(parents=True, exist_ok=True)
        except (FileNotFoundError, PermissionError) as exc:
            self.skipTest(f"temporary directory is not writable in this environment: {exc}")
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

    def test_next_checkpoint_scan_rounds_up_to_next_minute(self) -> None:
        current = self._dt("2026-04-22T09:55:12+09:00")

        next_scan = _next_checkpoint_scan(current)

        self.assertEqual(next_scan, self._dt("2026-04-22T09:56:00+09:00"))

    def test_checkpoint_window_minutes_rounds_partial_minute_up(self) -> None:
        start = self._dt("2026-04-22T09:55:00+09:00")
        end = self._dt("2026-04-22T09:56:01+09:00")

        self.assertEqual(_checkpoint_window_minutes(start, end), 2)

    def test_filter_unsent_checkpoints_uses_local_cache(self) -> None:
        first = self._checkpoint("checkpoint-1", "2026-04-22T09:55:00+09:00")
        second = self._checkpoint("checkpoint-2", "2026-04-22T10:55:00+09:00")
        _mark_checkpoints_sent(555, [first])

        unsent = _filter_unsent_checkpoints(555, [first, second])

        self.assertEqual([checkpoint.checkpoint_id for checkpoint in unsent], ["checkpoint-2"])

    @patch("yule_orchestrator.discord.planning_runtime.load_daily_plan_snapshot")
    def test_build_due_checkpoints_scans_across_midnight(
        self,
        load_daily_plan_snapshot_mock,
    ) -> None:
        first_day = self._checkpoint("checkpoint-1", "2026-04-22T23:59:00+09:00")
        second_day = self._checkpoint("checkpoint-2", "2026-04-23T00:01:00+09:00")

        load_daily_plan_snapshot_mock.side_effect = [
            self._snapshot([first_day]),
            self._snapshot([second_day]),
        ]

        due = build_due_checkpoints(
            self._dt("2026-04-22T23:58:00+09:00"),
            window_minutes=5,
        )

        self.assertEqual(
            [checkpoint.checkpoint_id for checkpoint in due],
            ["checkpoint-1", "checkpoint-2"],
        )
        self.assertEqual(load_daily_plan_snapshot_mock.call_count, 2)

    @patch("yule_orchestrator.discord.bot.build_due_checkpoints")
    @patch("yule_orchestrator.discord.bot.load_prefetched_due_checkpoints")
    def test_resolve_due_checkpoints_prefers_prefetched_snapshots(
        self,
        load_prefetched_due_checkpoints_mock,
        build_due_checkpoints_mock,
    ) -> None:
        checkpoint = self._checkpoint("checkpoint-1", "2026-04-22T09:55:00+09:00")
        load_prefetched_due_checkpoints_mock.return_value = ([checkpoint], True)

        resolved = _resolve_due_checkpoints(
            self._dt("2026-04-22T09:54:00+09:00"),
            self._dt("2026-04-22T09:55:00+09:00"),
        )

        self.assertEqual([item.checkpoint_id for item in resolved], ["checkpoint-1"])
        build_due_checkpoints_mock.assert_not_called()

    @patch("yule_orchestrator.discord.planning_runtime.build_daily_checkpoints_for_date")
    def test_prefetch_checkpoint_snapshots_can_be_loaded_without_live_fetch(
        self,
        build_daily_checkpoints_for_date_mock,
    ) -> None:
        build_daily_checkpoints_for_date_mock.return_value = [
            self._checkpoint("checkpoint-1", "2026-04-22T09:55:00+09:00")
        ]

        prefetch_checkpoint_snapshots(
            self._dt("2026-04-22T09:50:00+09:00"),
            prefetch_minutes=5,
        )
        loaded, cache_complete = load_prefetched_due_checkpoints(
            self._dt("2026-04-22T09:54:00+09:00"),
            self._dt("2026-04-22T09:55:00+09:00"),
        )

        self.assertTrue(cache_complete)
        self.assertEqual([item.checkpoint_id for item in loaded], ["checkpoint-1"])

    @staticmethod
    def _dt(value: str):
        from datetime import datetime

        return datetime.fromisoformat(value)

    @staticmethod
    def _checkpoint(checkpoint_id: str, remind_at: str) -> PlanningCheckpoint:
        return PlanningCheckpoint(
            checkpoint_id=checkpoint_id,
            remind_at=remind_at,
            source_event_uid="event-1",
            source_event_title="업무 수행",
            block_id="block-1",
            block_title="업무 수행",
            block_start="2026-04-22T09:00:00+09:00",
            block_end="2026-04-22T10:00:00+09:00",
            prompt="업무 수행 마무리됐는지 확인해 주세요.",
        )

    @staticmethod
    def _snapshot(checkpoints: list[PlanningCheckpoint]):
        class DailyPlan:
            def __init__(self, due_checkpoints: list[PlanningCheckpoint]) -> None:
                self.checkpoints = due_checkpoints

        class Envelope:
            def __init__(self, due_checkpoints: list[PlanningCheckpoint]) -> None:
                self.daily_plan = DailyPlan(due_checkpoints)

        class Snapshot:
            def __init__(self, due_checkpoints: list[PlanningCheckpoint]) -> None:
                self.envelope = Envelope(due_checkpoints)

        return Snapshot(checkpoints)
