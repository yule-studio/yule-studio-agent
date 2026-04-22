from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence

from ..integrations.calendar.models import CalendarEvent, CalendarTodo
from ..integrations.github.issues import GitHubIssue


@dataclass(frozen=True)
class PlanningSourceStatus:
    source_id: str
    source_type: str
    ok: bool
    item_count: int
    warning: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "ok": self.ok,
            "item_count": self.item_count,
            "warning": self.warning,
        }


@dataclass(frozen=True)
class ReminderItem:
    item_id: str
    title: str
    description: str = ""
    due_date: Optional[str] = None
    priority_hint: Optional[str] = None
    estimated_minutes: int = 30
    tags: Sequence[str] = ()

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "title": self.title,
            "description": self.description,
            "due_date": self.due_date,
            "priority_hint": self.priority_hint,
            "estimated_minutes": self.estimated_minutes,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "ReminderItem":
        tags = payload.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        due_date = _optional_string(payload.get("due_date"))
        priority_hint = _optional_string(payload.get("priority_hint"))
        return cls(
            item_id=str(payload.get("item_id") or payload.get("id") or payload.get("title") or "reminder"),
            title=str(payload.get("title") or "(untitled reminder)"),
            description=str(payload.get("description") or ""),
            due_date=due_date,
            priority_hint=priority_hint,
            estimated_minutes=_estimated_minutes_from_value(payload.get("estimated_minutes")),
            tags=[str(tag) for tag in tags],
        )


@dataclass(frozen=True)
class PlanningInputs:
    plan_date: date
    timezone: str
    source_statuses: Sequence[PlanningSourceStatus]
    warnings: Sequence[str]
    calendar_events: Sequence[CalendarEvent]
    calendar_todos: Sequence[CalendarTodo]
    github_issues: Sequence[GitHubIssue]
    reminders: Sequence[ReminderItem]

    def to_dict(self) -> dict:
        return {
            "plan_date": self.plan_date.isoformat(),
            "timezone": self.timezone,
            "source_statuses": [status.to_dict() for status in self.source_statuses],
            "warnings": list(self.warnings),
            "calendar_events": [event.to_dict() for event in self.calendar_events],
            "calendar_todos": [todo.to_dict() for todo in self.calendar_todos],
            "github_issues": [issue.to_dict() for issue in self.github_issues],
            "reminders": [reminder.to_dict() for reminder in self.reminders],
        }


@dataclass(frozen=True)
class DailyPlanSummary:
    fixed_event_count: int
    all_day_event_count: int
    todo_count: int
    github_issue_count: int
    reminder_count: int
    recommended_task_count: int
    available_focus_minutes: int

    def to_dict(self) -> dict:
        return {
            "fixed_event_count": self.fixed_event_count,
            "all_day_event_count": self.all_day_event_count,
            "todo_count": self.todo_count,
            "github_issue_count": self.github_issue_count,
            "reminder_count": self.reminder_count,
            "recommended_task_count": self.recommended_task_count,
            "available_focus_minutes": self.available_focus_minutes,
        }


@dataclass(frozen=True)
class PlanningTaskCandidate:
    task_id: str
    source_type: str
    title: str
    description: str
    due_date: Optional[str]
    priority_score: int
    priority_level: str
    estimated_minutes: int
    reasons: Sequence[str]
    coding_candidate: bool

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "source_type": self.source_type,
            "title": self.title,
            "description": self.description,
            "due_date": self.due_date,
            "priority_score": self.priority_score,
            "priority_level": self.priority_level,
            "estimated_minutes": self.estimated_minutes,
            "reasons": list(self.reasons),
            "coding_candidate": self.coding_candidate,
        }


@dataclass(frozen=True)
class PlanningTimeBlock:
    start: str
    end: str
    block_type: str
    title: str
    task_id: Optional[str]
    locked: bool

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "block_type": self.block_type,
            "title": self.title,
            "task_id": self.task_id,
            "locked": self.locked,
        }


@dataclass(frozen=True)
class PlanningExecutionBlock:
    block_id: str
    source_event_uid: str
    source_event_title: str
    start: str
    end: str
    title: str
    description: str

    def to_dict(self) -> dict:
        return {
            "block_id": self.block_id,
            "source_event_uid": self.source_event_uid,
            "source_event_title": self.source_event_title,
            "start": self.start,
            "end": self.end,
            "title": self.title,
            "description": self.description,
        }


