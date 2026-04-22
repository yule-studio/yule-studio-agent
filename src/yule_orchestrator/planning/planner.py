from __future__ import annotations

from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import re
from typing import Optional, Sequence

from ..integrations.calendar import CalendarIntegrationError, list_naver_calendar_items
from ..integrations.calendar.models import CalendarEvent, CalendarTodo, build_fallback_item_uid
from ..integrations.github.issues import GitHubIssue, GitHubIssueError, list_open_issues
from .models import (
    DailyPlan,
    DailyPlanEnvelope,
    DailyPlanSummary,
    PlanningBlockBriefing,
    PlanningCheckpoint,
    PlanningExecutionBlock,
    PlanningInputs,
    PlanningSourceStatus,
    PlanningTaskCandidate,
    PlanningTimeBlock,
    ReminderItem,
)
from .ollama import generate_human_briefing

PLANNING_DAY_START = time(hour=6, minute=0)
PLANNING_DAY_END = time(hour=23, minute=0)
MINIMUM_FOCUS_BLOCK_MINUTES = 30
MAXIMUM_FOCUS_BLOCK_MINUTES = 120
DEFAULT_CHECKPOINT_LEAD_MINUTES = 5
DESCRIPTION_BLOCK_PATTERN = re.compile(
    r"^\s*(?:[-*]\s*)?(?P<start>.+?)\s*(?:~|〜|–|-)\s*(?P<end>.+?)\s*:\s*(?P<title>.+?)\s*$"
)
TIME_TOKEN_PATTERN = re.compile(
    r"^(?:(오전|오후))?(?P<hour>\d{1,2})(?:(?:[:시])(?P<minute>\d{1,2}))?시?$"
)


def load_reminder_items(path_text: Optional[str]) -> Sequence[ReminderItem]:
    if not path_text:
        return []

    path = Path(path_text)
    if not path.exists():
        raise ValueError(f"Reminder file was not found: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Reminder file must contain valid JSON: {path}") from exc

    if isinstance(payload, dict):
        items = payload.get("items", [])
    else:
        items = payload

    if not isinstance(items, list):
        raise ValueError("Reminder file must contain a JSON array or an object with an `items` array.")

    reminders: list[ReminderItem] = []
    for item in items:
        if isinstance(item, dict):
            reminders.append(ReminderItem.from_dict(item))
    return reminders


def collect_planning_inputs(
    plan_date: date,
    github_limit: int = 20,
    include_calendar: bool = True,
    include_github: bool = True,
    reminders: Optional[Sequence[ReminderItem]] = None,
) -> PlanningInputs:
    timezone = datetime.now().astimezone().tzname() or "local"
    warnings: list[str] = []
    source_statuses: list[PlanningSourceStatus] = []
    calendar_events: Sequence[CalendarEvent] = []
    calendar_todos: Sequence[CalendarTodo] = []
    github_issues: Sequence[GitHubIssue] = []
    reminder_items = list(reminders or [])

    if include_calendar:
        try:
            result = list_naver_calendar_items(plan_date, plan_date)
            calendar_events = result.events
            calendar_todos = result.todos
            source_statuses.append(
                PlanningSourceStatus(
                    source_id="calendar",
                    source_type="calendar",
                    ok=True,
                    item_count=len(calendar_events) + len(calendar_todos),
                )
            )
        except CalendarIntegrationError as exc:
            warning = exc.details.message
            warnings.append(f"calendar: {warning}")
            source_statuses.append(
                PlanningSourceStatus(
                    source_id="calendar",
                    source_type="calendar",
                    ok=False,
                    item_count=0,
                    warning=warning,
                )
            )

    if include_github:
        try:
            github_issues = list_open_issues(limit=github_limit)
            source_statuses.append(
                PlanningSourceStatus(
                    source_id="github-issues",
                    source_type="github",
                    ok=True,
                    item_count=len(github_issues),
                )
            )
        except GitHubIssueError as exc:
            warning = str(exc)
            warnings.append(f"github: {warning}")
            source_statuses.append(
                PlanningSourceStatus(
                    source_id="github-issues",
                    source_type="github",
                    ok=False,
                    item_count=0,
                    warning=warning,
                )
            )

    source_statuses.append(
        PlanningSourceStatus(
            source_id="reminders",
            source_type="reminder",
            ok=True,
            item_count=len(reminder_items),
        )
    )

    return PlanningInputs(
        plan_date=plan_date,
        timezone=timezone,
        source_statuses=source_statuses,
        warnings=warnings,
        calendar_events=calendar_events,
        calendar_todos=calendar_todos,
        github_issues=github_issues,
        reminders=reminder_items,
    )


