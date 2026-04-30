"""Deliberation loop — structured per-role outputs + tech-lead synthesis.

This is the *contract layer* on top of the existing sequential runtime
(``discord/engineering_team_runtime.py``). It accepts:

- a :class:`WorkflowSession` (dispatcher decisions, write gate state),
- an optional :class:`ResearchPack` (자료 수집 결과),
- ``previous_turns`` — what other roles already said in the same thread,

and produces typed role contracts (one dataclass per role) plus a
``TechLeadSynthesis`` that closes the loop with 합의안 / 해야 할 일 /
더 조사할 것 / 사용자 결정 필요 / 승인 필요 여부.

LLM runner integration is optional. ``run_role_deliberation`` accepts a
``runner_fn`` injection point; when None or when the runner raises, a
**deterministic fallback** based on session/pack metadata is used so the
loop always produces a usable output. That keeps the MVP testable and
the production path resilient when a backend is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Optional, Sequence, Tuple, Union

from .research_pack import ResearchPack
from .workflow_state import WorkflowSession


# ---------------------------------------------------------------------------
# Per-role contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TechLeadOpening:
    """tech-lead가 thread 시작에 정리하는 작업 분해."""

    role: str = "engineering-agent/tech-lead"
    task_breakdown: Sequence[str] = field(default_factory=tuple)
    dependencies: Sequence[str] = field(default_factory=tuple)
    decisions_needed: Sequence[str] = field(default_factory=tuple)
    notes: Optional[str] = None


@dataclass(frozen=True)
class ProductDesignerTake:
    """product-designer 관점의 reference / UX / 시각 방향."""

    role: str = "engineering-agent/product-designer"
    reference_summary: Sequence[str] = field(default_factory=tuple)
    ux_direction: Optional[str] = None
    visual_direction: Optional[str] = None
    risks: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class BackendEngineerTake:
    """backend-engineer 관점의 데이터 / API / 저장소 영향."""

    role: str = "engineering-agent/backend-engineer"
    data_impact: Optional[str] = None
    api_impact: Optional[str] = None
    storage_impact: Optional[str] = None
    risks: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class FrontendEngineerTake:
    """frontend-engineer 관점의 UI / 상태 / 사용자 흐름."""

    role: str = "engineering-agent/frontend-engineer"
    ui_components: Sequence[str] = field(default_factory=tuple)
    state_strategy: Optional[str] = None
    user_flow: Optional[str] = None
    risks: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class QaEngineerTake:
    """qa-engineer 관점의 검증 기준 / 리스크 / 회귀."""

    role: str = "engineering-agent/qa-engineer"
    acceptance_criteria: Sequence[str] = field(default_factory=tuple)
    risks: Sequence[str] = field(default_factory=tuple)
    regression_targets: Sequence[str] = field(default_factory=tuple)


RoleTake = Union[
    TechLeadOpening,
    ProductDesignerTake,
    BackendEngineerTake,
    FrontendEngineerTake,
    QaEngineerTake,
]


@dataclass(frozen=True)
class TechLeadSynthesis:
    """thread 마지막 tech-lead 종합."""

    consensus: str
    todos: Sequence[str] = field(default_factory=tuple)
    open_research: Sequence[str] = field(default_factory=tuple)
    user_decisions_needed: Sequence[str] = field(default_factory=tuple)
    approval_required: bool = False
    approval_reason: Optional[str] = None


@dataclass(frozen=True)
class DeliberationContext:
    """Bundled inputs for one role's deliberation turn."""

    session: WorkflowSession
    role: str
    research_pack: Optional[ResearchPack] = None
    previous_turns: Sequence[RoleTake] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Runner injection (LLM-backed; optional)
# ---------------------------------------------------------------------------


# Returns either a RoleTake (already structured) or a string the caller will
# parse. For MVP we only support the structured return; raw strings trigger
# fallback so production starts simple and incrementally adds parsers.
RunnerFn = Callable[[DeliberationContext], Any]


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def run_role_deliberation(
    context: DeliberationContext,
    *,
    runner_fn: Optional[RunnerFn] = None,
) -> RoleTake:
    """Produce one role's structured take.

    Tries *runner_fn* first; on None / exception / unstructured return,
    falls back to deterministic templates.
    """

    if runner_fn is not None:
        try:
            outcome = runner_fn(context)
        except Exception:  # noqa: BLE001 - fall back to deterministic template
            outcome = None
        else:
            structured = _coerce_structured_outcome(outcome, context.role)
            if structured is not None:
                return structured

    return _deterministic_role_take(context)


