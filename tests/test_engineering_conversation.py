from __future__ import annotations

import unittest

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

from yule_orchestrator.discord.engineering_conversation import (
    CONFIRM_INTAKE,
    GENERAL_ENGINEERING_HELP,
    NEEDS_CLARIFICATION,
    SPLIT_TASK_PROPOSAL,
    TASK_INTAKE_CANDIDATE,
    build_engineering_conversation_response,
    detect_engineering_intent,
    split_task_branches,
)


class DetectIntentTestCase(unittest.TestCase):
    def test_general_help_keyword(self) -> None:
        intent = detect_engineering_intent("engineering-agent 어떻게 써?")
        self.assertEqual(intent.intent_id, GENERAL_ENGINEERING_HELP)

    def test_help_korean(self) -> None:
        intent = detect_engineering_intent("엔지니어링 봇 도움말 좀 줘봐")
        self.assertEqual(intent.intent_id, GENERAL_ENGINEERING_HELP)

    def test_confirm_phrase_short_circuits(self) -> None:
        intent = detect_engineering_intent("이대로 진행")
        self.assertEqual(intent.intent_id, CONFIRM_INTAKE)

    def test_confirm_standalone_token(self) -> None:
        for token in ("ok", "오케이", "확정", "진행", "ㄱㄱ"):
            with self.subTest(token=token):
                intent = detect_engineering_intent(token)
                self.assertEqual(intent.intent_id, CONFIRM_INTAKE)

    def test_vague_short_message(self) -> None:
        for text in ("도와줘", "ㅁㄴㅇ", "ㅎㅎ"):
            with self.subTest(text=text):
                intent = detect_engineering_intent(text)
                self.assertEqual(intent.intent_id, NEEDS_CLARIFICATION)

    def test_empty_message(self) -> None:
        self.assertEqual(detect_engineering_intent("   ").intent_id, NEEDS_CLARIFICATION)

    def test_split_task_when_two_substantial_branches(self) -> None:
        intent = detect_engineering_intent(
            "랜딩페이지 hero 정리하고 또 회원가입 onboarding 흐름 개선해줘"
        )
        self.assertEqual(intent.intent_id, SPLIT_TASK_PROPOSAL)

    def test_no_split_when_branch_is_too_short(self) -> None:
        intent = detect_engineering_intent("음 그리고 좋아")
        self.assertNotEqual(intent.intent_id, SPLIT_TASK_PROPOSAL)

    def test_default_is_intake_candidate(self) -> None:
        intent = detect_engineering_intent("users API schema 변경해서 email_verified 필드 추가")
        self.assertEqual(intent.intent_id, TASK_INTAKE_CANDIDATE)


class SplitTaskBranchesTestCase(unittest.TestCase):
    def test_korean_conjunction(self) -> None:
        self.assertEqual(
            split_task_branches("랜딩 hero 정리 그리고 회원가입 흐름 개선"),
            ("랜딩 hero 정리", "회원가입 흐름 개선"),
        )

    def test_english_and(self) -> None:
        self.assertEqual(
            split_task_branches("polish hero and refresh onboarding"),
            ("polish hero", "refresh onboarding"),
        )

    def test_no_split_for_single_clause(self) -> None:
        self.assertEqual(split_task_branches("hero 섹션 정리"), ())


