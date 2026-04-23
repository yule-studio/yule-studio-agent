from __future__ import annotations

from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import patch

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

from yule_orchestrator.planning.inputs import collect_planning_inputs


class PlanningInputsTestCase(unittest.TestCase):
    @patch("yule_orchestrator.planning.inputs.list_naver_calendar_items")
    @patch("yule_orchestrator.planning.inputs.list_calendar_state_records")
    def test_collect_planning_inputs_prefers_local_calendar_state(
        self,
        list_calendar_state_records_mock,
        list_naver_calendar_items_mock,
    ) -> None:
        list_calendar_state_records_mock.return_value = [
            SimpleNamespace(
                item_type="todo",
                payload={
                    "item_uid": "todo-1",
                    "title": "오늘 해야 할 업무",
                    "start": None,
                    "due": "2026-04-23",
                    "start_all_day": False,
                    "due_all_day": True,
                    "status": "NEEDS-ACTION",
                    "completed": False,
                    "completed_at": None,
                    "priority": None,
                    "percent_complete": None,
                    "calendar_name": "내 할 일",
                    "source": "naver-caldav",
                    "description": "",
                    "last_modified": None,
                    "category_color": "27",
                },
            )
        ]

        inputs = collect_planning_inputs(
            plan_date=date(2026, 4, 23),
            include_calendar=True,
            include_github=False,
            reminders=[],
        )

        list_naver_calendar_items_mock.assert_not_called()
        self.assertEqual(len(inputs.calendar_todos), 1)
        self.assertEqual(inputs.calendar_todos[0].category_color, "27")
        self.assertEqual(inputs.source_statuses[0].source_id, "calendar-state")

    @patch("yule_orchestrator.planning.inputs.list_naver_calendar_items")
    @patch("yule_orchestrator.planning.inputs.list_calendar_state_records")
    def test_collect_planning_inputs_fetches_calendar_when_state_is_empty(
        self,
        list_calendar_state_records_mock,
        list_naver_calendar_items_mock,
    ) -> None:
        list_calendar_state_records_mock.return_value = []
        list_naver_calendar_items_mock.return_value = SimpleNamespace(events=[], todos=[])

        inputs = collect_planning_inputs(
            plan_date=date(2026, 4, 23),
            include_calendar=True,
            include_github=False,
            reminders=[],
        )

        list_naver_calendar_items_mock.assert_called_once_with(date(2026, 4, 23), date(2026, 4, 23))
        self.assertEqual(inputs.source_statuses[0].source_id, "calendar")
