from __future__ import annotations

from datetime import datetime
from typing import Sequence

from ..planning.models import DailyPlanEnvelope, PlanningCheckpoint

DISCORD_MESSAGE_LIMIT = 1900


def format_plan_today_message(envelope: DailyPlanEnvelope) -> str:
    plan = envelope.daily_plan
    lines: list[str] = []
    lines.append("오늘 브리핑")
    lines.append(plan.discord_briefing)
    lines.append("")
    lines.append("아침 브리핑")
    lines.extend(_non_empty_lines(plan.morning_briefing))

    if plan.prioritized_tasks:
        lines.append("")
        lines.append("우선순위 작업")
        for index, task in enumerate(plan.prioritized_tasks[:3], start=1):
            due_text = f" | due {task.due_date}" if task.due_date else ""
            lines.append(f"{index}. {task.title} [{task.priority_level}]{due_text}")

    if plan.time_block_briefings:
        lines.append("")
        lines.append("시간대별 브리핑")
        for briefing in plan.time_block_briefings[:3]:
            lines.append(f"- {_time_range(briefing.start, briefing.end)} {briefing.title}")
            lines.append(f"  {briefing.briefing}")

    if plan.checkpoints:
        lines.append("")
        lines.append("체크포인트")
        for checkpoint in plan.checkpoints[:3]:
            reminder_time = datetime.fromisoformat(checkpoint.remind_at).strftime("%H:%M")
            lines.append(f"- {reminder_time} {checkpoint.block_title}")

    return "\n".join(lines).strip()


def format_checkpoints_message(checkpoints: Sequence[PlanningCheckpoint], *, reference_time: datetime) -> str:
    if not checkpoints:
        return f"{reference_time.strftime('%H:%M')} 기준으로 예정된 체크포인트가 없습니다."

    lines = [f"{reference_time.strftime('%H:%M')} 기준 체크포인트"]
    for checkpoint in checkpoints:
        reminder_time = datetime.fromisoformat(checkpoint.remind_at).strftime("%H:%M")
        lines.append(f"- {reminder_time} {checkpoint.prompt}")
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
