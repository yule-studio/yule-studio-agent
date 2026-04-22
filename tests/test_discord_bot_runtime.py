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
)
from yule_orchestrator.discord.planning_runtime import build_due_checkpoints
from yule_orchestrator.planning.models import PlanningCheckpoint


class DiscordBotRuntimeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path("tests/.tmp/discord-bot-runtime")
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

    @patch("yule_orchestrator.discord.planning_runtime.collect_planning_inputs")
    @patch("yule_orchestrator.discord.planning_runtime.build_daily_plan")
    def test_build_due_checkpoints_scans_across_midnight(
        self,
        build_daily_plan_mock,
        collect_inputs_mock,
    ) -> None:
        first_day = self._checkpoint("checkpoint-1", "2026-04-22T23:59:00+09:00")
        second_day = self._checkpoint("checkpoint-2", "2026-04-23T00:01:00+09:00")

        build_daily_plan_mock.side_effect = [
            self._envelope([first_day]),
            self._envelope([second_day]),
        ]

        due = build_due_checkpoints(
            self._dt("2026-04-22T23:58:00+09:00"),
            window_minutes=5,
        )

        self.assertEqual(
            [checkpoint.checkpoint_id for checkpoint in due],
            ["checkpoint-1", "checkpoint-2"],
        )
        self.assertEqual(collect_inputs_mock.call_count, 2)

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
    def _envelope(checkpoints: list[PlanningCheckpoint]):
        class Envelope:
            class DailyPlan:
                def __init__(self, due_checkpoints: list[PlanningCheckpoint]) -> None:
                    self.checkpoints = due_checkpoints

            def __init__(self, due_checkpoints: list[PlanningCheckpoint]) -> None:
                self.daily_plan = self.DailyPlan(due_checkpoints)

        return Envelope(checkpoints)
