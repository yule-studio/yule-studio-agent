from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Sequence

from ..integrations.calendar.models import build_fallback_item_uid
from .models import (
    DailyPlanEnvelope,
    DailyPlanSummary,
    PlanningBlockBriefing,
    PlanningCheckpoint,
    PlanningExecutionBlock,
    PlanningTaskCandidate,
    PlanningTimeBlock,
)


def render_daily_plan(envelope: DailyPlanEnvelope) -> str:
    plan = envelope.daily_plan
    lines: list[str] = []
    lines.append(f"Daily Plan - {plan.plan_date.isoformat()}")
    lines.append("")

    if plan.warnings:
        lines.append("Warnings")
        for warning in plan.warnings:
            lines.append(f"- {warning}")
        lines.append("")

    lines.append("Fixed Schedule")
    if not plan.fixed_schedule:
        lines.append("- no fixed events")
    else:
        for block in plan.fixed_schedule:
            lines.append(f"- {block.start} -> {block.end} | {block.title}")
    lines.append("")

    lines.append("Execution Blocks")
    if not plan.execution_blocks:
        lines.append("- no execution blocks parsed from event descriptions")
    else:
        for block in plan.execution_blocks:
            lines.append(f"- {block.start} -> {block.end} | {block.title} ({block.source_event_title})")
    lines.append("")

    lines.append("Prioritized Tasks")
    if not plan.prioritized_tasks:
        lines.append("- no recommended tasks")
    else:
        for index, task in enumerate(plan.prioritized_tasks[:5], start=1):
            due_label = f" | due {task.due_date}" if task.due_date else ""
            lines.append(
                f"{index}. [{task.priority_level}] {task.title} ({task.source_type}, {task.priority_score})"
                f"{due_label}"
            )
            if task.reasons:
                lines.append(f"   reasons: {', '.join(task.reasons)}")
    lines.append("")

    lines.append("Suggested Focus Blocks")
    if not plan.suggested_time_blocks:
        lines.append("- no focus blocks suggested")
    else:
        for block in plan.suggested_time_blocks:
            lines.append(f"- {block.start} -> {block.end} | {block.title}")
    lines.append("")

    lines.append("Morning Briefing")
    lines.append(f"source: {plan.morning_briefing_source}")
    lines.extend(plan.morning_briefing.splitlines() or [plan.morning_briefing])
    lines.append("")

    lines.append("Time Block Briefings")
    if not plan.time_block_briefings:
        lines.append("- no time block briefings")
    else:
        for briefing in plan.time_block_briefings:
            lines.append(f"- {briefing.start} -> {briefing.end} | {briefing.title}")
            lines.append(f"  {briefing.briefing}")
    lines.append("")

    lines.append("Checkpoints")
    if not plan.checkpoints:
        lines.append("- no checkpoints")
    else:
        for checkpoint in plan.checkpoints:
            lines.append(f"- {checkpoint.remind_at} | {checkpoint.prompt}")
    lines.append("")

    lines.append("Coding Agent Handoff")
    if not plan.coding_agent_handoff:
        lines.append("- no coding handoff candidates")
    else:
        for task in plan.coding_agent_handoff:
            lines.append(f"- {task.title} ({task.source_type})")
    lines.append("")

    lines.append("Discord Briefing")
    lines.append(f"source: {plan.discord_briefing_source}")
    lines.append(plan.discord_briefing)
    return "\n".join(lines).rstrip() + "\n"


