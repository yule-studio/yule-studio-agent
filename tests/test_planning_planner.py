from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

from datetime import date, datetime
import unittest

from yule_orchestrator.integrations.calendar.models import CalendarEvent, CalendarTodo
from yule_orchestrator.integrations.github.issues import GitHubIssue
from yule_orchestrator.planning import ReminderItem
from yule_orchestrator.planning.models import PlanningInputs, PlanningSourceStatus
from yule_orchestrator.planning.planner import build_daily_plan, select_due_checkpoints


class PlanningPlannerTestCase(unittest.TestCase):
    def test_build_daily_plan_prioritizes_due_today_todo(self) -> None:
        inputs = PlanningInputs(
            plan_date=date(2026, 4, 22),
            timezone="KST",
            source_statuses=[
                PlanningSourceStatus(source_id="calendar", source_type="calendar", ok=True, item_count=2),
                PlanningSourceStatus(source_id="github-issues", source_type="github", ok=True, item_count=1),
                PlanningSourceStatus(source_id="reminders", source_type="reminder", ok=True, item_count=1),
            ],
            warnings=[],
            calendar_events=[
                CalendarEvent(
                    item_uid="event-1",
                    title="업무 수행",
                    start="2026-04-22T09:00:00+09:00",
                    end="2026-04-22T12:00:00+09:00",
                    all_day=False,
                    calendar_name="내 캘린더",
                    source="naver-caldav",
                    description="",
                    last_modified=None,
                )
            ],
            calendar_todos=[
                CalendarTodo(
                    item_uid="todo-1",
                    title="오늘 해야 할 업무",
                    start=None,
                    due="2026-04-22",
                    start_all_day=False,
                    due_all_day=True,
                    status="NEEDS-ACTION",
                    completed=False,
                    completed_at=None,
                    priority=0,
                    percent_complete=None,
                    calendar_name="내 할 일",
                    source="naver-caldav",
                    description="오늘 마감",
                    last_modified=None,
                )
            ],
            github_issues=[
                GitHubIssue(
                    number=12,
                    repository="yule-studio/yule-studio-agent",
                    title="Planning Agent 입력/출력 포맷 정의",
                    url="https://github.com/yule-studio/yule-studio-agent/issues/12",
                    owner="yule-studio",
                    scope="org:yule-studio",
                )
            ],
            reminders=[
                ReminderItem(
                    item_id="review-java",
                    title="Java 복습",
                    description="record 복습",
                    due_date="2026-04-23",
                    priority_hint="medium",
                    estimated_minutes=30,
                    tags=["review", "java"],
                )
            ],
        )

        envelope = build_daily_plan(inputs)
        plan = envelope.daily_plan

        self.assertEqual(plan.prioritized_tasks[0].task_id, "todo:todo-1")
        self.assertGreaterEqual(plan.summary.available_focus_minutes, 30)
        self.assertTrue(any(task.source_type == "github_issue" for task in plan.coding_agent_handoff))
        self.assertTrue(plan.discord_briefing)
        self.assertEqual(plan.briefing_source, "rules")

    def test_build_daily_plan_creates_focus_blocks(self) -> None:
        inputs = PlanningInputs(
            plan_date=date(2026, 4, 22),
            timezone="KST",
            source_statuses=[],
            warnings=[],
            calendar_events=[],
            calendar_todos=[
                CalendarTodo(
                    item_uid="todo-2",
                    title="문서 정리",
                    start=None,
                    due="2026-04-22",
                    start_all_day=False,
                    due_all_day=True,
                    status="NEEDS-ACTION",
                    completed=False,
                    completed_at=None,
                    priority=0,
                    percent_complete=None,
                    calendar_name="내 할 일",
                    source="naver-caldav",
                    description="설계 문서 보강",
                    last_modified=None,
                )
            ],
            github_issues=[],
            reminders=[],
        )

        envelope = build_daily_plan(inputs)
        self.assertTrue(envelope.daily_plan.suggested_time_blocks)

    def test_build_daily_plan_parses_execution_blocks_and_checkpoints(self) -> None:
        inputs = PlanningInputs(
            plan_date=date(2026, 4, 22),
            timezone="KST",
            source_statuses=[],
            warnings=[],
            calendar_events=[
                CalendarEvent(
                    item_uid="event-2",
                    title="업무 수행",
                    start="2026-04-22T09:00:00+09:00",
                    end="2026-04-22T13:00:00+09:00",
                    all_day=False,
                    calendar_name="내 캘린더",
                    source="naver-caldav",
                    description="- 9시 ~ 10시 : 할일 목록 정리\n- 10 ~ 1시 : 업무 수행 (회의 없음)",
                    last_modified=None,
                )
            ],
            calendar_todos=[],
            github_issues=[],
            reminders=[],
        )

        envelope = build_daily_plan(inputs, reminder_lead_minutes=5)
        plan = envelope.daily_plan

        self.assertEqual(len(plan.execution_blocks), 2)
        self.assertEqual(plan.execution_blocks[0].title, "할일 목록 정리")
        self.assertEqual(plan.execution_blocks[1].start, "2026-04-22T10:00:00+09:00")
        self.assertEqual(plan.execution_blocks[1].end, "2026-04-22T13:00:00+09:00")
        self.assertEqual(len(plan.checkpoints), 2)
        self.assertEqual(plan.checkpoints[0].remind_at, "2026-04-22T09:55:00+09:00")
        self.assertIn("업무 수행 (회의 없음)", plan.checkpoints[0].prompt)

        due = select_due_checkpoints(
            plan.checkpoints,
            at=datetime.fromisoformat("2026-04-22T09:50:00+09:00"),
            window_minutes=10,
        )
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].block_title, "할일 목록 정리")
