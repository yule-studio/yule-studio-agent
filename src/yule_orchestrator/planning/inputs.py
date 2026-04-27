from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
from typing import Optional, Sequence

from ..integrations.calendar.models import CalendarEvent, CalendarQueryResult, CalendarTodo
from ..integrations.github.issues import GitHubIssue
from ..storage import list_calendar_state_records
from .models import PlanningInputs, PlanningSourceStatus, ReminderItem


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
    include_calendar: bool = True,
    include_github: bool = True,
    reminders: Optional[Sequence[ReminderItem]] = None,
    prefetched_calendar_result: Optional[CalendarQueryResult] = None,
    prefetched_github_issues: Optional[Sequence[GitHubIssue]] = None,
) -> PlanningInputs:
    warnings: list[str] = []
    source_statuses: list[PlanningSourceStatus] = []
    calendar_events: Sequence[CalendarEvent] = []
    calendar_todos: Sequence[CalendarTodo] = []
    github_issues: Sequence[GitHubIssue] = []
    reminder_items = list(reminders or [])

    if include_calendar:
        if prefetched_calendar_result is not None:
            calendar_events = prefetched_calendar_result.events
            calendar_todos = prefetched_calendar_result.todos
            source_statuses.append(
                PlanningSourceStatus(
                    source_id="calendar-prefetched",
                    source_type="calendar",
                    ok=True,
                    item_count=len(calendar_events) + len(calendar_todos),
                )
            )
        else:
            state_events, state_todos = _load_calendar_items_from_state(plan_date)
            calendar_events = state_events
            calendar_todos = state_todos
            if state_events or state_todos:
                source_statuses.append(
                    PlanningSourceStatus(
                        source_id="calendar-state",
                        source_type="calendar",
                        ok=True,
                        item_count=len(calendar_events) + len(calendar_todos),
                    )
                )
            else:
                warning = (
                    "no calendar state for the requested date; run `yule daily-warmup` to populate."
                )
                warnings.append(f"calendar: {warning}")
                source_statuses.append(
                    PlanningSourceStatus(
                        source_id="calendar-state",
                        source_type="calendar",
                        ok=False,
                        item_count=0,
                        warning=warning,
                    )
                )

    if include_github:
        if prefetched_github_issues is not None:
            github_issues = list(prefetched_github_issues)
            source_statuses.append(
                PlanningSourceStatus(
                    source_id="github-issues-prefetched",
                    source_type="github",
                    ok=True,
                    item_count=len(github_issues),
                )
            )
        else:
            warning = (
                "github issues are only available via warmup; supply `prefetched_github_issues`."
            )
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

    return build_planning_inputs(
        plan_date=plan_date,
        source_statuses=source_statuses,
        warnings=warnings,
        calendar_events=calendar_events,
        calendar_todos=calendar_todos,
        github_issues=github_issues,
        reminders=reminder_items,
    )


def build_planning_inputs(
    *,
    plan_date: date,
    timezone: Optional[str] = None,
    source_statuses: Optional[Sequence[PlanningSourceStatus]] = None,
    warnings: Optional[Sequence[str]] = None,
    calendar_events: Optional[Sequence[CalendarEvent]] = None,
    calendar_todos: Optional[Sequence[CalendarTodo]] = None,
    github_issues: Optional[Sequence[GitHubIssue]] = None,
    reminders: Optional[Sequence[ReminderItem]] = None,
) -> PlanningInputs:
    resolved_timezone = timezone or datetime.now().astimezone().tzname() or "local"
    return PlanningInputs(
        plan_date=plan_date,
        timezone=resolved_timezone,
        source_statuses=list(source_statuses or []),
        warnings=list(warnings or []),
        calendar_events=list(calendar_events or []),
        calendar_todos=list(calendar_todos or []),
        github_issues=list(github_issues or []),
        reminders=list(reminders or []),
    )


def _load_calendar_items_from_state(plan_date: date) -> tuple[list[CalendarEvent], list[CalendarTodo]]:
    records = list_calendar_state_records(
        start_date=plan_date,
        end_date=plan_date,
        include_completed=True,
    )
    events: list[CalendarEvent] = []
    todos: list[CalendarTodo] = []

    for record in records:
        try:
            if record.item_type == "event":
                events.append(CalendarEvent.from_dict(record.payload))
            elif record.item_type == "todo":
                todos.append(CalendarTodo.from_dict(record.payload))
        except Exception:
            continue

    return (
        sorted(events, key=lambda event: event.sort_key()),
        sorted(todos, key=lambda todo: todo.sort_key()),
    )
