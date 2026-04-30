from __future__ import annotations

import unittest
from datetime import datetime

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

from yule_orchestrator.agents.deliberation import (
    BackendEngineerTake,
    DeliberationContext,
    FrontendEngineerTake,
    ProductDesignerTake,
    QaEngineerTake,
    TechLeadOpening,
    TechLeadSynthesis,
    render_role_take,
    render_synthesis,
    run_role_deliberation,
    synthesize,
)
from yule_orchestrator.agents.research_pack import (
    ResearchPack,
    pack_from_discord_message,
)
from yule_orchestrator.agents.workflow_state import WorkflowSession, WorkflowState
from yule_orchestrator.discord.engineering_team_runtime import (
    deliberation_role_turn,
    synthesize_thread,
)


def _session(
    *,
    state: WorkflowState = WorkflowState.APPROVED,
    write_requested: bool = False,
    write_blocked_reason: str = "",
    references_user=(),
    references_suggested=(),
    role_sequence=("tech-lead", "product-designer", "frontend-engineer", "qa-engineer"),
    executor_role: str = "frontend-engineer",
    task_type: str = "landing-page",
    prompt: str = "새 랜딩페이지 hero 섹션 정리",
) -> WorkflowSession:
    now = datetime(2026, 4, 30, 9, 0)
    return WorkflowSession(
        session_id="abc123",
        prompt=prompt,
        task_type=task_type,
        state=state,
        created_at=now,
        updated_at=now,
        role_sequence=role_sequence,
        executor_role=executor_role,
        executor_runner="codex",
        references_user=references_user,
        references_suggested=references_suggested,
        write_requested=write_requested,
        write_blocked_reason=write_blocked_reason,
    )


class FallbackTechLeadTestCase(unittest.TestCase):
    def test_fallback_includes_breakdown_and_dependencies(self) -> None:
        session = _session(references_user=("https://example.com/x",))
        take = run_role_deliberation(
            DeliberationContext(session=session, role="engineering-agent/tech-lead")
        )
        self.assertIsInstance(take, TechLeadOpening)
        self.assertTrue(take.task_breakdown)
        self.assertTrue(any("우선" in d for d in take.dependencies))

    def test_fallback_decisions_when_write_pending(self) -> None:
        session = _session(
            state=WorkflowState.INTAKE,
            write_requested=True,
            write_blocked_reason="write requires approval",
        )
        take = run_role_deliberation(
            DeliberationContext(session=session, role="engineering-agent/tech-lead")
        )
        self.assertIsInstance(take, TechLeadOpening)
        self.assertTrue(any("승인" in d for d in take.decisions_needed))


class FallbackProductDesignerTestCase(unittest.TestCase):
    def test_uses_pack_urls_when_available(self) -> None:
        pack = pack_from_discord_message(
            title="Stripe pricing",
            content="https://stripe.com/pricing 참고",
            channel_id=1,
            message_id=2,
        )
        take = run_role_deliberation(
            DeliberationContext(
                session=_session(),
                role="engineering-agent/product-designer",
                research_pack=pack,
            )
        )
        self.assertIsInstance(take, ProductDesignerTake)
        self.assertTrue(any("stripe.com" in s for s in take.reference_summary))

    def test_falls_back_to_user_refs_without_pack(self) -> None:
        take = run_role_deliberation(
            DeliberationContext(
                session=_session(references_user=("https://user.example/a",)),
                role="engineering-agent/product-designer",
            )
        )
        self.assertIsInstance(take, ProductDesignerTake)
        self.assertTrue(any("user.example" in s for s in take.reference_summary))

    def test_flags_risk_when_no_reference(self) -> None:
        take = run_role_deliberation(
            DeliberationContext(
                session=_session(),
                role="engineering-agent/product-designer",
            )
        )
        self.assertTrue(take.risks)


class FallbackOtherRolesTestCase(unittest.TestCase):
    def test_backend(self) -> None:
        take = run_role_deliberation(
            DeliberationContext(session=_session(), role="engineering-agent/backend-engineer")
        )
        self.assertIsInstance(take, BackendEngineerTake)
        self.assertTrue(take.risks)

    def test_frontend(self) -> None:
        take = run_role_deliberation(
            DeliberationContext(session=_session(), role="engineering-agent/frontend-engineer")
        )
        self.assertIsInstance(take, FrontendEngineerTake)
        self.assertTrue(take.ui_components)

    def test_qa(self) -> None:
        take = run_role_deliberation(
            DeliberationContext(session=_session(), role="engineering-agent/qa-engineer")
        )
        self.assertIsInstance(take, QaEngineerTake)
        self.assertTrue(take.acceptance_criteria)

    def test_unknown_role_returns_generic_take(self) -> None:
        take = run_role_deliberation(
            DeliberationContext(session=_session(), role="design-agent/illustrator")
        )
        self.assertIsInstance(take, TechLeadOpening)
        self.assertEqual(take.role, "design-agent/illustrator")