@dataclass(frozen=True)
class PlanningBlockBriefing:
    briefing_id: str
    start: str
    end: str
    title: str
    block_type: str
    source_ref: Optional[str]
    briefing: str

    def to_dict(self) -> dict:
        return {
            "briefing_id": self.briefing_id,
            "start": self.start,
            "end": self.end,
            "title": self.title,
            "block_type": self.block_type,
            "source_ref": self.source_ref,
            "briefing": self.briefing,
        }


@dataclass(frozen=True)
class PlanningCheckpoint:
    checkpoint_id: str
    remind_at: str
    source_event_uid: str
    source_event_title: str
    block_id: str
    block_title: str
    block_start: str
    block_end: str
    prompt: str
    kind: str = "wrap_up"

    def to_dict(self) -> dict:
        return {
            "checkpoint_id": self.checkpoint_id,
            "remind_at": self.remind_at,
            "source_event_uid": self.source_event_uid,
            "source_event_title": self.source_event_title,
            "block_id": self.block_id,
            "block_title": self.block_title,
            "block_start": self.block_start,
            "block_end": self.block_end,
            "prompt": self.prompt,
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "PlanningCheckpoint":
        return cls(
            checkpoint_id=str(payload["checkpoint_id"]),
            remind_at=str(payload["remind_at"]),
            source_event_uid=str(payload["source_event_uid"]),
            source_event_title=str(payload["source_event_title"]),
            block_id=str(payload["block_id"]),
            block_title=str(payload["block_title"]),
            block_start=str(payload["block_start"]),
            block_end=str(payload["block_end"]),
            prompt=str(payload["prompt"]),
            kind=str(payload.get("kind") or "wrap_up"),
        )


@dataclass(frozen=True)
class DailyPlan:
    plan_date: date
    timezone: str
    source_statuses: Sequence[PlanningSourceStatus]
    warnings: Sequence[str]
    summary: DailyPlanSummary
    fixed_schedule: Sequence[PlanningTimeBlock]
    execution_blocks: Sequence[PlanningExecutionBlock]
    prioritized_tasks: Sequence[PlanningTaskCandidate]
    suggested_time_blocks: Sequence[PlanningTimeBlock]
    morning_briefing: str
    time_block_briefings: Sequence[PlanningBlockBriefing]
    checkpoints: Sequence[PlanningCheckpoint]
    coding_agent_handoff: Sequence[PlanningTaskCandidate]
    discord_briefing: str
    morning_briefing_source: str
    discord_briefing_source: str

    def to_dict(self) -> dict:
        return {
            "plan_date": self.plan_date.isoformat(),
            "timezone": self.timezone,
            "source_statuses": [status.to_dict() for status in self.source_statuses],
            "warnings": list(self.warnings),
            "summary": self.summary.to_dict(),
            "fixed_schedule": [block.to_dict() for block in self.fixed_schedule],
            "execution_blocks": [block.to_dict() for block in self.execution_blocks],
            "prioritized_tasks": [task.to_dict() for task in self.prioritized_tasks],
            "suggested_time_blocks": [block.to_dict() for block in self.suggested_time_blocks],
            "morning_briefing": self.morning_briefing,
            "time_block_briefings": [briefing.to_dict() for briefing in self.time_block_briefings],
            "checkpoints": [checkpoint.to_dict() for checkpoint in self.checkpoints],
            "coding_agent_handoff": [task.to_dict() for task in self.coding_agent_handoff],
            "discord_briefing": self.discord_briefing,
            "morning_briefing_source": self.morning_briefing_source,
            "discord_briefing_source": self.discord_briefing_source,
        }


def _optional_string(value: object) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _estimated_minutes_from_value(value: object) -> int:
    if value is None or value == "":
        return 30

    try:
        estimated_minutes = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"estimated_minutes must be an integer-compatible value, got: {value!r}") from exc

    return max(15, estimated_minutes)


@dataclass(frozen=True)
class DailyPlanEnvelope:
    inputs: PlanningInputs
    daily_plan: DailyPlan

    def to_dict(self) -> dict:
        return {
            "inputs": self.inputs.to_dict(),
            "daily_plan": self.daily_plan.to_dict(),
        }
