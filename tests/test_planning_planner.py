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
from yule_orchestrator.planning.briefings import normalize_paragraph_spacing
from yule_orchestrator.planning.ollama import _build_prompt
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
        self.assertEqual(
            [briefing.briefing_type for briefing in plan.briefings],
            ["morning", "work_start", "lunch", "evening"],
        )
        self.assertEqual(plan.morning_briefing_source, "rules")
        self.assertEqual(plan.discord_briefing_source, "rules")

    @patch("yule_orchestrator.planning.planner.generate_human_briefing")
    def test_build_daily_plan_can_use_ollama_from_environment(self, generate_human_briefing_mock) -> None:
        generate_human_briefing_mock.return_value = "Ollama가 정리한 아침 브리핑입니다."
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

        with patch.dict(
            "os.environ",
            {
                "OLLAMA_PLANNING_ENABLED": "true",
                "OLLAMA_ENDPOINT": "http://ollama.local:11434",
                "OLLAMA_MODEL": "qwen2.5:3b",
                "OLLAMA_TIMEOUT_SECONDS": "45",
            },
            clear=False,
        ):
            envelope = build_daily_plan(inputs)

        self.assertEqual(envelope.daily_plan.morning_briefing, "Ollama가 정리한 아침 브리핑입니다.")
        self.assertEqual(envelope.daily_plan.morning_briefing_source, "ollama")
        generate_human_briefing_mock.assert_called_once()
        self.assertEqual(generate_human_briefing_mock.call_args.kwargs["endpoint"], "http://ollama.local:11434")
        self.assertEqual(generate_human_briefing_mock.call_args.kwargs["model"], "qwen2.5:3b")
        self.assertEqual(generate_human_briefing_mock.call_args.kwargs["timeout_seconds"], 45)

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
        self.assertEqual(envelope.daily_plan.briefings[0].send_at, "2026-04-22T06:00:00+09:00")

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
        self.assertIn("마감까지 5분 남았습니다", plan.checkpoints[1].prompt)
        self.assertIn("업무 수행 (회의 없음)", plan.checkpoints[1].prompt)

    def test_ollama_prompt_hides_internal_scores_and_iso_timestamps(self) -> None:
        inputs = PlanningInputs(
            plan_date=date(2026, 4, 27),
            timezone="KST",
            source_statuses=[],
            warnings=[],
            calendar_events=[
                CalendarEvent(
                    item_uid="event-1",
                    title="업무 수행",
                    start="2026-04-27T09:00:00+09:00",
                    end="2026-04-27T13:00:00+09:00",
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
                    title="한국사 능력 검정 시험",
                    start=None,
                    due="2026-04-27",
                    start_all_day=False,
                    due_all_day=True,
                    status="NEEDS-ACTION",
                    completed=False,
                    completed_at=None,
                    priority=0,
                    percent_complete=None,
                    calendar_name="내 할 일",
                    source="naver-caldav",
                    description="선사시대 마무리",
                    last_modified=None,
                )
            ],
            github_issues=[],
            reminders=[],
        )

        envelope = build_daily_plan(inputs, use_ollama=False)
        prompt = _build_prompt(
            plan_date=envelope.daily_plan.plan_date.isoformat(),
            summary_line=envelope.daily_plan.discord_briefing,
            fixed_schedule=envelope.daily_plan.fixed_schedule,
            prioritized_tasks=envelope.daily_plan.prioritized_tasks,
            time_block_briefings=envelope.daily_plan.time_block_briefings,
            checkpoints=envelope.daily_plan.checkpoints,
        )

        self.assertNotIn("score=", prompt)
        self.assertNotIn("priority_score", prompt)
        self.assertIn("09:00~13:00", prompt)
        self.assertNotIn("2026-04-27T09:00:00+09:00", prompt)

    def test_build_daily_plan_adds_ten_and_five_minute_execution_checkpoints(self) -> None:
        inputs = PlanningInputs(
            plan_date=date(2026, 4, 22),
            timezone="KST",
            source_statuses=[],
            warnings=[],
            calendar_events=[
                CalendarEvent(
                    item_uid="event-2",
                    title="업무 수행",
                    start="2026-04-22T14:00:00+09:00",
                    end="2026-04-22T18:00:00+09:00",
                    all_day=False,
                    calendar_name="내 캘린더",
                    source="naver-caldav",
                    description=(
                        "2시 ~ 5시 : [Feature] Discord + Ollama 기반 개인 개발 오케스트레이터 구축 마무리\n"
                        "5시 ~ 6시 : OCI 계정 생성 및 yule-lab 구조, docker 설정 마무리 하기"
                    ),
                    last_modified=None,
                )
            ],
            calendar_todos=[],
            github_issues=[],
            reminders=[],
        )

        envelope = build_daily_plan(inputs)
        plan = envelope.daily_plan
        execution_checkpoints = [
            checkpoint for checkpoint in plan.checkpoints if checkpoint.kind == "wrap_up"
        ]

        self.assertEqual(
            [checkpoint.remind_at for checkpoint in execution_checkpoints],
            [
                "2026-04-22T16:50:00+09:00",
                "2026-04-22T16:55:00+09:00",
                "2026-04-22T17:50:00+09:00",
                "2026-04-22T17:55:00+09:00",
            ],
        )
        self.assertIn("마감까지 10분 남았습니다", execution_checkpoints[0].prompt)
        self.assertIn("마감까지 5분 남았습니다", execution_checkpoints[1].prompt)

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

    def test_normalize_paragraph_spacing_inserts_blank_between_prose_paragraphs(self) -> None:
        text = (
            "안녕하세요.\n"
            "오전 9시부터 13시까지는 업무 수행 일정이 있습니다.\n"
            "오후 14시부터는 다시 업무를 진행합니다."
        )

        normalized = normalize_paragraph_spacing(text)

        self.assertEqual(
            normalized,
            "안녕하세요.\n"
            "\n"
            "오전 9시부터 13시까지는 업무 수행 일정이 있습니다.\n"
            "\n"
            "오후 14시부터는 다시 업무를 진행합니다.",
        )

    def test_normalize_paragraph_spacing_splits_sentences_within_paragraph(self) -> None:
        text = (
            "오전 9시부터 13시까지는 '업무 수행' 일정이 있습니다. "
            "08:50에 첫 알림이 있으니 바로 준비하시면 됩니다. "
            "오후 14시부터 18시까지 다시 업무를 진행합니다."
        )

        normalized = normalize_paragraph_spacing(text)

        self.assertEqual(
            normalized,
            "오전 9시부터 13시까지는 '업무 수행' 일정이 있습니다.\n"
            "08:50에 첫 알림이 있으니 바로 준비하시면 됩니다.\n"
            "오후 14시부터 18시까지 다시 업무를 진행합니다.",
        )

    def test_normalize_paragraph_spacing_keeps_bullet_blocks_compact(self) -> None:
        text = (
            "- 첫 번째 업무\n"
            "- 두 번째 업무\n"
            "- 세 번째 업무"
        )

        normalized = normalize_paragraph_spacing(text)

        self.assertEqual(normalized, text)

    def test_normalize_paragraph_spacing_collapses_triple_blank_lines(self) -> None:
        text = "첫 문장입니다.\n\n\n\n두 번째 문장입니다."

        normalized = normalize_paragraph_spacing(text)

        self.assertEqual(normalized, "첫 문장입니다.\n\n두 번째 문장입니다.")

    def test_day_profile_briefing_schedule_has_four_slots(self) -> None:
        from yule_orchestrator.planning.day_profile import DayProfile
        from datetime import time as dt_time

        profile = DayProfile(
            wake_time=dt_time(5, 30),
            work_start_time=dt_time(9, 0),
            lunch_start_time=dt_time(13, 0),
            work_end_time=dt_time(18, 0),
            commute_minutes=45,
            departure_buffer_minutes=10,
            home_area="신정동",
            work_area="마곡",
        )

        slots = profile.briefing_schedule(date(2026, 4, 27))
        types = [slot.briefing_type for slot in slots]

        self.assertEqual(types, ["morning", "work_start", "lunch", "evening"])
        send_times = [slot.send_at.strftime("%H:%M") for slot in slots]
        self.assertEqual(send_times, ["05:30", "09:00", "13:00", "18:00"])