class RunnerInjectionTestCase(unittest.TestCase):
    def test_runner_structured_take_used(self) -> None:
        custom = ProductDesignerTake(
            reference_summary=("custom: a", "custom: b"),
            ux_direction="custom UX",
            visual_direction="custom visual",
        )

        def runner(_ctx: DeliberationContext) -> ProductDesignerTake:
            return custom

        take = run_role_deliberation(
            DeliberationContext(session=_session(), role="engineering-agent/product-designer"),
            runner_fn=runner,
        )
        self.assertEqual(take.ux_direction, "custom UX")
        self.assertEqual(take.reference_summary, ("custom: a", "custom: b"))

    def test_runner_failure_falls_back(self) -> None:
        def boom(_ctx: DeliberationContext):
            raise RuntimeError("backend down")

        take = run_role_deliberation(
            DeliberationContext(session=_session(), role="engineering-agent/backend-engineer"),
            runner_fn=boom,
        )
        self.assertIsInstance(take, BackendEngineerTake)
        self.assertTrue(take.risks)

    def test_runner_returning_none_falls_back(self) -> None:
        def empty(_ctx: DeliberationContext):
            return None

        take = run_role_deliberation(
            DeliberationContext(session=_session(), role="engineering-agent/qa-engineer"),
            runner_fn=empty,
        )
        self.assertIsInstance(take, QaEngineerTake)


class SynthesisTestCase(unittest.TestCase):
    def _basic_takes(self):
        return (
            run_role_deliberation(
                DeliberationContext(session=_session(), role="engineering-agent/tech-lead")
            ),
            run_role_deliberation(
                DeliberationContext(session=_session(), role="engineering-agent/product-designer")
            ),
            run_role_deliberation(
                DeliberationContext(session=_session(), role="engineering-agent/frontend-engineer")
            ),
            run_role_deliberation(
                DeliberationContext(session=_session(), role="engineering-agent/qa-engineer")
            ),
        )

    def test_synthesis_collects_todos_open_research_decisions(self) -> None:
        synth = synthesize(_session(), self._basic_takes())
        self.assertIsInstance(synth, TechLeadSynthesis)
        self.assertTrue(synth.consensus)
        self.assertTrue(synth.todos)
        # No pack → open research flagged.
        self.assertTrue(synth.open_research)

    def test_synthesis_marks_approval_required(self) -> None:
        session = _session(
            state=WorkflowState.INTAKE,
            write_requested=True,
            write_blocked_reason="user_approved=False",
        )
        synth = synthesize(session, self._basic_takes())
        self.assertTrue(synth.approval_required)
        self.assertIn("user_approved", synth.approval_reason or "")

    def test_synthesis_no_approval_when_already_approved(self) -> None:
        session = _session(
            state=WorkflowState.APPROVED,
            write_requested=True,
            write_blocked_reason="",
        )
        synth = synthesize(session, self._basic_takes())
        self.assertFalse(synth.approval_required)

    def test_synthesis_with_full_reference_pack(self) -> None:
        pack = ResearchPack(
            title="bundle",
            primary_url="https://a",
            sources=(),
        )
        # urls from primary_url alone = 1 → still less than 3
        synth = synthesize(_session(), self._basic_takes(), research_pack=pack)
        self.assertTrue(any("3건" in m for m in synth.open_research))


class RenderTestCase(unittest.TestCase):
    def test_render_role_take_includes_header(self) -> None:
        take = run_role_deliberation(
            DeliberationContext(session=_session(), role="engineering-agent/tech-lead")
        )
        text = render_role_take(take)
        self.assertIn("**[tech-lead]**", text)
        self.assertIn("작업 분해", text)

    def test_render_synthesis_blocks(self) -> None:
        synth = TechLeadSynthesis(
            consensus="합의안 한 줄",
            todos=("todo 1",),
            open_research=("연구 항목",),
            user_decisions_needed=("결정 항목",),
            approval_required=True,
            approval_reason="이유",
        )
        text = render_synthesis(synth)
        self.assertIn("합의안", text)
        self.assertIn("해야 할 일", text)
        self.assertIn("더 조사할 것", text)
        self.assertIn("사용자 결정 필요", text)
        self.assertIn("승인 필요: yes", text)


class RuntimeIntegrationTestCase(unittest.TestCase):
    def test_deliberation_role_turn_returns_take_and_text(self) -> None:
        take, text = deliberation_role_turn(
            _session(),
            "engineering-agent/qa-engineer",
        )
        self.assertIsInstance(take, QaEngineerTake)
        self.assertIn("**[qa-engineer]**", text)

    def test_synthesize_thread_uses_deliberation_outputs(self) -> None:
        session = _session()
        takes = [
            deliberation_role_turn(session, role)[0]
            for role in (
                "engineering-agent/tech-lead",
                "engineering-agent/product-designer",
                "engineering-agent/frontend-engineer",
                "engineering-agent/qa-engineer",
            )
        ]
        synth, text = synthesize_thread(session, takes)
        self.assertIsInstance(synth, TechLeadSynthesis)
        self.assertIn("tech-lead 종합", text)


if __name__ == "__main__":
    unittest.main()
