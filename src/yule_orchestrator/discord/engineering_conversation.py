"""Engineering-agent free-form conversation layer.

This module is the **conversational front door** for the engineering-agent
gateway in the ``#업무-접수`` channel. It receives a user's natural-language
message and returns a structured :class:`EngineeringConversationResponse`
that downstream code (bot.py, commands.py, future dispatcher) consumes to
decide whether to:

- reply only (general help / clarification questions),
- propose a task split before intake,
- or actually call ``workflow.intake`` because the user confirmed.

It deliberately does **not** import :mod:`workflow` or the dispatcher so it
can be exercised in unit tests without DB/Discord dependencies. The bot
layer is responsible for translating ``ready_to_intake`` into the actual
``workflow.intake`` call.

How this differs from ``discord/conversation.py`` (planning-agent):

- planning conversation is *snapshot-bound* — it leans on
  ``DailyPlanSnapshot`` and answers deterministic queries about the day.
- engineering conversation is *task-shaping* — it interprets a free-form
  request, asks for missing context, suggests breaking down multi-prong
  asks, and only commits to a session once the user explicitly says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Sequence

from ..agents.dispatcher import TaskType


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


GENERAL_ENGINEERING_HELP = "general_engineering_help"
TASK_INTAKE_CANDIDATE = "task_intake_candidate"
NEEDS_CLARIFICATION = "needs_clarification"
CONFIRM_INTAKE = "confirm_intake"
SPLIT_TASK_PROPOSAL = "split_task_proposal"


@dataclass(frozen=True)
class EngineeringIntentMatch:
    """What the user seems to want from engineering-agent right now."""

    intent_id: str
    label: str
    confidence: str = "medium"  # "high" / "medium" / "low"


@dataclass(frozen=True)
class EngineeringConversationResponse:
    """Envelope returned by :func:`build_engineering_conversation_response`.

    Downstream Discord layer reads:

    - ``ready_to_intake=True`` → call ``workflow.intake`` with the
      preserved ``intake_prompt``.
    - ``needs_clarification=True`` → reply with ``content`` and wait for
      another user turn.
    - ``proposed_splits`` non-empty → reply with split proposal; user picks
      one or types a confirmation phrase to proceed with the original ask.
    """

    content: str
    intent_id: str
    ready_to_intake: bool = False
    needs_clarification: bool = False
    proposed_splits: Sequence[str] = field(default_factory=tuple)
    suggested_task_type: Optional[str] = None
    write_likely: bool = False
    intake_prompt: Optional[str] = None
    mention_user_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def build_engineering_conversation_response(
    message_text: str,
    *,
    author_user_id: Optional[int] = None,
    mention_user: bool = False,
    last_proposed_prompt: Optional[str] = None,
) -> EngineeringConversationResponse:
    """Classify *message_text* and produce an actionable response envelope.

    *last_proposed_prompt* lets the caller stash the most recent task-shaped
    message so a follow-up confirmation ("이대로 진행해") can reuse it as
    ``intake_prompt`` instead of the literal confirmation string. The bot
    layer is expected to pass this in from its per-channel state.
    """

    intent = detect_engineering_intent(message_text)
    mention_user_id = author_user_id if mention_user else None

    if intent.intent_id == CONFIRM_INTAKE:
        intake_prompt = last_proposed_prompt or message_text
        suggested = _suggest_task_type(intake_prompt)
        write_likely = _looks_like_write_request(intake_prompt)
        body = (
            "좋습니다. 이대로 작업을 등록할게요.\n"
            "intake가 만들어지면 세션 ID와 승인 안내를 이어서 드릴게요."
        )
        return EngineeringConversationResponse(
            content=_prepend_mention(body, mention_user_id),
            intent_id=CONFIRM_INTAKE,
            ready_to_intake=True,
            suggested_task_type=suggested,
            write_likely=write_likely,
            intake_prompt=intake_prompt,
            mention_user_id=mention_user_id,
        )

    if intent.intent_id == GENERAL_ENGINEERING_HELP:
        body = _format_general_help()
        return EngineeringConversationResponse(
            content=_prepend_mention(body, mention_user_id),
            intent_id=GENERAL_ENGINEERING_HELP,
            mention_user_id=mention_user_id,
        )

    if intent.intent_id == NEEDS_CLARIFICATION:
        body = _format_clarification_question(message_text)
        return EngineeringConversationResponse(
            content=_prepend_mention(body, mention_user_id),
            intent_id=NEEDS_CLARIFICATION,
            needs_clarification=True,
            mention_user_id=mention_user_id,
        )

    if intent.intent_id == SPLIT_TASK_PROPOSAL:
        splits = split_task_branches(message_text)
        body = _format_split_proposal(splits)
        return EngineeringConversationResponse(
            content=_prepend_mention(body, mention_user_id),
            intent_id=SPLIT_TASK_PROPOSAL,
            proposed_splits=tuple(splits),
            suggested_task_type=_suggest_task_type(message_text),
            write_likely=_looks_like_write_request(message_text),
            intake_prompt=message_text,
            mention_user_id=mention_user_id,
        )

    # default: TASK_INTAKE_CANDIDATE
    suggested = _suggest_task_type(message_text)
    write_likely = _looks_like_write_request(message_text)
    body = _format_intake_candidate_question(
        message_text=message_text,
        suggested_task_type=suggested,
        write_likely=write_likely,
    )
    return EngineeringConversationResponse(
        content=_prepend_mention(body, mention_user_id),
        intent_id=TASK_INTAKE_CANDIDATE,
        suggested_task_type=suggested,
        write_likely=write_likely,
        intake_prompt=message_text,
        mention_user_id=mention_user_id,
    )


def detect_engineering_intent(message_text: str) -> EngineeringIntentMatch:
    """Map *message_text* to one of the five engineering intents.

    Order matters: confirmation phrases must short-circuit so that follow-up
    "이대로 진행" never mis-classifies as a new intake.
    """

    normalized = _normalize(message_text)
    if not normalized:
        return EngineeringIntentMatch(
            intent_id=NEEDS_CLARIFICATION,
            label="비어 있는 메시지",
            confidence="high",
        )

    if _is_confirmation(normalized):
        return EngineeringIntentMatch(
            intent_id=CONFIRM_INTAKE,
            label="진행 확정",
            confidence="high",
        )

    if _asks_for_general_help(normalized):
        return EngineeringIntentMatch(
            intent_id=GENERAL_ENGINEERING_HELP,
            label="일반 안내",
            confidence="high",
        )

    if _looks_too_vague(normalized):
        return EngineeringIntentMatch(
            intent_id=NEEDS_CLARIFICATION,
            label="추가 정보 필요",
            confidence="medium",
        )

    if _looks_like_multiple_tasks(message_text):
        return EngineeringIntentMatch(
            intent_id=SPLIT_TASK_PROPOSAL,
            label="작업 분리 제안",
            confidence="medium",
        )

    return EngineeringIntentMatch(
        intent_id=TASK_INTAKE_CANDIDATE,
        label="작업 후보",
        confidence="medium",
    )


def split_task_branches(message_text: str) -> tuple[str, ...]:
    """Heuristic split — returns 2+ sub-prompts when the user combined asks.

    Splits on Korean conjunctions (``그리고``/``또``) and English ``and``
    when surrounded by spaces. Drops empty fragments and trims whitespace.
    """

    parts = re.split(_SPLIT_PATTERN, message_text)
    cleaned = tuple(part.strip(" ,.;:") for part in parts if part and part.strip(" ,.;:"))
    if len(cleaned) <= 1:
        return ()
    return cleaned


# ---------------------------------------------------------------------------
# Intent detection helpers
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


_CONFIRMATION_PHRASES = (
    "이대로 진행",
    "이대로 등록",
    "이걸로 등록",
    "이걸로 진행",
    "그럼 이걸로",
    "그럼 등록",
    "그럼 진행",
    "좋아 진행",
    "좋습니다 진행",
    "오케이 진행",
    "ok 진행",
    "그렇게 등록",
    "그렇게 진행",
    "진행해줘",
    "진행해 주세요",
    "등록해줘",
    "등록해 주세요",
    "yes 등록",
    "yes 진행",
    "go 진행",
    "확정",
    "확정해",
)

_CONFIRMATION_STANDALONE = frozenset(
    {
        "ok",
        "okay",
        "오케이",
        "오케",
        "오키",
        "yes",
        "yep",
        "go",
        "고",
        "ㄱㄱ",
        "확정",
        "진행",
        "등록",
    }
)


def _is_confirmation(normalized: str) -> bool:
    if normalized in _CONFIRMATION_STANDALONE:
        return True
    return any(phrase in normalized for phrase in _CONFIRMATION_PHRASES)


_GENERAL_HELP_PHRASES = (
    "engineering-agent",
    "엔지니어링 에이전트",
    "엔지니어링 봇",
    "어떻게 쓰",
    "어떻게 써",
    "어떻게 사용",
    "기능 알려",
    "도움말",
    "help",
    "what can you do",
    "사용법",
    "뭐 할 수 있",
)


def _asks_for_general_help(normalized: str) -> bool:
    return any(phrase in normalized for phrase in _GENERAL_HELP_PHRASES)


_VAGUE_TOKEN_RUNS = (
    "도와줘",
    "도와 줘",
    "할 일 있어",
    "할일 있어",
    "작업 있어",
    "뭐 해야",
    "뭐해야",
    "할 거",
    "할거",
)


def _looks_too_vague(normalized: str) -> bool:
    if len(normalized) <= 3:
        return True
    word_count = len(normalized.split())
    if word_count == 1:
        return True
    if word_count <= 3 and any(token in normalized for token in _VAGUE_TOKEN_RUNS):
        return True
    return False


_SPLIT_PATTERN = re.compile(r"\s*그리고\s+|\s*,\s*그리고\s+|\s*또\s+|\s+and\s+", re.IGNORECASE)


def _looks_like_multiple_tasks(message_text: str) -> bool:
    branches = split_task_branches(message_text)
    if len(branches) < 2:
        return False
    # Require each fragment to look "task-like" (>=2 words). Otherwise we
    # mis-fire on "음 그리고 좋아".
    return all(len(part.split()) >= 2 for part in branches)


def _looks_like_write_request(message_text: str) -> bool:
    normalized = _normalize(message_text)
    write_signals = (
        "구현",
        "만들",
        "추가",
        "수정",
        "고쳐",
        "고치",
        "리팩",
        "refactor",
        "implement",
        "build",
        "create",
        "fix",
        "패치",
        "patch",
        "PR",
        "pull request",
        "draft",
        "짜야",
        "짜줘",
        "짜자",
        "작성",
        "쓸게",
        "써줘",
    )
    review_signals = ("어떻게 생각", "분석", "리뷰", "review", "검토", "조사")
    if any(signal.lower() in normalized for signal in review_signals):
        return False
    return any(signal.lower() in normalized for signal in write_signals)


# ---------------------------------------------------------------------------
# task_type hint
# ---------------------------------------------------------------------------


_TASK_TYPE_KEYWORDS: tuple[tuple[TaskType, tuple[str, ...]], ...] = (
    (
        TaskType.VISUAL_POLISH,
        ("visual ", "polish", "리디자인", "redesign", "시각 정리", "visual cleanup"),
    ),
    (
        TaskType.ONBOARDING_FLOW,
        ("onboarding", "온보딩", "signup flow", "가입 흐름", "first-run"),
    ),
    (
        TaskType.EMAIL_CAMPAIGN,
        ("email", "이메일", "campaign", "캠페인", "광고", "ad creative"),
    ),
    (TaskType.LANDING_PAGE, ("landing", "랜딩", "marketing page", "히어로")),
    (TaskType.QA_TEST, ("regression", "회귀", "qa", "test plan", "테스트 시나리오")),
    (
        TaskType.PLATFORM_INFRA,
        ("infra", "deploy", "ci ", " ci", "docker", "k8s", "terraform", "github action"),
    ),
    (
        TaskType.FRONTEND_FEATURE,
        ("frontend", "ui ", "component", "컴포넌트", "react", "next.js", "vue"),
    ),
    (
        TaskType.BACKEND_FEATURE,
        ("backend", "api ", "schema", "database", "migration", "도메인", "service layer"),
    ),
)


def _suggest_task_type(message_text: str) -> Optional[str]:
    normalized = _normalize(message_text)
    for task_type, keywords in _TASK_TYPE_KEYWORDS:
        for keyword in keywords:
            if keyword in normalized:
                return task_type.value
    return None


# ---------------------------------------------------------------------------
# Response body formatters
# ---------------------------------------------------------------------------


def _format_general_help() -> str:
    return (
        "engineering-agent입니다. tech-lead처럼 작업을 받아 정리하고, 멤버 봇과 함께 진행 흐름을 만들어요.\n\n"
        "이렇게 말씀해 주시면 도움이 됩니다.\n"
        "- 무엇을 만들거나 고치고 싶은지 한두 문장으로 설명\n"
        "- 참고할 화면/링크가 있으면 함께 붙여 주세요\n"
        "- 작업이 여러 갈래면 한 번에 적어 주셔도 좋아요. 제가 나누어 제안할게요.\n\n"
        "확정 단계에서 `이대로 진행`이라고 말씀하시면 세션을 만들어 다음 단계로 이어갑니다."
    )


def _format_clarification_question(message_text: str) -> str:
    text = message_text.strip() or "(빈 메시지)"
    return (
        f"`{text}`만으로는 작업 범위가 잡히지 않아 한 번 되짚어 볼게요.\n\n"
        "다음 중 한두 가지를 알려 주시면 더 정확하게 도와드릴 수 있어요.\n"
        "- 어느 화면 / API / 흐름을 다루고 싶은지\n"
        "- 지금 막힌 지점이 무엇인지 또는 원하는 결과가 무엇인지\n"
        "- 참고하고 싶은 링크나 스크린샷이 있는지"
    )


def _format_split_proposal(splits: Sequence[str]) -> str:
    if not splits:
        return _format_intake_candidate_question(
            message_text="",
            suggested_task_type=None,
            write_likely=False,
        )
    lines = ["요청에 갈래가 여러 개 보여요. 아래처럼 나눠 진행하는 안을 제안합니다."]
    for idx, branch in enumerate(splits, start=1):
        lines.append(f"{idx}. {branch}")
    lines.append(
        "\n각각 별도 세션으로 만들거나, 그대로 하나로 묶어서 진행할 수 있어요. "
        "원하시는 방식을 알려 주시면 그쪽으로 정리하고, `이대로 진행`이라고 하시면 한 세션으로 등록할게요."
    )
    return "\n".join(lines)


def _format_intake_candidate_question(
    *,
    message_text: str,
    suggested_task_type: Optional[str],
    write_likely: bool,
) -> str:
    parts: list[str] = []
    if message_text.strip():
        parts.append("작업 후보로 정리해 봤어요. 아래 내용으로 진행해도 될까요?")
        parts.append(f"> {message_text.strip()}")
    else:
        parts.append("작업 후보로 정리해 봤어요. 아래 내용으로 진행해도 될까요?")

    meta_lines: list[str] = []
    if suggested_task_type:
        meta_lines.append(f"- 추정 분류: `{suggested_task_type}`")
    if write_likely:
        meta_lines.append("- 코드/문서 쓰기를 동반할 것으로 보입니다 → 진행 시 승인 단계가 들어갑니다.")
    else:
        meta_lines.append("- 분석/검토 위주로 보여 승인 단계 없이 진행해도 괜찮아 보입니다.")
    parts.append("\n".join(meta_lines))

    parts.append(
        "맞으면 `이대로 진행`이라고 답해 주세요. 빠진 컨텍스트가 있으면 추가 메시지로 보강해 주셔도 좋아요."
    )
    return "\n\n".join(parts)


def _prepend_mention(content: str, mention_user_id: Optional[int]) -> str:
    if mention_user_id is None:
        return content
    return f"<@{mention_user_id}>\n\n{content}".strip()
