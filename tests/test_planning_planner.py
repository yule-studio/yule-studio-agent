from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

from datetime import date, datetime
import unittest
from unittest.mock import patch

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
        self.assertTrue(plan.morning_briefing)
        self.assertIn("추천 작업", plan.morning_briefing)
        self.assertIn("초반 흐름", plan.morning_briefing)
        self.assertTrue(plan.time_block_briefings)
        self.assertTrue(any(briefing.block_type == "focus_block" for briefing in plan.time_block_briefings))
        self.assertEqual(plan.morning_briefing_source, "rules")
        self.assertEqual(plan.discord_briefing_source, "rules")

    @patch.dict("os.environ", {"YULE_WORK_START_TIME": "09:00"}, clear=False)
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
        self.assertTrue(envelope.daily_plan.suggested_time_blocks[0].start.endswith("09:00:00+09:00"))
        self.assertIn("오늘의 전체 일정을 작성", envelope.daily_plan.morning_briefing)

    @patch.dict(
        "os.environ",
        {
            "YULE_WAKE_TIME": "06:00",
            "YULE_WORK_START_TIME": "09:00",
            "YULE_COMMUTE_MINUTES": "45",
            "YULE_DEPARTURE_BUFFER_MINUTES": "10",
            "YULE_HOME_AREA": "신정동",
            "YULE_WORK_AREA": "마곡",
        },
        clear=False,
    )
    def test_morning_briefing_includes_commute_ready_flow(self) -> None:
        inputs = PlanningInputs(
            plan_date=date(2026, 4, 22),
            timezone="KST",
            source_statuses=[],
            warnings=[],
            calendar_events=[],
            calendar_todos=[],
            github_issues=[],
            reminders=[],
        )

        envelope = build_daily_plan(inputs)

        self.assertIn("06:00 기상 기준", envelope.daily_plan.morning_briefing)
        self.assertIn("신정동에서 마곡까지", envelope.daily_plan.morning_briefing)
        self.assertIn("08:05 전후 출발", envelope.daily_plan.morning_briefing)
        self.assertIn("09:00에는 업무를 바로 시작", envelope.daily_plan.morning_briefing)

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
        self.assertEqual(len(plan.time_block_briefings), 2)
        self.assertEqual(plan.time_block_briefings[0].title, "할일 목록 정리")
        self.assertIn("10:00부터", plan.time_block_briefings[0].briefing)
        self.assertEqual(len(plan.checkpoints), 3)
        self.assertEqual(plan.checkpoints[0].kind, "event_rebriefing")
        self.assertEqual(plan.checkpoints[0].remind_at, "2026-04-22T08:50:00+09:00")
        self.assertIn("일정 설명에 적어둔 세부 흐름", plan.checkpoints[0].prompt)
        self.assertEqual(plan.checkpoints[1].remind_at, "2026-04-22T09:55:00+09:00")
        self.assertIn("업무 수행 (회의 없음)", plan.checkpoints[1].prompt)
        self.assertIn("남은 핵심 한 가지", plan.checkpoints[1].prompt)

        due = select_due_checkpoints(
            plan.checkpoints,
            at=datetime.fromisoformat("2026-04-22T09:50:00+09:00"),
            window_minutes=10,
        )
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].block_title, "할일 목록 정리")

    def test_build_daily_plan_adds_missing_event_plan_checkpoint(self) -> None:
        inputs = PlanningInputs(
            plan_date=date(2026, 4, 22),
            timezone="KST",
            source_statuses=[],
            warnings=[],
            calendar_events=[
                CalendarEvent(
                    item_uid="event-empty-description",
                    title="업무 수행",
                    start="2026-04-22T09:00:00+09:00",
                    end="2026-04-22T10:00:00+09:00",
                    all_day=False,
                    calendar_name="내 캘린더",
                    source="naver-caldav",
                    description="",
                    last_modified=None,
                )
            ],
            calendar_todos=[],
            github_issues=[],
            reminders=[],
        )

        envelope = build_daily_plan(inputs)
        plan = envelope.daily_plan

        self.assertEqual(len(plan.checkpoints), 1)
        self.assertEqual(plan.checkpoints[0].kind, "missing_event_plan")
        self.assertEqual(plan.checkpoints[0].remind_at, "2026-04-22T08:50:00+09:00")
        self.assertIn("세부 계획을 작성", plan.checkpoints[0].prompt)

    def test_build_daily_plan_keeps_focus_blocks_in_event_timezone(self) -> None:
        inputs = PlanningInputs(
            plan_date=date(2026, 4, 22),
            timezone="UTC",
            source_statuses=[],
            warnings=[],
            calendar_events=[
                CalendarEvent(
                    item_uid="event-utc",
                    title="UTC 업무",
                    start="2026-04-22T09:00:00+00:00",
                    end="2026-04-22T12:00:00+00:00",
                    all_day=False,
                    calendar_name="UTC 캘린더",
                    source="naver-caldav",
                    description="",
                    last_modified=None,
                )
            ],
            calendar_todos=[
                CalendarTodo(
                    item_uid="todo-utc",
                    title="오늘 문서 정리",
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
                    description="UTC 기준으로 집중 블록 생성",
                    last_modified=None,
                )
            ],
            github_issues=[],
            reminders=[],
        )

        envelope = build_daily_plan(inputs)
        self.assertTrue(envelope.daily_plan.suggested_time_blocks)
        self.assertTrue(envelope.daily_plan.suggested_time_blocks[0].start.endswith("+00:00"))

    def test_reminder_item_from_dict_normalizes_optional_strings(self) -> None:
        reminder = ReminderItem.from_dict(
            {
                "item_id": "reminder-1",
                "title": "복습",
                "due_date": 20260422,
                "priority_hint": 1,
                "estimated_minutes": 45,
            }
        )

        self.assertEqual(reminder.due_date, "20260422")
        self.assertEqual(reminder.priority_hint, "1")
        self.assertEqual(reminder.estimated_minutes, 45)

    def test_reminder_item_from_dict_rejects_invalid_estimated_minutes(self) -> None:
        with self.assertRaises(ValueError):
            ReminderItem.from_dict(
                {
                    "item_id": "reminder-2",
                    "title": "복습",
                    "estimated_minutes": "soon",
                }
            )