def synthesize(
    session: WorkflowSession,
    role_takes: Sequence[RoleTake],
    *,
    research_pack: Optional[ResearchPack] = None,
) -> TechLeadSynthesis:
    """Produce the final tech-lead synthesis from collected role takes.

    Pure-deterministic for MVP. A future iteration may delegate to an LLM
    runner; the dataclass shape is the contract either way.
    """

    todos: list[str] = []
    open_research: list[str] = []
    user_decisions: list[str] = []

    # Pull todos out of each per-role take's strongest signal.
    for take in role_takes:
        todos.extend(_todos_from_take(take))
        if isinstance(take, TechLeadOpening):
            user_decisions.extend(take.decisions_needed)

    # Reference gaps → open research.
    if research_pack is None or not research_pack.urls:
        open_research.append("자료 reference 보강 필요 — 현재 thread에 첨부된 링크 없음")
    if research_pack is not None and len(research_pack.urls) < 3:
        open_research.append(
            "권장 reference 3건 이상이 아직 모이지 않았습니다 — 추가 자료 수집 권장"
        )

    approval_required = bool(session.write_requested) and not _session_approved(session)
    approval_reason = (
        session.write_blocked_reason
        if approval_required and session.write_blocked_reason
        else (
            "쓰기 작업 승인이 필요합니다."
            if approval_required
            else None
        )
    )

    consensus = _consensus_summary(session, role_takes)
    return TechLeadSynthesis(
        consensus=consensus,
        todos=tuple(_dedup_keep_order(todos)),
        open_research=tuple(_dedup_keep_order(open_research)),
        user_decisions_needed=tuple(_dedup_keep_order(user_decisions)),
        approval_required=approval_required,
        approval_reason=approval_reason,
    )


def render_role_take(take: RoleTake) -> str:
    """Render a role take as a Discord-friendly multi-line string."""

    if isinstance(take, TechLeadOpening):
        return _render_tech_lead_opening(take)
    if isinstance(take, ProductDesignerTake):
        return _render_product_designer(take)
    if isinstance(take, BackendEngineerTake):
        return _render_backend_engineer(take)
    if isinstance(take, FrontendEngineerTake):
        return _render_frontend_engineer(take)
    if isinstance(take, QaEngineerTake):
        return _render_qa_engineer(take)
    raise TypeError(f"unsupported role take type: {type(take)!r}")


def render_synthesis(synth: TechLeadSynthesis) -> str:
    lines: list[str] = ["**[tech-lead 종합]**"]
    lines.append(f"합의안: {synth.consensus}")
    lines.append(_bullet_block("해야 할 일", synth.todos))
    lines.append(_bullet_block("더 조사할 것", synth.open_research))
    lines.append(_bullet_block("사용자 결정 필요", synth.user_decisions_needed))
    if synth.approval_required:
        reason = synth.approval_reason or "쓰기 승인 필요"
        lines.append(f"승인 필요: yes — {reason}")
    else:
        lines.append("승인 필요: no")
    return "\n".join(line for line in lines if line)


# ---------------------------------------------------------------------------
# Deterministic fallback templates
# ---------------------------------------------------------------------------


def _deterministic_role_take(context: DeliberationContext) -> RoleTake:
    role_short = _short_role(context.role)
    if role_short == "tech-lead":
        return _fallback_tech_lead_opening(context)
    if role_short == "product-designer":
        return _fallback_product_designer(context)
    if role_short == "backend-engineer":
        return _fallback_backend_engineer(context)
    if role_short == "frontend-engineer":
        return _fallback_frontend_engineer(context)
    if role_short == "qa-engineer":
        return _fallback_qa_engineer(context)
    # Unknown role — coerce to a generic tech-lead-shaped take so callers
    # always get something renderable.
    return TechLeadOpening(
        role=context.role,
        task_breakdown=(f"{context.role} 영역 검토",),
        notes="해당 역할의 결정 양식이 아직 정의되지 않았습니다.",
    )