def build_time_block_briefings(
    fixed_schedule: Sequence[PlanningTimeBlock],
    execution_blocks: Sequence[PlanningExecutionBlock],
    suggested_time_blocks: Sequence[PlanningTimeBlock],
    tasks: Sequence[PlanningTaskCandidate],
) -> list[PlanningBlockBriefing]:
    briefings: list[PlanningBlockBriefing] = []
    task_map = {task.task_id: task for task in tasks}
    covered_event_ids = {block.source_event_uid for block in execution_blocks}

    sorted_execution_blocks = sorted(execution_blocks, key=lambda block: block.start)
    for index, block in enumerate(sorted_execution_blocks):
        next_block = sorted_execution_blocks[index + 1] if index + 1 < len(sorted_execution_blocks) else None
        briefing_text = _build_execution_block_briefing(block, next_block)
        briefings.append(
            PlanningBlockBriefing(
                briefing_id=build_fallback_item_uid("planning-briefing", block.block_id),
                start=block.start,
                end=block.end,
                title=block.title,
                block_type="execution_block",
                source_ref=block.block_id,
                briefing=briefing_text,
            )
        )

    for block in fixed_schedule:
        if block.task_id in covered_event_ids:
            continue
        briefing_text = _build_fixed_event_briefing(block)
        briefings.append(
            PlanningBlockBriefing(
                briefing_id=build_fallback_item_uid("planning-briefing", block.block_type, block.title, block.start, block.end),
                start=block.start,
                end=block.end,
                title=block.title,
                block_type="fixed_event",
                source_ref=block.task_id,
                briefing=briefing_text,
            )
        )

    for block in suggested_time_blocks:
        task = task_map.get(block.task_id or "")
        briefing_text = _build_focus_block_briefing(block, task)
        briefings.append(
            PlanningBlockBriefing(
                briefing_id=build_fallback_item_uid("planning-briefing", block.block_type, block.title, block.start, block.end),
                start=block.start,
                end=block.end,
                title=block.title,
                block_type="focus_block",
                source_ref=block.task_id,
                briefing=briefing_text,
            )
        )

    briefings.sort(key=lambda briefing: briefing.start)
    return briefings


def render_morning_briefing(
    plan_date: date,
    summary: DailyPlanSummary,
    fixed_schedule: Sequence[PlanningTimeBlock],
    prioritized_tasks: Sequence[PlanningTaskCandidate],
    suggested_time_blocks: Sequence[PlanningTimeBlock],
    time_block_briefings: Sequence[PlanningBlockBriefing],
    coding_agent_handoff: Sequence[PlanningTaskCandidate],
    checkpoints: Sequence[PlanningCheckpoint],
) -> str:
    lines: list[str] = []
    lines.append(f"{plan_date.isoformat()} 아침 브리핑")
    lines.append(
        f"- 오늘은 고정 일정 {summary.fixed_event_count}건과 우선 작업 {summary.recommended_task_count}건을 기준으로 움직입니다."
    )

    first_fixed = fixed_schedule[0] if fixed_schedule else None
    first_focus = suggested_time_blocks[0] if suggested_time_blocks else None

    if first_fixed and first_focus:
        lines.append(
            f"- 하루 시작은 {_format_time_range(first_fixed.start, first_fixed.end)} '{first_fixed.title}'로 열고, "
            f"첫 집중 작업은 {_format_time_range(first_focus.start, first_focus.end)} '{first_focus.title}'로 잡는 편이 좋습니다."
        )
    elif first_fixed:
        lines.append(
            f"- 하루 시작은 {_format_time_range(first_fixed.start, first_fixed.end)} '{first_fixed.title}'입니다."
        )
    elif first_focus:
        lines.append(
            f"- 첫 집중 작업은 {_format_time_range(first_focus.start, first_focus.end)} '{first_focus.title}'입니다."
        )

    if checkpoints:
        first_checkpoint = datetime.fromisoformat(checkpoints[0].remind_at).strftime("%H:%M")
        if len(checkpoints) > 1:
            next_checkpoint = datetime.fromisoformat(checkpoints[1].remind_at).strftime("%H:%M")
            lines.append(
                f"- 중간 점검은 총 {len(checkpoints)}번이며, 첫 알림은 {first_checkpoint}, 다음 알림은 {next_checkpoint}입니다."
            )
        else:
            lines.append(f"- 중간 점검은 총 1번이며, 알림은 {first_checkpoint}에 들어갑니다.")

    if coding_agent_handoff:
        lines.append(
            f"- 개발 후보 작업은 {len(coding_agent_handoff)}건이며, 가장 먼저 볼 항목은 '{coding_agent_handoff[0].title}'입니다."
        )

    if prioritized_tasks:
        lines.append("")
        lines.append("추천 작업")
        focus_block_map = {
            block.task_id: block for block in suggested_time_blocks if block.task_id
        }
        for index, task in enumerate(prioritized_tasks[:3], start=1):
            lines.append(f"{index}. {task.title}")
            detail_parts: list[str] = []
            reason_text = _summarize_reasons(task.reasons)
            if reason_text:
                detail_parts.append(f"이유: {reason_text}")
            focus_block = focus_block_map.get(task.task_id)
            if focus_block is not None:
                detail_parts.append(
                    f"추천 시간: {_format_time_range(focus_block.start, focus_block.end)}"
                )
            elif task.due_date:
                detail_parts.append(f"기한: {_summarize_due_label(task.due_date)}")
            if detail_parts:
                lines.append(f"   - {' | '.join(detail_parts)}")

    if time_block_briefings:
        lines.append("")
        lines.append("초반 흐름")
        for briefing in time_block_briefings[:3]:
            lines.append(
                f"- {_format_time_range(briefing.start, briefing.end)} {briefing.title}: {briefing.briefing}"
            )

    return "\n".join(lines)


