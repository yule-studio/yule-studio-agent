"""Sequential team conversation runtime for engineering-agent member bots.

MVP scope: once a workflow session has a Discord ``thread_id``, walk the
``role_sequence`` in order and let each role bot post one short, role-shaped
message in that thread. tech-lead opens, then product-designer / backend-engineer
/ frontend-engineer / qa-engineer follow whichever order the dispatcher picked.

This is *not* a free discussion layer. Each role utterance is a templated
opening based on the session metadata (task type, executor role, write gate
status, references). The point of the MVP is to prove the thread can carry
multi-bot dialogue at all, so a tech lead reading the channel sees something
that resembles a team handoff instead of one silent gateway monologue.

The runtime is pure-Python so it can be exercised without a Discord client:
- ``build_turn_plan`` returns the ordered turn list for a session.
- ``handle_team_turn_message`` is what each member bot calls inside its
  ``on_message`` handler — it parses the dispatch marker, decides whether
  *this* role should speak, and returns the rendered message + the next
  dispatch directive.
- ``mark_turn_played`` / ``next_pending_turn`` give the gateway and the bot
  a shared view of "who has spoken so far" via ``WorkflowSession.extra``.

The Discord-side glue (creating the thread, posting the kickoff, mutating
the session state) lives in the gateway. Member bots only need this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Callable, Mapping, Optional, Sequence, Tuple

from ..agents.deliberation import (
    DeliberationContext,
    RoleTake,
    TechLeadSynthesis,
    render_role_take,
    render_synthesis,
    run_role_deliberation,
    synthesize,
)
from ..agents.research_pack import ResearchPack
from ..agents.workflow_state import WorkflowSession, load_session


TEAM_CONVERSATION_KEY = "team_conversation"
PLAYED_ROLES_KEY = "played_roles"

DISPATCH_MARKER_RE = re.compile(
    r"\[team-turn:(?P<sid>[A-Za-z0-9_\-]+)(?:\s+(?P<role>[A-Za-z0-9_\-]+))?\]"
)


@dataclass(frozen=True)
class TeamTurn:
    """One role's scripted turn inside a session thread."""

    session_id: str
    role: str
    is_executor: bool
    sequence_index: int
    thread_id: int
    header: str
    body: str

    def render(self) -> str:
        return f"**[{self.role}]** {self.header}\n{self.body}"


@dataclass(frozen=True)
class TeamTurnOutcome:
    """What a member bot should post in response to a dispatch directive.

    ``message`` is what to say. ``next_directive`` is appended so the next
    role's bot picks up the chain; ``None`` means this turn closes the
    conversation and the bot should not chain further.
    """

    turn: TeamTurn
    message: str
    next_directive: Optional[str]
    is_final: bool

    def full_post(self) -> str:
        if self.next_directive is None:
            return self.message
        return f"{self.message}\n\n{self.next_directive}"


# ---------------------------------------------------------------------------
# Role-specific opening templates
# ---------------------------------------------------------------------------


_ROLE_HEADERS: Mapping[str, str] = {
    "tech-lead": "팀 합류, 작업 정리부터 갑니다.",
    "product-designer": "디자인 관점에서 짚어볼게요.",
    "frontend-engineer": "프론트 관점에서 정리해 둘게요.",
    "backend-engineer": "백엔드 관점에서 정리합니다.",
    "qa-engineer": "QA 관점에서 체크리스트 잡습니다.",
}

_ROLE_BODY_BUILDERS: Mapping[
    str, Callable[["_TurnContext"], str]
] = {}


@dataclass(frozen=True)
class _TurnContext:
    session: WorkflowSession
    role: str
    is_executor: bool

    @property
    def task_type(self) -> str:
        return self.session.task_type or "unknown"

    @property
    def executor_role(self) -> str:
        return self.session.executor_role or "tech-lead"

    @property
    def references(self) -> Tuple[str, ...]:
        merged = tuple(self.session.references_user) + tuple(
            self.session.references_suggested
        )
        return merged

    @property
    def prompt_excerpt(self) -> str:
        first_line = (self.session.prompt or "").strip().splitlines()
        if not first_line:
            return "(요청 본문 없음)"
        head = first_line[0].strip()
        if len(head) > 80:
            head = head[:77] + "..."
        return head or "(요청 본문 없음)"


def _tech_lead_body(ctx: _TurnContext) -> str:
    lines = [
        f"분류: `{ctx.task_type}` · 실행자: `{ctx.executor_role}`.",
        f"요청: {ctx.prompt_excerpt}",
    ]
    if ctx.session.write_requested and ctx.session.write_blocked_reason:
        lines.append(
            "쓰기 작업은 승인 대기 중입니다. 먼저 의견 정리부터 받겠습니다."
        )
    if ctx.references:
        lines.append(
            f"참고 reference {len(ctx.references)}건 공유 — 각자 본인 영역에서 어떻게 활용할지 짧게 댓글 부탁드립니다."
        )
    else:
        lines.append("자료 reference는 따로 없습니다. 각자 도메인 기준으로 시작합시다.")
    lines.append("순서대로 한 마디씩 받겠습니다.")
    return "\n".join(lines)


