from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from ..planning.ollama import generate_ollama_text
from ..planning.ollama_config import load_ollama_conversation_config
from ..planning.snapshots import DailyPlanSnapshot
from .formatter import (
    format_missing_plan_snapshot_message,
    format_plan_today_message,
)
from .planning_runtime import build_due_checkpoints, load_plan_today_snapshot


@dataclass(frozen=True)
class ConversationIntentMatch:
    intent_id: str
    label: str
    requires_snapshot: bool = True
    proposal_only: bool = False


def build_conversation_response(
    message_text: str,
    *,
    author_user_id: int | None,
    mention_user: bool = False,
    reference_time: datetime | None = None,
    checkpoint_window_minutes: int = 60,
) -> str:
    now = reference_time or datetime.now().astimezone()
    mention_user_id = author_user_id if mention_user else None
    intent = detect_conversation_intent(message_text)
    snapshot = load_plan_today_snapshot(now.date())
    due_checkpoints = _load_due_checkpoints_for_intent(
        intent=intent,
        reference_time=now,
        checkpoint_window_minutes=checkpoint_window_minutes,
    )

    if snapshot is None and intent.requires_snapshot:
        return format_missing_plan_snapshot_message(mention_user_id=mention_user_id)

    if snapshot is not None:
        content = _build_ollama_conversation_response(
            message_text=message_text,
            intent=intent,
            snapshot=snapshot,
            due_checkpoints=due_checkpoints,
        )
        if content is not None:
            return _prepend_mention(content, mention_user_id=mention_user_id)

    return _prepend_mention(
        _build_fallback_conversation_response(
            message_text=message_text,
            intent=intent,
            snapshot=snapshot,
            due_checkpoints=due_checkpoints,
            reference_time=now,
        ),
        mention_user_id=mention_user_id,
    )


def detect_conversation_intent(message_text: str) -> ConversationIntentMatch:
    normalized = _normalize_message(message_text)

    if _asks_for_schedule_change_proposal(normalized):
        return ConversationIntentMatch(
            intent_id="schedule_change_proposal",
            label="일정 수정 제안",
            requires_snapshot=True,
            proposal_only=True,
        )
    if _asks_for_checkpoints(normalized):
        return ConversationIntentMatch(
            intent_id="checkpoint_lookup",
            label="체크포인트 조회",
            requires_snapshot=False,
        )
    if _asks_for_full_briefing(normalized):
        return ConversationIntentMatch(
            intent_id="briefing_refresh",
            label="브리핑 재요청",
            requires_snapshot=True,
        )
    if _asks_for_priorities(normalized):
        return ConversationIntentMatch(
            intent_id="priority_recommendation",
            label="우선순위 추천",
            requires_snapshot=True,
        )
    return ConversationIntentMatch(
        intent_id="general_help",
        label="일반 대화",
        requires_snapshot=False,
    )


def _build_ollama_conversation_response(
    *,
    message_text: str,
    intent: ConversationIntentMatch,
    snapshot: DailyPlanSnapshot,
    due_checkpoints: Sequence[object],
) -> str | None:
    config = load_ollama_conversation_config()
    if not config.enabled:
        return None

    prompt = _build_ollama_prompt(
        message_text=message_text,
        intent=intent,
        snapshot=snapshot,
        due_checkpoints=due_checkpoints,
    )

    try:
        content = generate_ollama_text(
            prompt,
            model=config.model,
            endpoint=config.endpoint,
            timeout_seconds=config.timeout_seconds,
            temperature=0.25,
            empty_error_message="Ollama Discord conversation response was empty.",
            request_label="discord conversation",
        )
    except ValueError:
        return None

    return _normalize_model_response(content)


