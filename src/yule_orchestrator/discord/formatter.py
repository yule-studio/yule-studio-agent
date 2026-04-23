from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from ..planning.models import DailyPlanEnvelope, PlanningCheckpoint
from ..planning.snapshots import DailyPlanSnapshot

DISCORD_MESSAGE_LIMIT = 1900


def format_plan_today_message(
    envelope: DailyPlanEnvelope,
    mention_user_id: Optional[int] = None,
    snapshot: Optional[DailyPlanSnapshot] = None,
) -> str:
    plan = envelope.daily_plan
    lines: list[str] = []
    _append_mention(lines, mention_user_id)
    if snapshot is not None:
        if snapshot.is_stale:
            lines.append(
                f"마지막 동기화 기준 브리핑입니다. 생성 시각: {snapshot.generated_at.strftime('%Y-%m-%d %H:%M')}"
            )
        else:
            lines.append(f"스냅샷 기준 브리핑입니다. 생성 시각: {snapshot.generated_at.strftime('%Y-%m-%d %H:%M')}")
        lines.append("")
    lines.append("**오늘 브리핑**")
    lines.extend(_non_empty_lines(plan.discord_briefing))
    lines.append("")
    lines.append("**아침 브리핑**")
    lines.extend(_morning_summary_lines(plan.morning_briefing))

    if plan.prioritized_tasks:
        lines.append("")
        lines.append("**추천 작업**")
        for index, task in enumerate(plan.prioritized_tasks[:3], start=1):
            lines.append(f"{index}. {task.title}")
            detail_parts = [f"우선순위: {_priority_label(task.priority_level)}"]
            if task.due_date:
                detail_parts.append(f"기한: {_due_label(task.due_date)}")
            lines.append(f"   - {' | '.join(detail_parts)}")

    if plan.time_block_briefings:
        lines.append("")
        lines.append("**시간대 메모**")
        for briefing in plan.time_block_briefings[:3]:
            lines.append(f"- {_time_range(briefing.start, briefing.end)} {briefing.title}")
            lines.append(f"  {briefing.briefing}")

    if plan.checkpoints:
        lines.append("")
        lines.append("**체크포인트**")
        for checkpoint in plan.checkpoints[:3]:
            lines.append(f"- {checkpoint.prompt}")

    return "\n".join(lines).strip()


def format_missing_plan_snapshot_message(
    *,
    mention_user_id: Optional[int] = None,
) -> str:
    lines: list[str] = []
    _append_mention(lines, mention_user_id)
    lines.append("아직 오늘 daily-plan snapshot이 없습니다.")
    lines.append("아래 순서로 로컬 동기화를 먼저 실행한 뒤 다시 확인해 주세요.")
    lines.append("")
    lines.append("```bash")
    lines.append("yule calendar sync --json")
    lines.append("yule github issues --limit 30")
    lines.append("yule planning snapshot --json")
    lines.append("```")
    return "\n".join(lines)


def format_checkpoints_message(
    checkpoints: Sequence[PlanningCheckpoint],
    *,
    reference_time: datetime,
    mention_user_id: Optional[int] = None,
) -> str:
    if not checkpoints:
        lines: list[str] = []
        _append_mention(lines, mention_user_id)
        lines.append(f"{reference_time.strftime('%H:%M')} 기준으로 예정된 체크포인트가 없습니다.")
        return "\n".join(lines)

    lines: list[str] = []
    _append_mention(lines, mention_user_id)
    lines.append(f"{reference_time.strftime('%H:%M')} 기준 체크포인트")
    for checkpoint in checkpoints:
        lines.append(f"- {checkpoint.prompt}")
    return "\n".join(lines)


def split_discord_message(message: str, limit: int = DISCORD_MESSAGE_LIMIT) -> list[str]:
    if len(message) <= limit:
        return [message]

    chunks: list[str] = []
    current_lines: list[str] = []
    current_length = 0

    for line in message.splitlines():
        added_length = len(line) + (1 if current_lines else 0)
        if current_lines and current_length + added_length > limit:
            chunks.append("\n".join(current_lines))
            current_lines = [line]
            current_length = len(line)
            continue

        current_lines.append(line)
        current_length += added_length

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks


def _time_range(start_value: str, end_value: str) -> str:
    return f"{datetime.fromisoformat(start_value).strftime('%H:%M')}~{datetime.fromisoformat(end_value).strftime('%H:%M')}"


def _non_empty_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()] or [text]


def _morning_summary_lines(text: str) -> list[str]:
    lines: list[str] = []
    for line in _non_empty_lines(text):
        if line in {"추천 작업", "초반 흐름"}:
            break
        lines.append(line)
    return lines or _non_empty_lines(text)


def _priority_label(value: str) -> str:
    return {
        "high": "높음",
        "medium": "중간",
        "low": "낮음",
    }.get(value, value)


def _due_label(value: str) -> str:
    if "T" in value:
        return datetime.fromisoformat(value).strftime("%m-%d %H:%M")
    return value


def _append_mention(lines: list[str], mention_user_id: Optional[int]) -> None:
    if mention_user_id is None:
        return
    lines.append(f"<@{mention_user_id}>")
    lines.append("")
