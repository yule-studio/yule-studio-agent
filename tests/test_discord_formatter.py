from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

from datetime import date, datetime
import unittest

from yule_orchestrator.discord.formatter import (
    format_checkpoints_message,
    format_plan_today_message,
    split_discord_message,
)
from yule_orchestrator.planning.models import (
    DailyPlan,
    DailyPlanEnvelope,
    DailyPlanSummary,
    PlanningBlockBriefing,
    PlanningInputs,
    PlanningScheduledBriefing,
    PlanningSourceStatus,
    PlanningTaskCandidate,
)


class DiscordFormatterTestCase(unittest.TestCase):
    def test_format_plan_today_message_contains_core_sections(self) -> None:
        envelope = DailyPlanEnvelope(
            inputs=PlanningInputs(
                plan_date=date(2026, 4, 22),
                timezone="KST",
                source_statuses=[
                    PlanningSourceStatus(
                        source_id="reminders",
                        source_type="reminder",
                        ok=True,
                        item_count=0,
                    )
                ],
                warnings=[],
                calendar_events=[],
                calendar_todos=[],
                github_issues=[],
                reminders=[],
            ),
            daily_plan=DailyPlan(
                plan_date=date(2026, 4, 22),
                timezone="KST",
                source_statuses=[],
                warnings=[],
                summary=DailyPlanSummary(
                    fixed_event_count=1,
                    all_day_event_count=0,
                    todo_count=1,
                    github_issue_count=0,
                    reminder_count=0,
                    recommended_task_count=1,
                    available_focus_minutes=300,
                ),
                fixed_schedule=[],
                execution_blocks=[],
                prioritized_tasks=[
                    PlanningTaskCandidate(
                        task_id="todo:1",
                        source_type="calendar_todo",
                        title="오늘 해야 할 업무",
                        description="설명",
                        due_date="2026-04-22",
                        priority_score=95,
                        priority_level="high",
                        estimated_minutes=60,
                        reasons=["due today"],
                        coding_candidate=False,
                    )
                ],
                suggested_time_blocks=[],
                morning_briefing="오늘은 먼저 오늘 해야 할 업무를 정리하는 게 좋습니다.",
                time_block_briefings=[
                    PlanningBlockBriefing(
                        briefing_id="briefing-1",
                        start="2026-04-22T09:00:00+09:00",
                        end="2026-04-22T10:00:00+09:00",
                        title="오늘 해야 할 업무 정리",
                        block_type="execution_block",
                        source_ref="block-1",
                        briefing="09:00~10:00은 오늘 해야 할 업무를 정리하는 시간입니다.",
                    )
                ],
                checkpoints=[],
                briefings=[
                    PlanningScheduledBriefing(
                        briefing_id="morning-1",
                        briefing_type="morning",
                        title="아침 브리핑",
                        send_at="2026-04-22T06:00:00+09:00",
                        content="오늘 브리핑\n오늘은 고정 일정 1건입니다.",
                    )
                ],
                coding_agent_handoff=[],
                discord_briefing="오늘은 고정 일정 1건, 우선 작업 1건이 있습니다.",
                morning_briefing_source="rules",
                discord_briefing_source="rules",
            ),
        )

        message = format_plan_today_message(envelope, mention_user_id=123456789)

        self.assertIn("<@123456789>", message)
        self.assertIn("오늘 브리핑", message)
        self.assertIn("아침 브리핑", message)
        self.assertIn("추천 작업", message)
        self.assertIn("시간대 메모", message)
        self.assertIn("우선순위: 높음", message)

    def test_format_checkpoints_message_can_include_mention(self) -> None:
        message = format_checkpoints_message(
            [],
            reference_time=datetime.fromisoformat("2026-04-22T09:55:00+09:00"),
            mention_user_id=123456789,
        )

        self.assertIn("<@123456789>", message)

    def test_split_discord_message_breaks_long_text(self) -> None:
        message = "\n".join([f"line-{index:03d}" for index in range(400)])
        chunks = split_discord_message(message, limit=200)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 200 for chunk in chunks))

    def test_format_plan_today_message_preserves_morning_briefing_paragraphs(self) -> None:
        from yule_orchestrator.discord.formatter import format_plan_today_message
        envelope = DailyPlanEnvelope(
            inputs=PlanningInputs(
                plan_date=date(2026, 4, 22),
                timezone="KST",
                source_statuses=[
                    PlanningSourceStatus(source_id="calendar", source_type="calendar", ok=True, item_count=1),
                ],
                warnings=[],
                calendar_events=[],
                calendar_todos=[],
                github_issues=[],
                reminders=[],
            ),
            daily_plan=DailyPlan(
                plan_date=date(2026, 4, 22),
                timezone="KST",
                source_statuses=[
                    PlanningSourceStatus(source_id="calendar", source_type="calendar", ok=True, item_count=1),
                ],
                warnings=[],
                summary=DailyPlanSummary(
                    fixed_event_count=0,
                    all_day_event_count=0,
                    todo_count=0,
                    github_issue_count=0,
                    reminder_count=0,
                    recommended_task_count=0,
                    available_focus_minutes=0,
                ),
                fixed_schedule=[],
                execution_blocks=[],
                prioritized_tasks=[],
                suggested_time_blocks=[],
                morning_briefing="첫 문단입니다.\n둘째 문단입니다.\n셋째 문단입니다.",
                time_block_briefings=[],
                checkpoints=[],
                briefings=[],
                coding_agent_handoff=[],
                discord_briefing="짧은 요약",
                morning_briefing_source="ollama",
                discord_briefing_source="rules",
            ),
        )

        message = format_plan_today_message(envelope)

        self.assertIn("첫 문단입니다.", message)
        self.assertIn("둘째 문단입니다.", message)
        self.assertIn("셋째 문단입니다.", message)
        self.assertIn("첫 문단입니다.\n\n둘째 문단입니다.", message)

    def test_format_plan_today_message_with_slot_title_prepends_header(self) -> None:
        from yule_orchestrator.discord.formatter import format_plan_today_message
        envelope = DailyPlanEnvelope(
            inputs=PlanningInputs(
                plan_date=date(2026, 4, 22),
                timezone="KST",
                source_statuses=[],
                warnings=[],
                calendar_events=[],
                calendar_todos=[],
                github_issues=[],
                reminders=[],
            ),
            daily_plan=DailyPlan(
                plan_date=date(2026, 4, 22),
                timezone="KST",
                source_statuses=[],
                warnings=[],
                summary=DailyPlanSummary(
                    fixed_event_count=0,
                    all_day_event_count=0,
                    todo_count=0,
                    github_issue_count=0,
                    reminder_count=0,
                    recommended_task_count=0,
                    available_focus_minutes=0,
                ),
                fixed_schedule=[],
                execution_blocks=[],
                prioritized_tasks=[],
                suggested_time_blocks=[],
                morning_briefing="아침 본문",
                time_block_briefings=[],
                checkpoints=[],
                briefings=[],
                coding_agent_handoff=[],
                discord_briefing="요약",
                morning_briefing_source="rules",
                discord_briefing_source="rules",
            ),
        )

        message = format_plan_today_message(envelope, slot_title="업무 시작 브리핑")

        self.assertTrue(message.startswith("**[업무 시작 브리핑]**"))