def _fallback_tech_lead_opening(ctx: DeliberationContext) -> TechLeadOpening:
    session = ctx.session
    pack = ctx.research_pack
    breakdown = [
        f"분류 `{session.task_type}` · 실행자 `{session.executor_role or 'tech-lead'}`",
        f"요청 본문: {_excerpt(session.prompt, 80)}",
    ]
    if session.role_sequence:
        breakdown.append(
            "역할 순서: " + " → ".join(session.role_sequence)
        )
    dependencies: list[str] = []
    if session.references_user:
        dependencies.append(
            "사용자 제공 reference 우선 검토 — " + ", ".join(session.references_user[:2])
        )
    if pack is not None and pack.urls:
        dependencies.append(
            "ResearchPack 자료 " + str(len(pack.urls)) + "건 thread에 동기화"
        )
    if not dependencies:
        dependencies.append("외부 의존 없음 — 각자 도메인 기준으로 시작")
    decisions_needed: list[str] = []
    if session.write_requested and not _session_approved(session):
        decisions_needed.append("쓰기 진행 승인 (operator 확인)")
    if pack is not None and len(pack.urls) < 3:
        decisions_needed.append("reference 추가 수집 여부")
    return TechLeadOpening(
        task_breakdown=tuple(breakdown),
        dependencies=tuple(dependencies),
        decisions_needed=tuple(decisions_needed),
        notes=None,
    )


def _fallback_product_designer(ctx: DeliberationContext) -> ProductDesignerTake:
    pack = ctx.research_pack
    refs: Tuple[str, ...] = ()
    if pack is not None and pack.urls:
        refs = pack.urls[:3]
    elif ctx.session.references_user:
        refs = tuple(ctx.session.references_user[:3])
    elif ctx.session.references_suggested:
        refs = tuple(ctx.session.references_suggested[:3])

    summary = tuple(f"reference 검토: {r}" for r in refs) or (
        "reference 미공급 — 사용자 제공 자료 또는 suggested 카테고리 우선",
    )

    risks: list[str] = []
    if not refs:
        risks.append("reference 부재 — 단순 복제 위험 회피 위해 추가 자료 권장")

    return ProductDesignerTake(
        reference_summary=summary,
        ux_direction="현재 흐름 기준으로 step 단위 분해 후 영역별 친절도 점검",
        visual_direction="기존 톤 유지하되 reference에서 색·여백 패턴만 차용",
        risks=tuple(risks),
    )


def _fallback_backend_engineer(ctx: DeliberationContext) -> BackendEngineerTake:
    return BackendEngineerTake(
        data_impact=_first_line(
            ctx.session.prompt,
            "도메인 모델 영향 점검 — schema 변경 여부 확인 필요",
        ),
        api_impact="외부 계약 변경 가능성 검토 — 변경 시 backward compatibility 메모",
        storage_impact="저장소 마이그레이션 필요 시 off-peak 적용 권장",
        risks=("schema 변경 동시 작업 충돌 가능", "기존 cache key 포맷 영향 점검"),
    )


def _fallback_frontend_engineer(ctx: DeliberationContext) -> FrontendEngineerTake:
    return FrontendEngineerTake(
        ui_components=("hero / CTA", "필수 폼", "상태 indicator"),
        state_strategy="form 상태는 로컬, 검증 결과만 글로벌 — 기존 패턴 유지",
        user_flow="첫 화면 → 정보 입력 → 검증 → 결과 노출 4단계 유지",
        risks=("모바일 가로폭에서 CTA 절단 가능", "에러 메시지 i18n 누락 위험"),
    )


def _fallback_qa_engineer(ctx: DeliberationContext) -> QaEngineerTake:
    return QaEngineerTake(
        acceptance_criteria=(
            "주요 흐름 e2e 1건 추가",
            "에러/빈 상태 스냅샷 확인",
        ),
        risks=("기존 회귀 케이스 영향", "비동기 race condition"),
        regression_targets=(
            "회원가입 onboarding 회귀 묶음",
            "공통 layout 컴포넌트",
        ),
    )


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _render_tech_lead_opening(t: TechLeadOpening) -> str:
    lines = ["**[tech-lead]**"]
    lines.append(_bullet_block("작업 분해", t.task_breakdown))
    lines.append(_bullet_block("의존성", t.dependencies))
    lines.append(_bullet_block("결정 필요 사항", t.decisions_needed))
    if t.notes:
        lines.append(f"메모: {t.notes}")
    return "\n".join(line for line in lines if line)


def _render_product_designer(t: ProductDesignerTake) -> str:
    lines = ["**[product-designer]**"]
    lines.append(_bullet_block("레퍼런스", t.reference_summary))
    if t.ux_direction:
        lines.append(f"UX 방향: {t.ux_direction}")
    if t.visual_direction:
        lines.append(f"시각 방향: {t.visual_direction}")
    lines.append(_bullet_block("리스크", t.risks))
    return "\n".join(line for line in lines if line)


