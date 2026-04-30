from __future__ import annotations

import asyncio
import os
import unittest
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

from yule_orchestrator.discord.engineering_channel_router import (
    EngineeringConversationOutcome,
    EngineeringRouteContext,
    EngineeringRouteResult,
    EngineeringThreadKickoff,
    detect_confirmation_signal,
    extract_message_attachments,
    is_engineering_channel,
    route_engineering_message,
)


def _run(coro):
    return asyncio.run(coro)


@contextmanager
def _patched_env(values: dict[str, str | None]):
    previous: dict[str, str | None] = {}
    for key, value in values.items():
        previous[key] = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, prior in previous.items():
            if prior is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prior


class _Channel:
    def __init__(
        self,
        *,
        channel_id: int,
        name: str | None,
        parent_id: int | None = None,
        parent_name: str | None = None,
    ) -> None:
        self.id = channel_id
        self.name = name
        if parent_id is None and parent_name is None:
            self.parent = None
            self.parent_id = None
        else:
            self.parent = _Parent(parent_id, parent_name)
            self.parent_id = parent_id


class _Parent:
    def __init__(self, parent_id: int | None, parent_name: str | None) -> None:
        self.id = parent_id
        self.name = parent_name


class _Author:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


class _Message:
    def __init__(
        self,
        *,
        content: str,
        channel: _Channel,
        author_id: int = 4242,
    ) -> None:
        self.content = content
        self.channel = channel
        self.author = _Author(author_id)
        self.mentions: list[Any] = []


@dataclass
class _FakeSession:
    session_id: str
    task_type: str
    executor_role: str | None = "tech-lead"
    executor_runner: str | None = "claude-code"


@dataclass
class _FakePlan:
    role_sequence: tuple[str, ...] = ("tech-lead", "backend-engineer")


@dataclass
class _FakeIntakeResult:
    session: _FakeSession
    plan: _FakePlan
    message: str


def _extract_prompt(*, message: object, bot_user: object) -> str:
    return str(getattr(message, "content", "") or "")


class IsEngineeringChannelTests(unittest.TestCase):
    def test_matches_by_channel_id(self) -> None:
        message = _Message(
            content="안녕",
            channel=_Channel(channel_id=111, name="업무-접수"),
        )
        ctx = EngineeringRouteContext(intake_channel_id=111)
        self.assertTrue(is_engineering_channel(message=message, route_context=ctx))

    def test_matches_by_channel_name(self) -> None:
        message = _Message(
            content="안녕",
            channel=_Channel(channel_id=999, name="업무-접수"),
        )
        ctx = EngineeringRouteContext(intake_channel_name="업무-접수")
        self.assertTrue(is_engineering_channel(message=message, route_context=ctx))

    def test_matches_thread_parent(self) -> None:
        message = _Message(
            content="안녕",
            channel=_Channel(
                channel_id=2222,
                name="작업-thread",
                parent_id=111,
                parent_name="업무-접수",
            ),
        )
        ctx = EngineeringRouteContext(intake_channel_id=111)
        self.assertTrue(is_engineering_channel(message=message, route_context=ctx))

    def test_thread_parent_name_match(self) -> None:
        message = _Message(
            content="안녕",
            channel=_Channel(
                channel_id=2222,
                name="작업-thread",
                parent_id=None,
                parent_name="#업무-접수",
            ),
        )
        ctx = EngineeringRouteContext(intake_channel_name="업무-접수")
        self.assertTrue(is_engineering_channel(message=message, route_context=ctx))

    def test_returns_false_when_no_context_configured(self) -> None:
        message = _Message(
            content="안녕",
            channel=_Channel(channel_id=111, name="업무-접수"),
        )
        ctx = EngineeringRouteContext()
        self.assertFalse(is_engineering_channel(message=message, route_context=ctx))

    def test_returns_false_for_planning_channel(self) -> None:
        message = _Message(
            content="안녕",
            channel=_Channel(channel_id=555, name="planning-chat"),
        )
        ctx = EngineeringRouteContext(intake_channel_id=111, intake_channel_name="업무-접수")
        self.assertFalse(is_engineering_channel(message=message, route_context=ctx))


