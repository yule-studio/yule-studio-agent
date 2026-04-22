from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo
import re
from typing import Optional, Sequence

from ..integrations.calendar.models import CalendarEvent, build_fallback_item_uid
from .models import PlanningCheckpoint, PlanningExecutionBlock, PlanningTaskCandidate, PlanningTimeBlock

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


def build_fixed_schedule(events: Sequence[CalendarEvent]) -> list[PlanningTimeBlock]:
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


def build_focus_blocks(
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


def build_execution_blocks(events: Sequence[CalendarEvent]) -> list[PlanningExecutionBlock]:
    blocks: list[PlanningExecutionBlock] = []
    for event in events:
        if event.all_day or not event.description.strip():
            continue

        try:
            event_start = datetime.fromisoformat(event.start)
            event_end = datetime.fromisoformat(event.end)
        except ValueError:
            continue

        blocks.extend(
            _parse_execution_blocks_from_description(
                event=event,
                event_start=event_start,
                event_end=event_end,
            )
        )

    blocks.sort(key=lambda block: block.start)
    return blocks


def build_checkpoints(
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


def _available_windows(
    plan_date: date,
    fixed_schedule: Sequence[PlanningTimeBlock],
) -> list[tuple[datetime, datetime]]:
    timezone = _derive_schedule_timezone(fixed_schedule)
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


def _derive_schedule_timezone(fixed_schedule: Sequence[PlanningTimeBlock]) -> Optional[tzinfo]:
    for block in fixed_schedule:
        try:
            parsed = datetime.fromisoformat(block.start)
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            return parsed.tzinfo

    return datetime.now().astimezone().tzinfo


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