def render_discord_briefing(
    summary: DailyPlanSummary,
    fixed_schedule: Sequence[PlanningTimeBlock],
    tasks: Sequence[PlanningTaskCandidate],
    suggested_time_blocks: Sequence[PlanningTimeBlock],
    coding_agent_handoff: Sequence[PlanningTaskCandidate],
    checkpoints: Sequence[PlanningCheckpoint],
) -> str:
    lines = [f"오늘은 고정 일정 {summary.fixed_event_count}건과 우선 작업 {summary.recommended_task_count}건이 있습니다."]

    first_fixed = fixed_schedule[0] if fixed_schedule else None
    first_focus = suggested_time_blocks[0] if suggested_time_blocks else None

    if first_fixed and first_focus:
        lines.append(
            f"먼저 {_format_time_range(first_fixed.start, first_fixed.end)} '{first_fixed.title}'로 시작하고, "
            f"이후 {_format_time_range(first_focus.start, first_focus.end)} '{first_focus.title}'에 집중하는 흐름을 추천합니다."
        )
    elif first_focus:
        lines.append(
            f"첫 집중 작업은 {_format_time_range(first_focus.start, first_focus.end)} '{first_focus.title}'입니다."
        )
    elif tasks:
        lines.append(f"가장 먼저 볼 작업은 '{tasks[0].title}'입니다.")

    if checkpoints:
        first_checkpoint = datetime.fromisoformat(checkpoints[0].remind_at).strftime("%H:%M")
        lines.append(f"중간 점검은 {len(checkpoints)}번이고, 첫 알림은 {first_checkpoint}입니다.")

    if coding_agent_handoff:
        lines.append(f"개발 후보 작업은 {len(coding_agent_handoff)}건입니다.")

    return "\n".join(lines)


def _build_execution_block_briefing(
    block: PlanningExecutionBlock,
    next_block: Optional[PlanningExecutionBlock],
) -> str:
    action_hint = _action_hint(block.title, block.description)
    parts = [action_hint]
    if next_block is not None and next_block.source_event_uid == block.source_event_uid:
        next_start = datetime.fromisoformat(next_block.start).strftime("%H:%M")
        parts.append(
            f"{next_start}부터 '{next_block.title}'가 이어지니, 끝나기 전까지 넘길 기준이나 메모를 짧게 남겨두면 흐름이 덜 끊깁니다."
        )
    else:
        parts.append("이 블록이 끝날 때는 마무리 상태와 다음 행동 한 가지를 함께 정리해 두는 편이 좋습니다.")
    return " ".join(parts)


def _build_fixed_event_briefing(block: PlanningTimeBlock) -> str:
    haystack = block.title.lower()
    if any(keyword in haystack for keyword in ["할 일", "해야 할", "업무 정리", "목록 정리"]):
        return (
            "이 구간은 오늘 처리할 일과 우선순위를 정리하고, 다음 집중 작업으로 바로 넘어갈 준비를 하는 시간으로 쓰면 좋습니다."
        )
    return (
        "새 작업을 벌리기보다 일정 자체에 집중하고, 끝나기 직전에 다음 블록으로 넘어갈 준비만 정리하는 편이 안정적입니다."
    )