def build_daily_plan(
    inputs: PlanningInputs,
    reminder_lead_minutes: int = DEFAULT_CHECKPOINT_LEAD_MINUTES,
    use_ollama: bool = False,
    ollama_model: str = "gemma3:latest",
    ollama_endpoint: str = "http://localhost:11434",
) -> DailyPlanEnvelope:
    fixed_schedule = _build_fixed_schedule(inputs.plan_date, inputs.calendar_events)
    execution_blocks = _build_execution_blocks(inputs.calendar_events)
    tasks = _build_task_candidates(inputs)
    suggested_blocks, available_focus_minutes = _build_focus_blocks(
        inputs.plan_date,
        fixed_schedule,
        tasks,
    )
    checkpoints = _build_checkpoints(execution_blocks, lead_minutes=reminder_lead_minutes)
    coding_agent_handoff = [task for task in tasks if task.coding_candidate][:3]
    warnings = list(inputs.warnings)

    summary = DailyPlanSummary(
        fixed_event_count=len([event for event in inputs.calendar_events if not event.all_day]),
        all_day_event_count=len([event for event in inputs.calendar_events if event.all_day]),
        todo_count=len(inputs.calendar_todos),
        github_issue_count=len(inputs.github_issues),
        reminder_count=len(inputs.reminders),
        recommended_task_count=len(tasks),
        available_focus_minutes=available_focus_minutes,
    )

    discord_briefing = _render_discord_briefing(
        summary,
        tasks,
        coding_agent_handoff,
        checkpoints,
    )
    time_block_briefings = _build_time_block_briefings(
        fixed_schedule=fixed_schedule,
        execution_blocks=execution_blocks,
        suggested_time_blocks=suggested_blocks,
        tasks=tasks,
    )
    morning_briefing = _render_morning_briefing(
        plan_date=inputs.plan_date,
        summary=summary,
        fixed_schedule=fixed_schedule,
        prioritized_tasks=tasks,
        suggested_time_blocks=suggested_blocks,
        time_block_briefings=time_block_briefings,
        coding_agent_handoff=coding_agent_handoff,
        checkpoints=checkpoints,
    )
    briefing_source = "rules"

    if use_ollama:
        try:
            morning_briefing = generate_human_briefing(
                plan_date=inputs.plan_date.isoformat(),
                summary_line=discord_briefing,
                fixed_schedule=fixed_schedule,
                prioritized_tasks=tasks,
                time_block_briefings=time_block_briefings,
                checkpoints=checkpoints,
                model=ollama_model,
                endpoint=ollama_endpoint,
            )
            briefing_source = "ollama"
        except ValueError as exc:
            warnings.append(f"ollama: {exc}")

    daily_plan = DailyPlan(
        plan_date=inputs.plan_date,
        timezone=inputs.timezone,
        source_statuses=inputs.source_statuses,
        warnings=warnings,
        summary=summary,
        fixed_schedule=fixed_schedule,
        execution_blocks=execution_blocks,
        prioritized_tasks=tasks,
        suggested_time_blocks=suggested_blocks,
        morning_briefing=morning_briefing,
        time_block_briefings=time_block_briefings,
        checkpoints=checkpoints,
        coding_agent_handoff=coding_agent_handoff,
        discord_briefing=discord_briefing,
        briefing_source=briefing_source,
    )
    return DailyPlanEnvelope(inputs=inputs, daily_plan=daily_plan)


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
    lines.append(f"source: {plan.briefing_source}")
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
    lines.append(f"source: {plan.briefing_source}")
    lines.append(plan.discord_briefing)
    return "\n".join(lines).rstrip() + "\n"