def _product_designer_body(ctx: _TurnContext) -> str:
    refs = ", ".join(ctx.references[:3]) if ctx.references else "(reference 없음)"
    role_self = "내가 실행자" if ctx.is_executor else f"실행자({ctx.executor_role})"
    return (
        f"reference 검토: {refs}.\n"
        f"{role_self}에게 톤·레이아웃 가이드 1차 정리해서 thread에 붙이겠습니다."
    )


def _frontend_engineer_body(ctx: _TurnContext) -> str:
    role_self = "본인 영역" if ctx.is_executor else f"실행자({ctx.executor_role})"
    return (
        "컴포넌트/레이아웃 분해 검토 시작합니다.\n"
        f"{role_self} 합류 시 협업 포인트(상태 / 데이터 바인딩)는 thread에서 동기화하겠습니다."
    )


def _backend_engineer_body(ctx: _TurnContext) -> str:
    role_self = "내가 실행자" if ctx.is_executor else f"실행자({ctx.executor_role})"
    return (
        "도메인 / API 영향 검토 들어갑니다.\n"
        f"{role_self}와 schema·migration 충돌 여부 thread에 메모로 남기겠습니다."
    )


def _qa_engineer_body(ctx: _TurnContext) -> str:
    role_self = "내가 실행자" if ctx.is_executor else f"실행자({ctx.executor_role})"
    return (
        "테스트 시나리오 초안 잡습니다.\n"
        f"{role_self} 작업이 끝나면 회귀 영향 점검 결과를 같은 thread에 회신하겠습니다."
    )


_ROLE_BODY_BUILDERS = {
    "tech-lead": _tech_lead_body,
    "product-designer": _product_designer_body,
    "frontend-engineer": _frontend_engineer_body,
    "backend-engineer": _backend_engineer_body,
    "qa-engineer": _qa_engineer_body,
}


def _generic_body(ctx: _TurnContext) -> str:
    role_self = "내가 실행자" if ctx.is_executor else f"실행자({ctx.executor_role})"
    return f"{ctx.role} 관점에서 검토 들어가겠습니다. {role_self} 기준으로 thread 회신 이어가겠습니다."


def format_role_turn_text(
    session: WorkflowSession,
    role: str,
    *,
    is_executor: bool,
) -> Tuple[str, str]:
    """Return ``(header, body)`` for one role's turn message.

    Roles outside the canonical engineering set fall back to a generic
    template so a custom role sequence still produces a coherent line.
    """

    ctx = _TurnContext(session=session, role=role, is_executor=is_executor)
    header = _ROLE_HEADERS.get(role, f"{role} 관점에서 정리합니다.")
    builder = _ROLE_BODY_BUILDERS.get(role, _generic_body)
    return header, builder(ctx)


# ---------------------------------------------------------------------------
# Plan / state helpers
# ---------------------------------------------------------------------------


def build_turn_plan(session: WorkflowSession) -> Tuple[TeamTurn, ...]:
    """Build the ordered turn plan for a session.

    Requires ``session.thread_id`` and a non-empty ``role_sequence``. The
    gateway (D's territory) is responsible for setting both before calling.
    """

    if session.thread_id is None:
        raise ValueError(
            f"session {session.session_id} has no thread_id; thread must be created before team conversation"
        )
    if not session.role_sequence:
        raise ValueError(
            f"session {session.session_id} has no role_sequence; dispatcher must populate it"
        )

    plan: list[TeamTurn] = []
    for idx, role in enumerate(session.role_sequence):
        is_executor = role == session.executor_role
        header, body = format_role_turn_text(session, role, is_executor=is_executor)
        plan.append(
            TeamTurn(
                session_id=session.session_id,
                role=role,
                is_executor=is_executor,
                sequence_index=idx,
                thread_id=int(session.thread_id),
                header=header,
                body=body,
            )
        )
    return tuple(plan)


def played_roles(session: WorkflowSession) -> Tuple[str, ...]:
    """Roles that have already taken their turn in this session."""

    block = (session.extra or {}).get(TEAM_CONVERSATION_KEY) or {}
    return tuple(str(r) for r in (block.get(PLAYED_ROLES_KEY) or ()))


def next_pending_turn(session: WorkflowSession) -> Optional[TeamTurn]:
    """First turn in the plan whose role has not posted yet."""

    plan = build_turn_plan(session)
    played = set(played_roles(session))
    for turn in plan:
        if turn.role not in played:
            return turn
    return None


def mark_turn_played(session: WorkflowSession, role: str) -> WorkflowSession:
    """Return a copy of *session* with ``role`` recorded as having spoken.

    The caller is responsible for persisting via
    ``workflow_state.update_session`` so this module stays free of side
    effects (and easy to test without a SQLite cache).
    """

    extra = dict(session.extra or {})
    block = dict(extra.get(TEAM_CONVERSATION_KEY) or {})
    played = list(block.get(PLAYED_ROLES_KEY) or ())
    if role not in played:
        played.append(role)
    block[PLAYED_ROLES_KEY] = played
    extra[TEAM_CONVERSATION_KEY] = block
    return replace(session, extra=extra)