class ResponseEnvelopeTestCase(unittest.TestCase):
    def test_general_help_envelope(self) -> None:
        envelope = build_engineering_conversation_response("도움말 줘봐")
        self.assertEqual(envelope.intent_id, GENERAL_ENGINEERING_HELP)
        self.assertFalse(envelope.ready_to_intake)
        self.assertFalse(envelope.needs_clarification)
        self.assertIsNone(envelope.intake_prompt)

    def test_intake_candidate_envelope(self) -> None:
        envelope = build_engineering_conversation_response(
            "새 랜딩페이지 hero 섹션을 다시 짜야 해"
        )
        self.assertEqual(envelope.intent_id, TASK_INTAKE_CANDIDATE)
        self.assertEqual(envelope.suggested_task_type, "landing-page")
        self.assertTrue(envelope.write_likely)
        self.assertEqual(envelope.intake_prompt, "새 랜딩페이지 hero 섹션을 다시 짜야 해")
        self.assertFalse(envelope.ready_to_intake)
        self.assertIn("이대로 진행", envelope.content)

    def test_needs_clarification_envelope(self) -> None:
        envelope = build_engineering_conversation_response("도와줘")
        self.assertEqual(envelope.intent_id, NEEDS_CLARIFICATION)
        self.assertTrue(envelope.needs_clarification)
        self.assertFalse(envelope.ready_to_intake)
        self.assertIn("작업 범위", envelope.content)

    def test_split_proposal_envelope(self) -> None:
        envelope = build_engineering_conversation_response(
            "랜딩페이지 hero 정리하고 또 회원가입 onboarding 흐름 개선해줘"
        )
        self.assertEqual(envelope.intent_id, SPLIT_TASK_PROPOSAL)
        self.assertEqual(len(envelope.proposed_splits), 2)
        self.assertFalse(envelope.ready_to_intake)
        self.assertEqual(envelope.intake_prompt, envelope.intake_prompt)  # preserved

    def test_confirm_with_last_prompt_marks_ready_to_intake(self) -> None:
        envelope = build_engineering_conversation_response(
            "이대로 진행",
            last_proposed_prompt="랜딩페이지 hero 다시 짜야 해",
        )
        self.assertEqual(envelope.intent_id, CONFIRM_INTAKE)
        self.assertTrue(envelope.ready_to_intake)
        self.assertEqual(envelope.intake_prompt, "랜딩페이지 hero 다시 짜야 해")
        self.assertEqual(envelope.suggested_task_type, "landing-page")
        self.assertTrue(envelope.write_likely)

    def test_confirm_without_last_prompt_uses_message_text(self) -> None:
        envelope = build_engineering_conversation_response("이대로 진행")
        self.assertEqual(envelope.intent_id, CONFIRM_INTAKE)
        self.assertTrue(envelope.ready_to_intake)
        self.assertEqual(envelope.intake_prompt, "이대로 진행")

    def test_mention_prefix_only_when_requested(self) -> None:
        with_mention = build_engineering_conversation_response(
            "도와줘",
            author_user_id=123,
            mention_user=True,
        )
        without_mention = build_engineering_conversation_response(
            "도와줘",
            author_user_id=123,
            mention_user=False,
        )
        self.assertTrue(with_mention.content.startswith("<@123>"))
        self.assertFalse(without_mention.content.startswith("<@"))


class WriteLikelyTestCase(unittest.TestCase):
    def test_write_keywords_set_flag(self) -> None:
        for prompt in (
            "users API 추가 구현해줘",
            "랜딩 hero 다시 짜야 해",
            "buttons 컴포넌트 만들어줘",
            "fix 배포 스크립트",
        ):
            with self.subTest(prompt=prompt):
                envelope = build_engineering_conversation_response(prompt)
                self.assertTrue(envelope.write_likely, prompt)

    def test_review_signals_dominate_write(self) -> None:
        envelope = build_engineering_conversation_response(
            "users API 어떻게 생각해 분석만 해줘"
        )
        self.assertFalse(envelope.write_likely)


class TaskTypeHintTestCase(unittest.TestCase):
    def test_known_task_types(self) -> None:
        cases = {
            "랜딩 hero 정리": "landing-page",
            "onboarding 가입 흐름 개선": "onboarding-flow",
            "welcome email 캠페인 만들기": "email-campaign",
            "히어로 visual polish": "visual-polish",
            "users API 추가": "backend-feature",
            "ui 컴포넌트 정리": "frontend-feature",
            "regression 테스트 시나리오 추가": "qa-test",
            "deploy 파이프라인 보강": "platform-infra",
        }
        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                envelope = build_engineering_conversation_response(prompt)
                self.assertEqual(envelope.suggested_task_type, expected)

    def test_unknown_message_has_no_task_type(self) -> None:
        envelope = build_engineering_conversation_response("이 부분 좀 검토해줘")
        self.assertIsNone(envelope.suggested_task_type)


if __name__ == "__main__":
    unittest.main()