class ConfirmationSignalTests(unittest.TestCase):
    def test_detects_korean_confirm_phrases(self) -> None:
        for phrase in (
            "이대로 진행해 줘",
            "확정",
            "ㄱㄱ 시작하자",
            "고고",
            "그대로 가자 진행",
            "오케이 진행해줘",
        ):
            self.assertTrue(
                detect_confirmation_signal(phrase),
                f"expected confirmation for {phrase!r}",
            )

    def test_detects_english_confirm_phrases(self) -> None:
        for phrase in ("let's go", "Go ahead", "kick off please", "Proceed"):
            self.assertTrue(
                detect_confirmation_signal(phrase),
                f"expected confirmation for {phrase!r}",
            )

    def test_does_not_promote_casual_yes(self) -> None:
        for phrase in (
            "그게 뭐야?",
            "yes",
            "네",
            "오케이",
            "",
        ):
            self.assertFalse(
                detect_confirmation_signal(phrase),
                f"did not expect confirmation for {phrase!r}",
            )


class RouteContextEnvTests(unittest.TestCase):
    def test_reads_env_vars(self) -> None:
        with _patched_env(
            {
                "DISCORD_ENGINEERING_INTAKE_CHANNEL_ID": "1234",
                "DISCORD_ENGINEERING_INTAKE_CHANNEL_NAME": "업무-접수",
            }
        ):
            ctx = EngineeringRouteContext.from_env()
        self.assertEqual(ctx.intake_channel_id, 1234)
        self.assertEqual(ctx.intake_channel_name, "업무-접수")
        self.assertTrue(ctx.configured)

    def test_unconfigured_when_env_missing(self) -> None:
        with _patched_env(
            {
                "DISCORD_ENGINEERING_INTAKE_CHANNEL_ID": None,
                "DISCORD_ENGINEERING_INTAKE_CHANNEL_NAME": None,
            }
        ):
            ctx = EngineeringRouteContext.from_env()
        self.assertFalse(ctx.configured)


class RouteEngineeringMessageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = EngineeringRouteContext(intake_channel_id=111)
        self.send_chunks = AsyncMock()

    def _route(
        self,
        *,
        message: _Message,
        conversation_fn,
        intake_fn=None,
        thread_kickoff_fn=None,
    ) -> EngineeringRouteResult:
        intake_fn = intake_fn or AsyncMock(side_effect=AssertionError("intake should not run"))
        thread_kickoff_fn = thread_kickoff_fn or AsyncMock(
            side_effect=AssertionError("thread kickoff should not run")
        )
        return _run(
            route_engineering_message(
                message=message,
                bot_user=object(),
                route_context=self.context,
                extract_prompt=_extract_prompt,
                conversation_fn=conversation_fn,
                intake_fn=intake_fn,
                thread_kickoff_fn=thread_kickoff_fn,
                send_chunks=self.send_chunks,
            )
        )

    def test_non_engineering_channel_returns_unhandled(self) -> None:
        message = _Message(
            content="안녕",
            channel=_Channel(channel_id=999, name="planning-chat"),
        )
        outcome = EngineeringConversationOutcome(content="hi")
        result = self._route(
            message=message,
            conversation_fn=lambda **_: outcome,
        )
        self.assertFalse(result.handled)
        self.send_chunks.assert_not_awaited()

    def test_engineering_message_without_confirmation_only_replies(self) -> None:
        message = _Message(
            content="이번 작업 우선순위 좀 정리해줘",
            channel=_Channel(channel_id=111, name="업무-접수"),
        )
        outcome = EngineeringConversationOutcome(
            content="우선순위는 다음과 같이 보입니다 …",
        )
        result = self._route(
            message=message,
            conversation_fn=lambda **_: outcome,
        )
        self.assertTrue(result.handled)
        self.assertEqual(result.conversation_message, outcome.content)
        self.assertIsNone(result.session_id)
        self.send_chunks.assert_awaited_once()
        sent_text = self.send_chunks.await_args.args[1]
        self.assertEqual(sent_text, outcome.content)

    def test_confirmation_runs_intake_and_kickoff(self) -> None:
        message = _Message(
            content="좋아요 그대로 진행해 주세요",
            channel=_Channel(channel_id=111, name="업무-접수"),
        )
        outcome = EngineeringConversationOutcome(
            content="요약은 이렇습니다.",
            confirmed=True,
            intake_prompt="planning-bot의 자유대화 레이어를 손봐 주세요",
            write_requested=True,
            thread_topic="engineer-feature-abc",
        )
        intake_session = _FakeSession(session_id="abc123", task_type="feature")
        intake_plan = _FakePlan()
        intake_message = "**[engineering-agent] 새 작업 접수** ..."
        intake_fn = AsyncMock(
            return_value=_FakeIntakeResult(
                session=intake_session,
                plan=intake_plan,
                message=intake_message,
            )
        )
        kickoff = EngineeringThreadKickoff(thread_id=4242, message="kickoff!")
        thread_kickoff_fn = AsyncMock(return_value=kickoff)

        result = self._route(
            message=message,
            conversation_fn=lambda **_: outcome,
            intake_fn=intake_fn,
            thread_kickoff_fn=thread_kickoff_fn,
        )

        self.assertTrue(result.handled)
        self.assertEqual(result.session_id, "abc123")
        self.assertEqual(result.thread_id, 4242)
        self.assertEqual(result.intake_message, intake_message)
        self.assertEqual(result.kickoff_message, "kickoff!")

        intake_fn.assert_awaited_once()
        intake_kwargs = intake_fn.await_args.kwargs
        self.assertEqual(intake_kwargs["prompt"], outcome.intake_prompt)
        self.assertTrue(intake_kwargs["write_requested"])
        self.assertEqual(intake_kwargs["channel_id"], 111)
        self.assertEqual(intake_kwargs["user_id"], 4242)

        thread_kickoff_fn.assert_awaited_once()
        kickoff_kwargs = thread_kickoff_fn.await_args.kwargs
        self.assertIs(kickoff_kwargs["session"], intake_session)
        self.assertIs(kickoff_kwargs["plan"], intake_plan)
        self.assertEqual(kickoff_kwargs["topic"], "engineer-feature-abc")

        sent_payloads = [call.args[1] for call in self.send_chunks.await_args_list]
        self.assertIn(outcome.content, sent_payloads)
        self.assertIn(intake_message, sent_payloads)

    def test_keyword_fallback_promotes_to_intake_when_outcome_is_string(self) -> None:
        message = _Message(
            content="좋아 이대로 ㄱㄱ",
            channel=_Channel(channel_id=111, name="업무-접수"),
        )
        intake_session = _FakeSession(session_id="ses1", task_type="ops")
        intake_fn = AsyncMock(
            return_value=_FakeIntakeResult(
                session=intake_session,
                plan=_FakePlan(),
                message="intake!",
            )
        )
        kickoff = EngineeringThreadKickoff(thread_id=7, message="kickoff!")
        thread_kickoff_fn = AsyncMock(return_value=kickoff)

        result = self._route(
            message=message,
            conversation_fn=lambda **_: "이렇게 진행하면 어떨까요?",
            intake_fn=intake_fn,
            thread_kickoff_fn=thread_kickoff_fn,
        )

        self.assertTrue(result.handled)
        self.assertEqual(result.session_id, "ses1")
        self.assertEqual(result.thread_id, 7)
        intake_fn.assert_awaited_once()
        intake_kwargs = intake_fn.await_args.kwargs
        self.assertEqual(intake_kwargs["prompt"], "좋아 이대로 ㄱㄱ")
        self.assertFalse(intake_kwargs["write_requested"])

    def test_intake_failure_reports_error_without_calling_kickoff(self) -> None:
        message = _Message(
            content="이대로 진행해 주세요",
            channel=_Channel(channel_id=111, name="업무-접수"),
        )
        outcome = EngineeringConversationOutcome(
            content="요약 갑니다.",
            confirmed=True,
            intake_prompt="문서 만들어 주세요",
        )
        intake_fn = AsyncMock(side_effect=RuntimeError("dispatcher down"))
        thread_kickoff_fn = AsyncMock(side_effect=AssertionError("kickoff should not run"))

        result = self._route(
            message=message,
            conversation_fn=lambda **_: outcome,
            intake_fn=intake_fn,
            thread_kickoff_fn=thread_kickoff_fn,
        )

        self.assertTrue(result.handled)
        self.assertIsNone(result.session_id)
        self.assertIn("dispatcher down", result.error or "")
        sent_payloads = [call.args[1] for call in self.send_chunks.await_args_list]
        self.assertIn(outcome.content, sent_payloads)
        self.assertTrue(any("intake 실패" in payload for payload in sent_payloads))
        thread_kickoff_fn.assert_not_awaited()

    def test_kickoff_failure_keeps_session_and_reports_error(self) -> None:
        message = _Message(
            content="이대로 진행해 주세요",
            channel=_Channel(channel_id=111, name="업무-접수"),
        )
        outcome = EngineeringConversationOutcome(
            content="요약 갑니다.",
            confirmed=True,
            intake_prompt="작업 진행해 주세요",
        )
        intake_session = _FakeSession(session_id="ses-kick-fail", task_type="feature")
        intake_fn = AsyncMock(
            return_value=_FakeIntakeResult(
                session=intake_session,
                plan=_FakePlan(),
                message="intake message",
            )
        )
        thread_kickoff_fn = AsyncMock(side_effect=RuntimeError("forbidden"))

        result = self._route(
            message=message,
            conversation_fn=lambda **_: outcome,
            intake_fn=intake_fn,
            thread_kickoff_fn=thread_kickoff_fn,
        )

        self.assertTrue(result.handled)
        self.assertEqual(result.session_id, "ses-kick-fail")
        self.assertIsNone(result.thread_id)
        self.assertEqual(result.error, "forbidden")
        sent_payloads = [call.args[1] for call in self.send_chunks.await_args_list]
        self.assertTrue(any("thread kickoff 실패" in payload for payload in sent_payloads))

    def test_async_conversation_fn_is_awaited(self) -> None:
        message = _Message(
            content="브리핑 좀 부탁",
            channel=_Channel(channel_id=111, name="업무-접수"),
        )
        outcome = EngineeringConversationOutcome(content="요약 응답")

        async def _async_conversation(**_kwargs):
            return outcome

        result = self._route(
            message=message,
            conversation_fn=_async_conversation,
        )
        self.assertTrue(result.handled)
        self.send_chunks.assert_awaited_once()
        self.assertEqual(self.send_chunks.await_args.args[1], outcome.content)

    def test_empty_prompt_does_not_handle(self) -> None:
        message = _Message(
            content="   ",
            channel=_Channel(channel_id=111, name="업무-접수"),
        )
        result = self._route(
            message=message,
            conversation_fn=lambda **_: EngineeringConversationOutcome(content="ignored"),
        )
        self.assertFalse(result.handled)
        self.send_chunks.assert_not_awaited()

    def test_planning_channel_message_falls_through_unhandled(self) -> None:
        """Engineering router must not steal #일정-관리 / planning conversation messages.

        ``handled=False`` lets the bot's planning conversation layer take over;
        if this regressed, planning-bot users would see "engineer intake" replies.
        """

        message = _Message(
            content="오늘 점심 브리핑 다시 보여줘",
            channel=_Channel(channel_id=222, name="일정-관리"),
        )
        # _route's defaults raise AssertionError if intake_fn / thread_kickoff_fn
        # are ever called, so a clean handled=False here also confirms planning
        # messages never trip the engineering pipeline.
        result = self._route(
            message=message,
            conversation_fn=lambda **_: EngineeringConversationOutcome(content="should not be sent"),
        )
        self.assertFalse(result.handled)
        self.send_chunks.assert_not_awaited()


class ExtractMessageAttachmentsTests(unittest.TestCase):
    def test_returns_empty_tuple_when_attribute_missing(self) -> None:
        message = object()
        self.assertEqual(extract_message_attachments(message), ())

    def test_returns_empty_when_explicit_none(self) -> None:
        class _Msg:
            attachments = None

        self.assertEqual(extract_message_attachments(_Msg()), ())

    def test_passes_through_list_attachments(self) -> None:
        class _Msg:
            attachments = [
                {"filename": "hero.png"},
                {"filename": "spec.pdf"},
            ]

        result = extract_message_attachments(_Msg())
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["filename"], "hero.png")

    def test_drops_none_entries(self) -> None:
        class _Msg:
            attachments = [None, {"filename": "a.png"}, None]

        result = extract_message_attachments(_Msg())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["filename"], "a.png")

    def test_accepts_iterable_attachments(self) -> None:
        def _yield():
            yield {"filename": "one.png"}
            yield {"filename": "two.pdf"}

        class _Msg:
            attachments = _yield()

        result = extract_message_attachments(_Msg())
        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