def _build_ollama_prompt(
    *,
    message_text: str,
    intent: ConversationIntentMatch,
    snapshot: DailyPlanSnapshot,
    due_checkpoints: Sequence[object],
) -> str:
    plan = snapshot.envelope.daily_plan
    freshness = "stale" if snapshot.is_stale else "fresh"
    top_tasks = [
        f"- {task.title} | 우선순위={task.priority_level} | 기한={task.due_date or '없음'}"
        for task in plan.prioritized_tasks[:3]
    ] or ["- 추천 작업 없음"]
    focus_blocks = [
        f"- {datetime.fromisoformat(block.start).strftime('%H:%M')}~{datetime.fromisoformat(block.end).strftime('%H:%M')} {block.title}"
        for block in plan.suggested_time_blocks[:3]
    ] or ["- 집중 시간대 없음"]
    checkpoint_lines = [
        f"- {datetime.fromisoformat(checkpoint.remind_at).strftime('%H:%M')} {checkpoint.prompt}"
        for checkpoint in due_checkpoints[:5]
    ] or [
        f"- {datetime.fromisoformat(checkpoint.remind_at).strftime('%H:%M')} {checkpoint.prompt}"
        for checkpoint in plan.checkpoints[:5]
    ] or ["- 체크포인트 없음"]

    intent_guide = _intent_guide(intent)

    return f"""당신은 Discord 안에서 동작하는 개인 Planning Assistant입니다.
아래 snapshot을 기반으로 한국어 답변을 작성하세요.

절대 규칙:
- snapshot에 없는 사실을 지어내지 말 것
- 일정/상태 변경 요청은 실행된 것처럼 말하지 말 것
- 일정 수정, 완료 처리, 이동, 삭제 요청은 반드시 proposal만 반환할 것
- 문단 사이에는 빈 줄을 하나 넣고, 문장은 짧고 자연스럽게 유지할 것
- raw field 이름, score 숫자, ISO datetime 원문을 그대로 노출하지 말 것
- 필요한 시간 표기는 HH:MM 형식으로 풀어 쓸 것

응답 스타일:
- 2~4개의 짧은 문단
- heading 남발 금지
- 필요한 경우에만 간단한 bullet 사용
- 사용자가 바로 다음 행동을 알 수 있게 마무리할 것

현재 intent:
- {intent.intent_id} ({intent.label})

intent별 추가 지침:
{intent_guide}

사용자 메시지:
{message_text}

snapshot 상태:
- plan_date={plan.plan_date.isoformat()}
- snapshot_generated_at={snapshot.generated_at.isoformat()}
- snapshot_freshness={freshness}
- discord_briefing={plan.discord_briefing}
- morning_briefing={plan.morning_briefing}

우선순위 작업:
{chr(10).join(top_tasks)}

추천 집중 시간대:
{chr(10).join(focus_blocks)}

체크포인트:
{chr(10).join(checkpoint_lines)}
"""


def _intent_guide(intent: ConversationIntentMatch) -> str:
    if intent.intent_id == "briefing_refresh":
        return (
            "- 오늘 흐름을 다시 설명하되, 첫 우선 작업과 다음 집중 시간대를 자연스럽게 강조할 것\n"
            "- snapshot 기준 시각을 한 번만 짧게 언급할 것"
        )
    if intent.intent_id == "priority_recommendation":
        return (
            "- 지금 가장 먼저 할 일 1개를 분명하게 추천할 것\n"
            "- 2순위가 있으면 이어서 짧게 덧붙일 것\n"
            "- 왜 그렇게 보는지 snapshot 근거를 짧게 설명할 것"
        )
    if intent.intent_id == "checkpoint_lookup":
        return (
            "- 가장 가까운 체크포인트를 시간과 함께 알려줄 것\n"
            "- 체크포인트가 없으면 없다고 짧게 말하고 다음에 물어볼 만한 질문 한 개를 제안할 것"
        )
    if intent.intent_id == "schedule_change_proposal":
        return (
            "- 실제 반영 금지, proposal only\n"
            "- `제안:` `이유:` `승인 전 메모:` 세 블록으로 답할 것\n"
            "- 사용자의 원문 요청을 반영해 어느 시간대/작업을 어떻게 조정하면 좋을지 제안할 것"
        )
    return (
        "- 사용자의 문장이 모호하면 현재 snapshot 기준으로 가장 도움이 되는 방향을 제안할 것\n"
        "- 마지막 문단에서 예시 질문 1~2개를 자연스럽게 이어 줄 것"
    )