def _build_fixed_schedule(plan_date: date, events: Sequence[CalendarEvent]) -> list[PlanningTimeBlock]:
    blocks: list[PlanningTimeBlock] = []
    for event in events:
        if event.all_day:
            continue
        blocks.append(
            PlanningTimeBlock(
                start=event.start,
                end=event.end,
                block_type="fixed_event",
                title=event.title,
                task_id=event.item_uid,
                locked=True,
            )
        )
    blocks.sort(key=lambda block: block.start)
    return blocks


def _build_task_candidates(inputs: PlanningInputs) -> list[PlanningTaskCandidate]:
    tasks: list[PlanningTaskCandidate] = []

    for todo in inputs.calendar_todos:
        if todo.completed:
            continue
        tasks.append(_build_todo_candidate(inputs.plan_date, todo))

    for issue in inputs.github_issues:
        tasks.append(_build_issue_candidate(issue))

    for reminder in inputs.reminders:
        tasks.append(_build_reminder_candidate(inputs.plan_date, reminder))

    tasks.sort(key=lambda task: (-task.priority_score, task.due_date or "9999-12-31", task.title.lower()))
    return tasks


def _build_execution_blocks(events: Sequence[CalendarEvent]) -> list[PlanningExecutionBlock]:
    blocks: list[PlanningExecutionBlock] = []
    for event in events:
        if event.all_day or not event.description.strip():
            continue

        try:
            event_start = datetime.fromisoformat(event.start)
            event_end = datetime.fromisoformat(event.end)
        except ValueError:
            continue

        parsed_blocks = _parse_execution_blocks_from_description(
            event=event,
            event_start=event_start,
            event_end=event_end,
        )
        blocks.extend(parsed_blocks)

    blocks.sort(key=lambda block: block.start)
    return blocks


def _build_todo_candidate(plan_date: date, todo: CalendarTodo) -> PlanningTaskCandidate:
    score = 40
    reasons = ["calendar todo"]
    due_date = _date_only(todo.due or todo.start)

    if due_date is not None:
        offset = (due_date - plan_date).days
        if offset < 0:
            score += 50
            reasons.append("overdue")
        elif offset == 0:
            score += 35
            reasons.append("due today")
        elif offset == 1:
            score += 15
            reasons.append("due tomorrow")

    keyword_score, keyword_reasons = _keyword_boost(todo.title, todo.description)
    score += keyword_score
    reasons.extend(keyword_reasons)

    return PlanningTaskCandidate(
        task_id=f"todo:{todo.item_uid}",
        source_type="calendar_todo",
        title=todo.title,
        description=todo.description,
        due_date=todo.due or todo.start,
        priority_score=score,
        priority_level=_priority_level(score),
        estimated_minutes=60,
        reasons=reasons,
        coding_candidate=_looks_like_coding_work(todo.title, todo.description),
    )


def _build_issue_candidate(issue: GitHubIssue) -> PlanningTaskCandidate:
    score = 35
    reasons = ["open GitHub issue", "coding candidate"]

    if issue.scope == "personal":
        score += 10
        reasons.append("personal repository")
    elif issue.scope.startswith("org:"):
        score += 5
        reasons.append("organization repository")

    keyword_score, keyword_reasons = _keyword_boost(issue.title, "")
    score += keyword_score
    reasons.extend(keyword_reasons)

    return PlanningTaskCandidate(
        task_id=f"issue:{issue.repository}#{issue.number}",
        source_type="github_issue",
        title=issue.title,
        description=issue.url,
        due_date=None,
        priority_score=score,
        priority_level=_priority_level(score),
        estimated_minutes=90,
        reasons=reasons,
        coding_candidate=True,
    )