def _render_backend_engineer(t: BackendEngineerTake) -> str:
    lines = ["**[backend-engineer]**"]
    if t.data_impact:
        lines.append(f"데이터 영향: {t.data_impact}")
    if t.api_impact:
        lines.append(f"API 영향: {t.api_impact}")
    if t.storage_impact:
        lines.append(f"저장소 영향: {t.storage_impact}")
    lines.append(_bullet_block("리스크", t.risks))
    return "\n".join(line for line in lines if line)


def _render_frontend_engineer(t: FrontendEngineerTake) -> str:
    lines = ["**[frontend-engineer]**"]
    lines.append(_bullet_block("UI 컴포넌트", t.ui_components))
    if t.state_strategy:
        lines.append(f"상태 전략: {t.state_strategy}")
    if t.user_flow:
        lines.append(f"사용자 흐름: {t.user_flow}")
    lines.append(_bullet_block("리스크", t.risks))
    return "\n".join(line for line in lines if line)


def _render_qa_engineer(t: QaEngineerTake) -> str:
    lines = ["**[qa-engineer]**"]
    lines.append(_bullet_block("수용 기준", t.acceptance_criteria))
    lines.append(_bullet_block("리스크", t.risks))
    lines.append(_bullet_block("회귀 대상", t.regression_targets))
    return "\n".join(line for line in lines if line)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short_role(role: str) -> str:
    if "/" in role:
        return role.split("/", 1)[1]
    return role


def _excerpt(text: Optional[str], max_len: int) -> str:
    body = (text or "").strip()
    if not body:
        return "(요청 본문 없음)"
    head = body.splitlines()[0].strip()
    if len(head) > max_len:
        head = head[: max_len - 3] + "..."
    return head or "(요청 본문 없음)"


def _first_line(text: Optional[str], default: str) -> str:
    body = (text or "").strip()
    if not body:
        return default
    head = body.splitlines()[0].strip()
    return head or default


def _bullet_block(label: str, items: Sequence[str]) -> str:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        return f"{label}: 없음"
    bullets = "\n".join(f"  - {item}" for item in cleaned)
    return f"{label}:\n{bullets}"


def _coerce_structured_outcome(outcome: Any, role: str) -> Optional[RoleTake]:
    """Allow the runner to return either a typed RoleTake or shape-compatible dict."""

    if outcome is None:
        return None
    if isinstance(
        outcome,
        (
            TechLeadOpening,
            ProductDesignerTake,
            BackendEngineerTake,
            FrontendEngineerTake,
            QaEngineerTake,
        ),
    ):
        return outcome
    return None


def _todos_from_take(take: RoleTake) -> list[str]:
    if isinstance(take, TechLeadOpening):
        return [f"[tech-lead] {b}" for b in take.task_breakdown]
    if isinstance(take, ProductDesignerTake):
        if take.ux_direction:
            return [f"[product-designer] {take.ux_direction}"]
        return []
    if isinstance(take, BackendEngineerTake):
        items: list[str] = []
        if take.data_impact:
            items.append(f"[backend-engineer] data — {take.data_impact}")
        if take.api_impact:
            items.append(f"[backend-engineer] api — {take.api_impact}")
        return items
    if isinstance(take, FrontendEngineerTake):
        if take.user_flow:
            return [f"[frontend-engineer] flow — {take.user_flow}"]
        return []
    if isinstance(take, QaEngineerTake):
        return [f"[qa-engineer] {ac}" for ac in take.acceptance_criteria]
    return []


def _consensus_summary(session: WorkflowSession, takes: Sequence[RoleTake]) -> str:
    role_names = [_short_role(getattr(take, "role", "")) for take in takes]
    role_text = ", ".join(r for r in role_names if r) or "tech-lead"
    return (
        f"{session.task_type} 작업을 {role_text} 순서로 검토했습니다 — "
        f"실행자 `{session.executor_role or 'tech-lead'}`가 결정 사항을 반영해 진행."
    )


def _session_approved(session: WorkflowSession) -> bool:
    state = getattr(session, "state", None)
    state_value = getattr(state, "value", state)
    return state_value not in (None, "intake")


def _dedup_keep_order(items: Sequence[str]) -> Tuple[str, ...]:
    seen: dict[str, None] = {}
    for item in items:
        text = (item or "").strip()
        if text and text not in seen:
            seen[text] = None
    return tuple(seen.keys())
