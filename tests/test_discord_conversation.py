from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import patch

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

from yule_orchestrator.discord.bot import _extract_conversation_prompt, _should_handle_message
from yule_orchestrator.discord.conversation import build_conversation_response


class DiscordConversationTestCase(unittest.TestCase):
    def test_should_handle_message_in_conversation_channel(self) -> None:
        message = _message(content="오늘 일정 브리핑 다시 해줘", channel_id=123, mentions=[])
        bot_user = _user(999, "yule-planning-bot")

        handled = _should_handle_message(
            message=message,
            bot_user=bot_user,
            conversation_channel_id=123,
        )

        self.assertTrue(handled)

    def test_should_handle_message_when_bot_is_mentioned(self) -> None:
        message = _message(
            content="<@999> 오늘 뭐부터 해야 해?",
            channel_id=555,
            mentions=[_user(999, "yule-planning-bot")],
        )
        bot_user = _user(999, "yule-planning-bot")

        handled = _should_handle_message(
            message=message,
            bot_user=bot_user,
            conversation_channel_id=None,
        )

        self.assertTrue(handled)

    def test_extract_conversation_prompt_removes_bot_mentions(self) -> None:
        message = _message(content="<@999> 오늘 뭐부터 해야 해?", channel_id=555, mentions=[])
        bot_user = _user(999, "yule-planning-bot")

        prompt = _extract_conversation_prompt(message=message, bot_user=bot_user)

        self.assertEqual(prompt, "오늘 뭐부터 해야 해?")

    @patch("yule_orchestrator.discord.conversation.load_plan_today_snapshot")
    def test_build_conversation_response_returns_priority_summary(
        self,
        load_plan_today_snapshot_mock,
    ) -> None:
        load_plan_today_snapshot_mock.return_value = _snapshot(
            generated_at="2026-04-24T09:00:00+09:00",
            prioritized_titles=["Discord bot 대화형 응답 붙이기", "체크포인트 정리"],
            checkpoint_times=["2026-04-24T09:55:00+09:00"],
            suggested_blocks=[("2026-04-24T10:00:00+09:00", "2026-04-24T11:00:00+09:00", "Discord bot 대화형 응답 붙이기")],
        )

        content = build_conversation_response(
            "오늘 뭐부터 해야 해?",
            author_user_id=777,
            reference_time=datetime.fromisoformat("2026-04-24T09:10:00+09:00"),
        )

        self.assertIn("가장 먼저 볼 일", content)
        self.assertIn("Discord bot 대화형 응답 붙이기", content)
        self.assertIn("다음 체크포인트", content)

    @patch("yule_orchestrator.discord.conversation.load_plan_today_snapshot")
    def test_build_conversation_response_returns_full_briefing_when_requested(
        self,
        load_plan_today_snapshot_mock,
    ) -> None:
        load_plan_today_snapshot_mock.return_value = _snapshot(
            generated_at="2026-04-24T09:00:00+09:00",
            prioritized_titles=["mail-mail 동작 원리 정리"],
            checkpoint_times=[],
            suggested_blocks=[],
        )

        content = build_conversation_response(
            "오늘 브리핑 다시 해줘",
            author_user_id=777,
            reference_time=datetime.fromisoformat("2026-04-24T09:10:00+09:00"),
        )

        self.assertIn("오늘 브리핑", content)
        self.assertIn("아침 브리핑", content)


def _user(user_id: int, name: str):
    class User:
        def __init__(self, value: int, text: str) -> None:
            self.id = value
            self.name = text

    return User(user_id, name)


def _message(*, content: str, channel_id: int, mentions: list[object]):
    class Channel:
        def __init__(self, value: int) -> None:
            self.id = value

    class Message:
        def __init__(self) -> None:
            self.content = content
            self.channel = Channel(channel_id)
            self.mentions = mentions

    return Message()


def _snapshot(
    *,
    generated_at: str,
    prioritized_titles: list[str],
    checkpoint_times: list[str],
    suggested_blocks: list[tuple[str, str, str]],
):
    class Task:
        def __init__(self, title: str) -> None:
            self.title = title
            self.priority_level = "high"
            self.due_date = "2026-04-24"

    class Checkpoint:
        def __init__(self, remind_at: str) -> None:
            self.remind_at = remind_at

    class Block:
        def __init__(self, start: str, end: str, title: str) -> None:
            self.start = start
            self.end = end
            self.title = title

    class Summary:
        fixed_event_count = 1
        recommended_task_count = len(prioritized_titles)

    class DailyPlan:
        def __init__(self) -> None:
            self.discord_briefing = "테스트용 오늘 브리핑"
            self.morning_briefing = "테스트용 아침 브리핑"
            self.prioritized_tasks = [Task(title) for title in prioritized_titles]
            self.checkpoints = [Checkpoint(value) for value in checkpoint_times]
            self.suggested_time_blocks = [Block(start, end, title) for start, end, title in suggested_blocks]
            self.time_block_briefings = []
            self.summary = Summary()

    class Envelope:
        def __init__(self) -> None:
            self.daily_plan = DailyPlan()

    class Snapshot:
        def __init__(self) -> None:
            self.generated_at = datetime.fromisoformat(generated_at)
            self.envelope = Envelope()
            self.is_stale = False

    return Snapshot()
