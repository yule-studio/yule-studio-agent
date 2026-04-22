from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
from typing import Optional, Sequence

from ..integrations.calendar import CalendarIntegrationError, list_naver_calendar_items
from ..integrations.calendar.models import CalendarEvent, CalendarTodo
from ..integrations.github.issues import GitHubIssue, GitHubIssueError, list_open_issues
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