# ---------------------------------------------------------------------------
# Dispatch protocol
# ---------------------------------------------------------------------------


def parse_dispatch_marker(text: str) -> Optional[Tuple[str, Optional[str]]]:
    """Parse ``[team-turn:<sid> <role>]`` (role optional) out of a message.

    Returns ``(session_id, role_or_None)`` or ``None`` if no marker is
    present. Used both by the gateway when emitting directives and by
    member bots when filtering inbound messages.
    """

    match = DISPATCH_MARKER_RE.search(text or "")
    if not match:
        return None
    return match.group("sid"), match.group("role")


def dispatch_directive(turn: TeamTurn) -> str:
    """Marker the *previous* speaker appends to hand off to *turn*'s role."""

    return f"[team-turn:{turn.session_id} {turn.role}]"


def kickoff_directive(session: WorkflowSession) -> str:
    """Marker the gateway posts in the thread to start the chain.

    Always targets the first role in ``role_sequence`` (typically
    ``tech-lead``). Raises ``ValueError`` if the session has no plan yet.
    """

    plan = build_turn_plan(session)
    return dispatch_directive(plan[0])


# ---------------------------------------------------------------------------
# Member-bot entry point
# ---------------------------------------------------------------------------


SessionLoader = Callable[[str], Optional[WorkflowSession]]


def handle_team_turn_message(
    *,
    role: str,
    text: str,
    session_loader: Optional[SessionLoader] = None,
) -> Optional[TeamTurnOutcome]:
    """Decide what (if anything) the bot for *role* should post.

    Pure-Python; the Discord layer is responsible for taking the returned
    ``TeamTurnOutcome.full_post()`` and sending it. Returns ``None`` when:

    - the message has no dispatch marker, or
    - the marker targets a different role, or
    - the session is unknown, or
    - the session does not include this role in its plan, or
    - the role has already posted.
    """

    parsed = parse_dispatch_marker(text)
    if parsed is None:
        return None
    session_id, target_role = parsed
    if target_role is not None and target_role != role:
        return None

    loader = session_loader or load_session
    session = loader(session_id)
    if session is None:
        return None

    try:
        plan = build_turn_plan(session)
    except ValueError:
        return None

    my_turn = next((t for t in plan if t.role == role), None)
    if my_turn is None:
        return None

    if role in played_roles(session):
        return None

    next_turn = _next_unplayed_after(plan, role, session)
    next_directive = dispatch_directive(next_turn) if next_turn else None
    is_final = next_turn is None

    return TeamTurnOutcome(
        turn=my_turn,
        message=my_turn.render(),
        next_directive=next_directive,
        is_final=is_final,
    )


def _next_unplayed_after(
    plan: Sequence[TeamTurn],
    role: str,
    session: WorkflowSession,
) -> Optional[TeamTurn]:
    played = set(played_roles(session)) | {role}
    saw_self = False
    for turn in plan:
        if turn.role == role:
            saw_self = True
            continue
        if not saw_self:
            continue
        if turn.role not in played:
            return turn
    return None


# ---------------------------------------------------------------------------
# Deliberation-aware extension (pack-driven structured turns)
# ---------------------------------------------------------------------------


def deliberation_role_turn(
    session: WorkflowSession,
    role: str,
    *,
    research_pack: Optional[ResearchPack] = None,
    previous_turns: Sequence[RoleTake] = (),
    runner_fn=None,
) -> Tuple[RoleTake, str]:
    """Produce a structured role take + rendered Discord text.

    Sits next to ``format_role_turn_text`` for callers that have a
    ``ResearchPack`` (e.g. forum-driven sessions) and want the richer
    contract instead of the bare templated line. ``runner_fn`` is the
    optional LLM hook; when None or when it raises, the deterministic
    fallback inside ``run_role_deliberation`` handles the response.
    """

    context = DeliberationContext(
        session=session,
        role=role,
        research_pack=research_pack,
        previous_turns=tuple(previous_turns),
    )
    take = run_role_deliberation(context, runner_fn=runner_fn)
    return take, render_role_take(take)


def synthesize_thread(
    session: WorkflowSession,
    role_takes: Sequence[RoleTake],
    *,
    research_pack: Optional[ResearchPack] = None,
) -> Tuple[TechLeadSynthesis, str]:
    """Run tech-lead synthesis and return both the dataclass and rendered text."""

    synth = synthesize(session, role_takes, research_pack=research_pack)
    return synth, render_synthesis(synth)


def closing_message(session: WorkflowSession) -> str:
    """Final wrap-up the last role appends after speaking.

    Kept as a separate helper so the gateway / closing role can reuse it
    without rebuilding the plan.
    """

    return (
        "팀 합류 1차 의견 정리 완료. "
        f"세션 `{session.session_id}` thread에서 이어서 진행합니다."
    )