def _build_reminder_candidate(plan_date: date, reminder: ReminderItem) -> PlanningTaskCandidate:
    score = 45
    reasons = ["reminder item"]
    due_date = _date_only(reminder.due_date)

    if due_date is not None:
        offset = (due_date - plan_date).days
        if offset < 0:
            score += 40
            reasons.append("review overdue")
        elif offset == 0:
            score += 25
            reasons.append("review today")
        elif offset == 1:
            score += 10
            reasons.append("review tomorrow")

    if reminder.priority_hint:
        hint = reminder.priority_hint.strip().lower()
        if hint in {"high", "urgent", "critical"}:
            score += 20
            reasons.append("high priority hint")
        elif hint == "medium":
            score += 8
            reasons.append("medium priority hint")

    keyword_score, keyword_reasons = _keyword_boost(reminder.title, reminder.description)
    score += keyword_score
    reasons.extend(keyword_reasons)

    return PlanningTaskCandidate(
        task_id=f"reminder:{reminder.item_id}",
        source_type="review_reminder",
        title=reminder.title,
        description=reminder.description,
        due_date=reminder.due_date,
        priority_score=score,
        priority_level=_priority_level(score),
        estimated_minutes=max(15, reminder.estimated_minutes),
        reasons=reasons,
        coding_candidate=_looks_like_coding_work(reminder.title, reminder.description, reminder.tags),
    )


