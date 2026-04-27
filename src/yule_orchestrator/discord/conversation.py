from __future__ import annotations

from datetime import datetime

from .formatter import (
    format_checkpoints_message,
    format_missing_plan_snapshot_message,
    format_plan_today_message,
)
from .planning_runtime import build_due_checkpoints, load_plan_today_snapshot


def build_conversation_response(
    message_text: str,
    *,
    author_user_id: int | None,
    reference_time: datetime | None = None,
    checkpoint_window_minutes: int = 60,
) -> str:
    now = reference_time or datetime.now().astimezone()
    mention_user_id = author_user_id
    normalized = _normalize_message(message_text)

    if _asks_for_checkpoints(normalized):
        checkpoints = build_due_checkpoints(now, window_minutes=checkpoint_window_minutes)
        return format_checkpoints_message(
            checkpoints,
            reference_time=now,
            mention_user_id=mention_user_id,
        )

    snapshot = load_plan_today_snapshot(now.date())
    if snapshot is None:
        return format_missing_plan_snapshot_message(mention_user_id=mention_user_id)

    if _asks_for_full_briefing(normalized):
        return format_plan_today_message(
            snapshot.envelope,
            mention_user_id=mention_user_id,
            snapshot=snapshot,
        )

    if _asks_for_priorities(normalized):
        return _format_priority_response(snapshot=snapshot, mention_user_id=mention_user_id)

    return _format_help_response(snapshot=snapshot, mention_user_id=mention_user_id)


def _format_priority_response(*, snapshot, mention_user_id: int | None) -> str:
    plan = snapshot.envelope.daily_plan
    lines: list[str] = []
    if mention_user_id is not None:
        lines.append(f"<@{mention_user_id}>")
        lines.append("")

    lines.append("지금 기준으로는 이렇게 보는 게 좋아요.")
    if plan.prioritized_tasks:
        top_task = plan.prioritized_tasks[0]
        lines.append(f"- 가장 먼저 볼 일: {top_task.title}")
        if len(plan.prioritized_tasks) > 1:
            lines.append(f"- 다음 후보: {plan.prioritized_tasks[1].title}")
        if len(plan.prioritized_tasks) > 2:
            lines.append(f"- 세 번째 후보: {plan.prioritized_tasks[2].title}")
    else:
        lines.append("- 아직 추천 작업이 없습니다. 먼저 브리핑을 다시 생성하는 편이 좋습니다.")

    if plan.suggested_time_blocks:
        first_block = plan.suggested_time_blocks[0]
        start_label = datetime.fromisoformat(first_block.start).strftime("%H:%M")
        end_label = datetime.fromisoformat(first_block.end).strftime("%H:%M")
        lines.append(f"- 첫 집중 시간대: {start_label}~{end_label} {first_block.title}")

    if plan.checkpoints:
        first_checkpoint = datetime.fromisoformat(plan.checkpoints[0].remind_at).strftime("%H:%M")
        lines.append(f"- 다음 체크포인트: {first_checkpoint}")

    return "\n".join(lines)


def _format_help_response(*, snapshot, mention_user_id: int | None) -> str:
    lines: list[str] = []
    if mention_user_id is not None:
        lines.append(f"<@{mention_user_id}>")
        lines.append("")

    lines.append("지금은 Planning 대화형 MVP라서 아래처럼 말해 주면 바로 도와줄 수 있어요.")
    lines.append("- 오늘 일정 브리핑 다시 해줘")
    lines.append("- 오늘 뭐부터 해야 해?")
    lines.append("- 다음 체크포인트 알려줘")
    lines.append("")
    lines.append(
        f"참고로 마지막 스냅샷 생성 시각은 {snapshot.generated_at.strftime('%Y-%m-%d %H:%M')}입니다."
    )
    return "\n".join(lines)


def _normalize_message(message_text: str) -> str:
    return " ".join(message_text.lower().split())


def _asks_for_checkpoints(normalized: str) -> bool:
    keywords = ("체크포인트", "점검", "알림", "다음 일정", "언제")
    return any(keyword in normalized for keyword in keywords)


def _asks_for_full_briefing(normalized: str) -> bool:
    keywords = ("브리핑", "일정", "다시", "요약", "정리")
    return any(keyword in normalized for keyword in keywords)


def _asks_for_priorities(normalized: str) -> bool:
    keywords = ("뭐부터", "우선", "먼저", "추천", "중요")
    return any(keyword in normalized for keyword in keywords)