def _normalize_model_response(content: str) -> str:
    lines = [line.rstrip() for line in content.replace("\r\n", "\n").strip().splitlines()]
    normalized_lines: list[str] = []
    previous_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank and previous_blank:
            continue
        normalized_lines.append(line.strip() if not is_blank else "")
        previous_blank = is_blank
    return "\n".join(normalized_lines).strip()


def _build_fallback_conversation_response(
    *,
    message_text: str,
    intent: ConversationIntentMatch,
    snapshot: DailyPlanSnapshot | None,
    due_checkpoints: Sequence[object],
    reference_time: datetime,
) -> str:
    if intent.intent_id == "checkpoint_lookup":
        return _format_checkpoint_response(
            due_checkpoints=due_checkpoints,
            reference_time=reference_time,
        )

    if snapshot is None:
        return (
            "아직 오늘 snapshot이 준비되지 않아서 자세한 답을 바로 드리긴 어렵습니다.\n\n"
            "먼저 `yule planning snapshot --json`으로 snapshot을 만든 뒤 다시 물어보면 더 정확하게 도와드릴 수 있어요."
        )

    if intent.intent_id == "briefing_refresh":
        return format_plan_today_message(
            snapshot.envelope,
            mention_user_id=None,
            snapshot=snapshot,
        )
    if intent.intent_id == "priority_recommendation":
        return _format_priority_response(snapshot=snapshot)
    if intent.intent_id == "schedule_change_proposal":
        return _format_schedule_change_proposal(
            snapshot=snapshot,
            message_text=message_text,
        )
    return _format_general_help(snapshot=snapshot)


def _format_priority_response(*, snapshot: DailyPlanSnapshot) -> str:
    plan = snapshot.envelope.daily_plan
    lines: list[str] = []
    if plan.prioritized_tasks:
        top_task = plan.prioritized_tasks[0]
        lines.append(f"지금 기준으로는 `{top_task.title}`부터 잡는 편이 가장 좋아 보입니다.")
        if len(plan.prioritized_tasks) > 1:
            lines.append(f"그 다음 후보는 `{plan.prioritized_tasks[1].title}`입니다.")
    else:
        lines.append("지금 snapshot에는 뚜렷한 우선 작업이 아직 없습니다.")

    if plan.suggested_time_blocks:
        first_block = plan.suggested_time_blocks[0]
        start_label = datetime.fromisoformat(first_block.start).strftime("%H:%M")
        end_label = datetime.fromisoformat(first_block.end).strftime("%H:%M")
        lines.append(f"집중 시간대는 {start_label}~{end_label}에 `{first_block.title}`로 잡혀 있습니다.")

    if plan.checkpoints:
        first_checkpoint = datetime.fromisoformat(plan.checkpoints[0].remind_at).strftime("%H:%M")
        lines.append(f"가장 가까운 체크포인트는 {first_checkpoint}입니다.")

    return "\n\n".join(lines)


def _format_checkpoint_response(
    *,
    due_checkpoints: Sequence[object],
    reference_time: datetime,
) -> str:
    if not due_checkpoints:
        return (
            f"{reference_time.strftime('%H:%M')} 기준으로 바로 다가오는 체크포인트는 없습니다.\n\n"
            "필요하면 오늘 우선순위나 브리핑을 다시 같이 정리해 드릴게요."
        )

    rendered = []
    for checkpoint in due_checkpoints[:3]:
        remind_at = datetime.fromisoformat(checkpoint.remind_at).strftime("%H:%M")
        rendered.append(f"{remind_at}에 `{checkpoint.prompt}` 체크가 예정돼 있습니다.")
    return "\n\n".join(rendered)