def _build_focus_blocks(
    plan_date: date,
    fixed_schedule: Sequence[PlanningTimeBlock],
    tasks: Sequence[PlanningTaskCandidate],
) -> tuple[list[PlanningTimeBlock], int]:
    windows = _available_windows(plan_date, fixed_schedule)
    focus_blocks: list[PlanningTimeBlock] = []
    available_focus_minutes = sum(int((end - start).total_seconds() // 60) for start, end in windows)
    if not windows:
        return focus_blocks, available_focus_minutes

    working_windows = list(windows)
    for task in tasks[:6]:
        assigned = _assign_task_block(task, working_windows)
        if assigned is not None:
            focus_blocks.append(assigned)

    return focus_blocks, available_focus_minutes


def _build_time_block_briefings(
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


def _available_windows(
    plan_date: date,
    fixed_schedule: Sequence[PlanningTimeBlock],
) -> list[tuple[datetime, datetime]]:
    timezone = datetime.now().astimezone().tzinfo
    day_start = datetime.combine(plan_date, PLANNING_DAY_START, tzinfo=timezone)
    day_end = datetime.combine(plan_date, PLANNING_DAY_END, tzinfo=timezone)
    cursor = day_start
    windows: list[tuple[datetime, datetime]] = []

    timed_blocks = []
    for block in fixed_schedule:
        try:
            block_start = datetime.fromisoformat(block.start)
            block_end = datetime.fromisoformat(block.end)
        except ValueError:
            continue
        timed_blocks.append((block_start, block_end))

    timed_blocks.sort(key=lambda item: item[0])
    for block_start, block_end in timed_blocks:
        if block_end <= day_start or block_start >= day_end:
            continue
        clipped_start = max(block_start, day_start)
        clipped_end = min(block_end, day_end)
        if clipped_start > cursor and int((clipped_start - cursor).total_seconds() // 60) >= MINIMUM_FOCUS_BLOCK_MINUTES:
            windows.append((cursor, clipped_start))
        if clipped_end > cursor:
            cursor = clipped_end

    if day_end > cursor and int((day_end - cursor).total_seconds() // 60) >= MINIMUM_FOCUS_BLOCK_MINUTES:
        windows.append((cursor, day_end))

    return windows


def _assign_task_block(
    task: PlanningTaskCandidate,
    windows: list[tuple[datetime, datetime]],
) -> Optional[PlanningTimeBlock]:
    for index, (window_start, window_end) in enumerate(windows):
        duration_minutes = int((window_end - window_start).total_seconds() // 60)
        if duration_minutes < MINIMUM_FOCUS_BLOCK_MINUTES:
            continue

        block_minutes = min(duration_minutes, max(MINIMUM_FOCUS_BLOCK_MINUTES, task.estimated_minutes), MAXIMUM_FOCUS_BLOCK_MINUTES)
        block_end = window_start + timedelta(minutes=block_minutes)

        windows[index] = (block_end, window_end)
        return PlanningTimeBlock(
            start=window_start.isoformat(),
            end=block_end.isoformat(),
            block_type="focus",
            title=task.title,
            task_id=task.task_id,
            locked=False,
        )

    return None


def _build_execution_block_briefing(
    block: PlanningExecutionBlock,
    next_block: Optional[PlanningExecutionBlock],
) -> str:
    time_range = _format_time_range(block.start, block.end)
    action_hint = _action_hint(block.title, block.description)
    parts = [f"{time_range}는 '{block.title}'에 집중하는 구간입니다.", action_hint]
    if next_block is not None and next_block.source_event_uid == block.source_event_uid:
        next_start = datetime.fromisoformat(next_block.start).strftime("%H:%M")
        parts.append(
            f"{next_start}부터 '{next_block.title}'가 이어지니, 끝나기 전까지 넘길 기준이나 메모를 짧게 남겨두는 편이 좋습니다."
        )
    else:
        parts.append(f"이 블록이 끝날 때는 '{block.source_event_title}' 일정 기준으로 마무리 상태를 한 번 점검해 주세요.")
    return " ".join(parts)


def _build_fixed_event_briefing(block: PlanningTimeBlock) -> str:
    time_range = _format_time_range(block.start, block.end)
    return (
        f"{time_range}는 고정 일정 '{block.title}' 시간입니다. "
        "이 구간은 새 작업을 벌리기보다 참석이나 진행 자체에 집중하고, 종료 직전에 다음 블록으로 넘어갈 준비만 정리하는 편이 안정적입니다."
    )


def _build_focus_block_briefing(
    block: PlanningTimeBlock,
    task: Optional[PlanningTaskCandidate],
) -> str:
    time_range = _format_time_range(block.start, block.end)
    if task is None:
        return (
            f"{time_range}는 '{block.title}'에 쓰는 추천 집중 블록입니다. "
            "시작 전에 이번 블록의 완료 기준을 한 줄로 적고, 끝날 때는 다음 행동 하나만 남겨 주세요."
        )

    reason_text = _summarize_reasons(task.reasons)
    due_text = _summarize_due(task.due_date)
    action_hint = _action_hint(task.title, task.description)
    parts = [f"{time_range}는 '{task.title}'에 쓰는 추천 집중 블록입니다."]
    if reason_text:
        parts.append(f"이 작업은 {reason_text} 우선순위가 높게 잡혔습니다.")
    if due_text:
        parts.append(due_text)
    parts.append(action_hint)
    return " ".join(parts)


def _render_morning_briefing(
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
    lines.append(
        f"{plan_date.isoformat()} 아침 브리핑입니다. 오늘은 고정 일정 {summary.fixed_event_count}건과 우선 작업 {summary.recommended_task_count}건을 기준으로 움직이는 날입니다."
    )

    if fixed_schedule:
        first_fixed = fixed_schedule[0]
        lines.append(
            f"첫 고정 일정은 {_format_time_range(first_fixed.start, first_fixed.end)} '{first_fixed.title}'입니다."
        )

    if prioritized_tasks:
        lines.append("추천 우선순위는 아래 순서입니다.")
        focus_block_map = {
            block.task_id: block for block in suggested_time_blocks if block.task_id
        }
        for index, task in enumerate(prioritized_tasks[:3], start=1):
            sentence = f"{index}. {task.title}"
            reason_text = _summarize_reasons(task.reasons)
            if reason_text:
                sentence += f" - {reason_text}"
            focus_block = focus_block_map.get(task.task_id)
            if focus_block is not None:
                sentence += f" 추천 시간은 {_format_time_range(focus_block.start, focus_block.end)}입니다."
            elif task.due_date:
                sentence += f" {task.due_date} 기준으로 오늘 안에 방향을 잡아두는 편이 좋습니다."
            lines.append(sentence)

    if time_block_briefings:
        first_briefing = time_block_briefings[0]
        lines.append(
            f"시간대별로는 {_format_time_range(first_briefing.start, first_briefing.end)} '{first_briefing.title}'부터 따라가면 흐름이 자연스럽습니다."
        )

    if checkpoints:
        first_checkpoint = checkpoints[0]
        checkpoint_time = datetime.fromisoformat(first_checkpoint.remind_at).strftime("%H:%M")
        lines.append(
            f"중간 체크는 총 {len(checkpoints)}번 들어가고, 첫 체크는 {checkpoint_time}에 예정되어 있습니다."
        )

    if coding_agent_handoff:
        lines.append(
            f"Coding Agent로 넘길 후보는 '{coding_agent_handoff[0].title}' 포함 {len(coding_agent_handoff)}건입니다."
        )

    return "\n".join(lines)


def _render_discord_briefing(
    summary: DailyPlanSummary,
    tasks: Sequence[PlanningTaskCandidate],
    coding_agent_handoff: Sequence[PlanningTaskCandidate],
    checkpoints: Sequence[PlanningCheckpoint],
) -> str:
    parts = [f"오늘은 고정 일정 {summary.fixed_event_count}건, 우선 작업 {summary.recommended_task_count}건이 있습니다."]
    if tasks:
        parts.append(f"먼저는 '{tasks[0].title}'부터 잡는 흐름을 추천합니다.")
    if coding_agent_handoff:
        parts.append(f"Coding Agent 후보는 '{coding_agent_handoff[0].title}' 포함 {len(coding_agent_handoff)}건입니다.")
    if checkpoints:
        parts.append(f"체크포인트는 {len(checkpoints)}건입니다.")
    return " ".join(parts)


def _format_time_range(start_value: str, end_value: str) -> str:
    start_label = datetime.fromisoformat(start_value).strftime("%H:%M")
    end_label = datetime.fromisoformat(end_value).strftime("%H:%M")
    return f"{start_label}~{end_label}"


def _summarize_reasons(reasons: Sequence[str]) -> str:
    label_map = {
        "calendar todo": "캘린더 할 일이라",
        "coding candidate": "개발 후보 작업이라",
        "due today": "오늘 처리 우선이라",
        "high priority hint": "우선순위 힌트가 높아",
        "medium priority hint": "중요도가 중간 이상이라",
        "open GitHub issue": "열려 있는 GitHub 이슈라",
        "organization repository": "조직 저장소 작업이라",
        "overdue": "기한이 이미 지나",
        "personal repository": "개인 저장소 작업이라",
        "reminder item": "리마인더로 잡혀 있어",
        "review or documentation keyword": "정리나 문서화 성격이 있어",
        "review overdue": "밀린 복습 항목이라",
        "review today": "오늘 복습해야 해서",
        "review tomorrow": "내일 전 준비가 필요해서",
        "urgent keyword": "긴급 키워드가 있어",
    }
    labels: list[str] = []
    for reason in reasons:
        label = label_map.get(reason)
        if label and label not in labels:
            labels.append(label)
        if len(labels) == 2:
            break

    if not labels:
        return ""
    if len(labels) == 1:
        return labels[0]
    return f"{labels[0]} {labels[1]}"


def _summarize_due(due_date: Optional[str]) -> str:
    if not due_date:
        return ""
    if "T" in due_date:
        parsed = datetime.fromisoformat(due_date)
        return f"마감 기준은 {parsed.strftime('%m-%d %H:%M')}입니다."
    return f"마감 기준은 {due_date}입니다."


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


def _date_only(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    if "T" in value:
        return datetime.fromisoformat(value).date()
    return date.fromisoformat(value)


def _priority_level(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _keyword_boost(title: str, description: str) -> tuple[int, list[str]]:
    haystack = f"{title}\n{description}".lower()
    score = 0
    reasons: list[str] = []

    high_keywords = ["오늘", "urgent", "긴급", "마감", "시험", "신청", "fix", "bug", "hotfix", "error"]
    medium_keywords = ["정리", "문서", "분석", "review", "복습"]

    if any(keyword in haystack for keyword in high_keywords):
        score += 20
        reasons.append("urgent keyword")
    if any(keyword in haystack for keyword in medium_keywords):
        score += 8
        reasons.append("review or documentation keyword")

    return score, reasons


def _looks_like_coding_work(title: str, description: str, tags: Optional[Sequence[str]] = None) -> bool:
    combined = f"{title}\n{description}".lower()
    tag_values = [tag.lower() for tag in (tags or [])]
    coding_keywords = [
        "api",
        "backend",
        "bug",
        "code",
        "coding",
        "dev",
        "docs",
        "issue",
        "pr",
        "refactor",
        "repository",
        "server",
        "test",
        "agent",
    ]
    if any(keyword in combined for keyword in coding_keywords):
        return True
    return any(tag in {"coding", "dev", "backend", "review"} for tag in tag_values)


def _parse_execution_blocks_from_description(
    event: CalendarEvent,
    event_start: datetime,
    event_end: datetime,
) -> list[PlanningExecutionBlock]:
    blocks: list[PlanningExecutionBlock] = []
    lines = event.description.splitlines()
    for line in lines:
        match = DESCRIPTION_BLOCK_PATTERN.match(line.strip())
        if match is None:
            continue

        start_text = match.group("start").strip()
        end_text = match.group("end").strip()
        title = match.group("title").strip()

        block_start = _resolve_description_time(
            token=start_text,
            event_start=event_start,
            event_end=event_end,
            reference=None,
        )
        if block_start is None:
            continue

        block_end = _resolve_description_time(
            token=end_text,
            event_start=event_start,
            event_end=event_end,
            reference=block_start,
        )
        if block_end is None or block_end <= block_start:
            continue

        block_id = build_fallback_item_uid(
            "planning-block",
            event.item_uid,
            block_start.isoformat(),
            block_end.isoformat(),
            title,
        )
        blocks.append(
            PlanningExecutionBlock(
                block_id=block_id,
                source_event_uid=event.item_uid,
                source_event_title=event.title,
                start=block_start.isoformat(),
                end=block_end.isoformat(),
                title=title,
                description=line.strip(),
            )
        )

    blocks.sort(key=lambda block: block.start)
    return blocks


def _resolve_description_time(
    token: str,
    event_start: datetime,
    event_end: datetime,
    reference: Optional[datetime],
) -> Optional[datetime]:
    match = TIME_TOKEN_PATTERN.match(token.strip().replace(" ", "").replace("분", ""))
    if match is None:
        return None

    meridian = match.group(1)
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or "0")

    if meridian == "오전":
        hour = 0 if hour == 12 else hour
        candidate_hours = [hour]
    elif meridian == "오후":
        hour = hour if hour == 12 else hour + 12
        candidate_hours = [hour]
    else:
        candidate_hours = [hour]
        if hour < 12:
            candidate_hours.append(hour + 12)
        candidate_hours.append(hour + 24)

    candidates: list[datetime] = []
    for candidate_hour in candidate_hours:
        day_offset, resolved_hour = divmod(candidate_hour, 24)
        candidate_date = event_start.date() + timedelta(days=day_offset)
        candidates.append(
            datetime.combine(
                candidate_date,
                time(hour=resolved_hour, minute=minute),
                tzinfo=event_start.tzinfo,
            )
        )

    if reference is None:
        window_candidates = [
            candidate
            for candidate in candidates
            if event_start - timedelta(minutes=5) <= candidate <= event_end + timedelta(minutes=5)
        ]
        if window_candidates:
            return min(window_candidates, key=lambda candidate: abs((candidate - event_start).total_seconds()))
        return min(candidates, key=lambda candidate: abs((candidate - event_start).total_seconds()))

    after_reference = [candidate for candidate in candidates if candidate > reference]
    window_candidates = [
        candidate
        for candidate in after_reference
        if candidate <= event_end + timedelta(minutes=5)
    ]
    if window_candidates:
        return min(window_candidates)
    if after_reference:
        return min(after_reference)
    return None


def _build_checkpoints(
    execution_blocks: Sequence[PlanningExecutionBlock],
    lead_minutes: int,
) -> list[PlanningCheckpoint]:
    if lead_minutes <= 0:
        return []

    checkpoints: list[PlanningCheckpoint] = []
    sorted_blocks = sorted(execution_blocks, key=lambda block: block.start)

    for index, block in enumerate(sorted_blocks):
        block_start = datetime.fromisoformat(block.start)
        block_end = datetime.fromisoformat(block.end)
        remind_at = block_end - timedelta(minutes=lead_minutes)
        if remind_at <= block_start:
            continue

        next_block = sorted_blocks[index + 1] if index + 1 < len(sorted_blocks) else None
        prompt = _build_checkpoint_prompt(block, next_block, remind_at)
        checkpoint_id = build_fallback_item_uid(
            "planning-checkpoint",
            block.block_id,
            remind_at.isoformat(),
        )
        checkpoints.append(
            PlanningCheckpoint(
                checkpoint_id=checkpoint_id,
                remind_at=remind_at.isoformat(),
                source_event_uid=block.source_event_uid,
                source_event_title=block.source_event_title,
                block_id=block.block_id,
                block_title=block.title,
                block_start=block.start,
                block_end=block.end,
                prompt=prompt,
            )
        )

    return checkpoints


def select_due_checkpoints(
    checkpoints: Sequence[PlanningCheckpoint],
    at: datetime,
    window_minutes: int = 10,
) -> list[PlanningCheckpoint]:
    if window_minutes < 0:
        window_minutes = 0

    window_end = at + timedelta(minutes=window_minutes)
    return [
        checkpoint
        for checkpoint in checkpoints
        if at <= datetime.fromisoformat(checkpoint.remind_at) <= window_end
    ]


def _build_checkpoint_prompt(
    block: PlanningExecutionBlock,
    next_block: Optional[PlanningExecutionBlock],
    remind_at: datetime,
) -> str:
    remind_label = remind_at.strftime("%H:%M")
    if next_block is not None and next_block.source_event_uid == block.source_event_uid:
        next_start = datetime.fromisoformat(next_block.start).strftime("%H:%M")
        return (
            f"{remind_label} 체크: '{block.title}' 마무리됐는지 확인해 주세요. "
            f"끝났다면 {next_start}부터 '{next_block.title}'로 넘어가고, "
            "아직 안 끝났다면 남은 핵심 한 가지만 정리해서 다음 블록으로 이월해 주세요."
        )
    return (
        f"{remind_label} 체크: '{block.title}' 마무리됐는지 확인해 주세요. "
        f"'{block.source_event_title}' 일정 종료 전 정리할 시간입니다. "
        "완료 여부와 남은 한 가지를 짧게 남겨두면 다음 판단이 쉬워집니다."
    )