def _build_focus_block_briefing(
    block: PlanningTimeBlock,
    task: Optional[PlanningTaskCandidate],
) -> str:
    if task is None:
        return (
            "시작 전에 이번 블록의 완료 기준을 한 줄로 적고, 끝날 때는 다음 행동 하나만 남겨 주세요."
        )

    reason_text = _summarize_reasons(task.reasons)
    due_text = _summarize_due(task.due_date)
    action_hint = _action_hint(task.title, task.description)
    parts: list[str] = []
    if reason_text:
        parts.append(f"이 작업은 {reason_text} 때문에 우선순위가 높게 잡혔습니다.")
    if due_text:
        parts.append(due_text)
    parts.append(action_hint)
    return " ".join(parts)


def _format_time_range(start_value: str, end_value: str) -> str:
    start_label = datetime.fromisoformat(start_value).strftime("%H:%M")
    end_label = datetime.fromisoformat(end_value).strftime("%H:%M")
    return f"{start_label}~{end_label}"


def _summarize_reasons(reasons: Sequence[str]) -> str:
    label_map = {
        "calendar todo": "캘린더에 잡힌 할 일",
        "coding candidate": "개발 후보 작업",
        "due today": "오늘 처리 우선",
        "high priority hint": "높은 우선순위 힌트",
        "medium priority hint": "중간 이상 우선순위",
        "open GitHub issue": "열려 있는 GitHub 이슈",
        "organization repository": "조직 저장소 작업",
        "overdue": "기한이 지난 상태",
        "personal repository": "개인 저장소 작업",
        "reminder item": "리마인더 항목",
        "review or documentation keyword": "정리/문서 성격",
        "review overdue": "밀린 복습 항목",
        "review today": "오늘 복습 필요",
        "review tomorrow": "내일 전 준비 필요",
        "urgent keyword": "긴급 키워드 포함",
    }
    labels: list[str] = []
    category_labels: list[str] = []
    for reason in reasons:
        label = label_map.get(reason)
        if label is None and reason.startswith("naver category: "):
            label = reason.replace("naver category: ", "", 1)
            if label and label not in category_labels:
                category_labels.append(label)
            continue
        if label and label not in labels:
            labels.append(label)

    labels = category_labels + [label for label in labels if label not in category_labels]
    if not labels:
        return ""
    if len(labels) > 2 and "캘린더에 잡힌 할 일" in labels:
        labels.remove("캘린더에 잡힌 할 일")
    return ", ".join(labels[:2])


def _summarize_due(due_date: Optional[str]) -> str:
    if not due_date:
        return ""
    if "T" in due_date:
        parsed = datetime.fromisoformat(due_date)
        return f"시간 기준 마감은 {parsed.strftime('%m-%d %H:%M')}입니다."
    return ""


def _summarize_due_label(due_date: str) -> str:
    if "T" in due_date:
        parsed = datetime.fromisoformat(due_date)
        return parsed.strftime("%m-%d %H:%M")
    return due_date


def _action_hint(title: str, description: str) -> str:
    haystack = f"{title}\n{description}".lower()
    if any(keyword in haystack for keyword in ["정리", "분류", "목록"]):
        return "먼저 흩어진 항목을 한 번에 모으고, 끝날 때는 다음 단계로 넘길 것만 짧게 남겨두는 흐름이 좋습니다."
    if any(keyword in haystack for keyword in ["문서", "분석", "설계", "포맷", "구조"]):
        return "먼저 기준과 뼈대를 고정하고, 남는 시간에 예시나 세부 항목을 채우는 순서가 안정적입니다."
    if any(keyword in haystack for keyword in ["구현", "개발", "코딩", "bug", "fix", "api", "agent", "server", "test"]):
        return "먼저 완료 기준을 좁게 잡고, 가장 작은 결과물 하나를 끝내는 방식으로 들어가면 흐름이 덜 흔들립니다."
    if any(keyword in haystack for keyword in ["복습", "정독", "공부", "review"]):
        return "처음 10분은 범위와 목표를 다시 맞추고, 이후에는 한 주제를 끝까지 보는 편이 기억에 더 잘 남습니다."
    return "시작 전에 이번 블록의 완료 기준을 한 줄로 정하고 들어가면 시간 분배가 훨씬 선명해집니다."