def _format_schedule_change_proposal(
    *,
    snapshot: DailyPlanSnapshot,
    message_text: str,
) -> str:
    plan = snapshot.envelope.daily_plan
    top_task = plan.prioritized_tasks[0].title if plan.prioritized_tasks else "현재 최우선 작업"
    next_checkpoint = (
        datetime.fromisoformat(plan.checkpoints[0].remind_at).strftime("%H:%M")
        if plan.checkpoints
        else "다음 체크포인트 없음"
    )
    return (
        "제안:\n"
        f"- 요청하신 `{message_text.strip()}` 방향으로 조정안을 먼저 검토해 볼게요.\n"
        f"- 현재 흐름을 기준으로는 `{top_task}`를 크게 깨지 않는 선에서 시간을 재배치하는 안이 안전합니다.\n\n"
        "이유:\n"
        f"- 지금 snapshot 기준 우선순위와 다음 체크포인트({next_checkpoint})를 함께 보면, 급하게 전체 순서를 바꾸기보다 영향 범위를 좁혀 조정하는 편이 리스크가 적습니다.\n\n"
        "승인 전 메모:\n"
        "- 아직 실제 일정이나 상태는 변경하지 않았습니다.\n"
        "- 원하시면 다음 응답에서는 이동 대상 시간대와 밀려나는 작업까지 proposal 형태로 더 구체화해 드릴게요."
    )


def _format_general_help(*, snapshot: DailyPlanSnapshot) -> str:
    return (
        f"지금은 {snapshot.generated_at.strftime('%H:%M')} snapshot 기준으로 답하고 있습니다.\n\n"
        "브리핑 재요청, 우선순위 추천, 다음 체크포인트 확인, 일정 조정 proposal까지 이어서 도와드릴 수 있어요.\n\n"
        "예를 들면 `오늘 브리핑 다시 정리해줘`, `지금 뭐부터 해야 해?`, `다음 체크포인트 알려줘`, `오후 일정 좀 옮기는 안 제안해줘`처럼 말해 주면 됩니다."
    )


def _load_due_checkpoints_for_intent(
    *,
    intent: ConversationIntentMatch,
    reference_time: datetime,
    checkpoint_window_minutes: int,
) -> Sequence[object]:
    if intent.intent_id != "checkpoint_lookup":
        return []
    return build_due_checkpoints(reference_time, window_minutes=checkpoint_window_minutes)


def _prepend_mention(content: str, *, mention_user_id: int | None) -> str:
    if mention_user_id is None:
        return content
    return f"<@{mention_user_id}>\n\n{content}".strip()


def _normalize_message(message_text: str) -> str:
    return " ".join(message_text.lower().split())


def _asks_for_schedule_change_proposal(normalized: str) -> bool:
    keywords = (
        "옮겨",
        "변경",
        "수정",
        "바꿔",
        "미루",
        "미뤄",
        "당겨",
        "연기",
        "취소",
        "삭제",
        "추가",
        "완료",
        "일정 조정",
        "일정 수정",
        "제안",
    )
    return any(keyword in normalized for keyword in keywords)


def _asks_for_checkpoints(normalized: str) -> bool:
    keywords = ("체크포인트", "점검", "알림", "다음 일정", "언제")
    return any(keyword in normalized for keyword in keywords)


def _asks_for_full_briefing(normalized: str) -> bool:
    keywords = ("브리핑", "요약", "정리")
    has_refresh_request = any(keyword in normalized for keyword in ("다시", "재요청", "다시 해", "다시 정리"))
    return has_refresh_request or any(keyword in normalized for keyword in keywords)


def _asks_for_priorities(normalized: str) -> bool:
    keywords = ("뭐부터", "우선", "먼저", "추천", "중요", "우선순위")
    return any(keyword in normalized for keyword in keywords)
