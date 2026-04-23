from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from yule_orchestrator.cli.daily import run_daily_warmup_command


class DailyWarmupTestCase(unittest.TestCase):
    @patch("yule_orchestrator.cli.daily.save_runtime_metric_run")
    @patch("yule_orchestrator.cli.daily.save_daily_plan_snapshot")
    @patch("yule_orchestrator.cli.daily.build_daily_plan")
    @patch("yule_orchestrator.cli.daily.collect_planning_inputs")
    @patch("yule_orchestrator.cli.daily.load_reminder_items")
    @patch("yule_orchestrator.cli.daily.list_open_issues")
    @patch("yule_orchestrator.cli.daily.list_naver_calendar_items")
    def test_daily_warmup_syncs_sources_and_saves_snapshot(
        self,
        list_naver_calendar_items_mock,
        list_open_issues_mock,
        load_reminder_items_mock,
        collect_planning_inputs_mock,
        build_daily_plan_mock,
        save_daily_plan_snapshot_mock,
        save_runtime_metric_run_mock,
    ) -> None:
        list_naver_calendar_items_mock.return_value = SimpleNamespace(events=[object()], todos=[object()], metrics={})
        list_open_issues_mock.return_value = [object()]
        load_reminder_items_mock.return_value = []
        collect_planning_inputs_mock.return_value = object()
        build_daily_plan_mock.return_value = SimpleNamespace(
            daily_plan=SimpleNamespace(
                summary=SimpleNamespace(recommended_task_count=3),
                checkpoints=[object(), object()],
            )
        )
        save_daily_plan_snapshot_mock.return_value = SimpleNamespace(
            cache_key="snapshot-key",
            generated_at=datetime.fromisoformat("2026-04-23T05:58:00+09:00"),
        )
        save_runtime_metric_run_mock.return_value = {
            "run_id": "daily-warmup:1",
            "steps": [],
        }

        stdout = StringIO()
        with redirect_stdout(stdout):
            exit_code = run_daily_warmup_command(
                date_text="2026-04-23",
                github_limit=20,
                reminders_file=None,
                skip_calendar=False,
                skip_github=False,
                force_refresh=True,
                reminder_lead_minutes=5,
                json_output=True,
            )

        self.assertEqual(exit_code, 0)
        list_naver_calendar_items_mock.assert_called_once()
        self.assertTrue(list_naver_calendar_items_mock.call_args.kwargs["force_refresh"])
        list_open_issues_mock.assert_called_once_with(limit=20, force_refresh=True)
        save_daily_plan_snapshot_mock.assert_called_once()
        save_runtime_metric_run_mock.assert_called_once()
        self.assertIn('"action": "daily_warmup"', stdout.getvalue())
        self.assertIn('"snapshot-key"', stdout.getvalue())
