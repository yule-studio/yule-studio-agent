from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

from .models import CalendarEvent, CalendarTodo


def build_event(component: Any, calendar_name: str) -> Optional[CalendarEvent]:
    title_value = component.get("summary")
    title = str(title_value) if title_value else "(untitled event)"
    description = extract_description(component)

    start_value = component.decoded("dtstart")
    end_value = component.decoded("dtend") if component.get("dtend") else None

    if isinstance(start_value, date) and not isinstance(start_value, datetime):
        start_date = start_value
        end_date = end_value if isinstance(end_value, date) and not isinstance(end_value, datetime) else start_date + timedelta(days=1)
        return CalendarEvent(
            title=title,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            all_day=True,
            calendar_name=calendar_name,
            source="naver-caldav",
            description=description,
        )

    if not isinstance(start_value, datetime):
        return None

    start_dt = normalize_datetime(start_value)
    end_dt = normalize_datetime(end_value) if isinstance(end_value, datetime) else start_dt

    return CalendarEvent(
        title=title,
        start=start_dt.isoformat(),
        end=end_dt.isoformat(),
        all_day=False,
        calendar_name=calendar_name,
        source="naver-caldav",
        description=description,
    )


def build_todo(component: Any, calendar_name: str) -> CalendarTodo:
    title_value = component.get("summary")
    title = str(title_value) if title_value else "(untitled todo)"
    description = extract_description(component)

    start_value = component.decoded("dtstart") if component.get("dtstart") else None
    due_value = component.decoded("due") if component.get("due") else None
    duration_value = component.decoded("duration") if component.get("duration") else None
    if due_value is None and duration_value is not None and isinstance(start_value, (date, datetime)):
        due_value = start_value + duration_value

    completed_value = component.decoded("completed") if component.get("completed") else None

    start, start_all_day = normalize_temporal_value(start_value)
    due, due_all_day = normalize_temporal_value(due_value)
    completed_at, _ = normalize_temporal_value(completed_value)
    status = extract_status(component)
    priority = extract_int(component, "priority")
    percent_complete = extract_int(component, "percent-complete")
    completed = status == "COMPLETED" or completed_at is not None or percent_complete == 100

    return CalendarTodo(
        title=title,
        start=start,
        due=due,
        start_all_day=start_all_day,
        due_all_day=due_all_day,
        status=status,
        completed=completed,
        completed_at=completed_at,
        priority=priority,
        percent_complete=percent_complete,
        calendar_name=calendar_name,
        source="naver-caldav",
        description=description,
    )


def todo_matches_range(todo: CalendarTodo, start_date: date, end_date: date) -> bool:
    candidate_values = [todo.start, todo.due, todo.completed_at]
    for value in candidate_values:
        if value is None:
            continue
        candidate_date = date_from_iso(value)
        if start_date <= candidate_date <= end_date:
            return True

    return False


def extract_description(component: Any) -> str:
    for field_name in ("description", "comment"):
        value = component.get(field_name)
        if value:
            return str(value).strip()
    return ""


def extract_status(component: Any) -> str:
    value = component.get("status")
    if value is None:
        return "NEEDS-ACTION"
    return str(value).strip().upper() or "NEEDS-ACTION"


def extract_int(component: Any, property_name: str) -> Optional[int]:
    if component.get(property_name) is None:
        return None

    try:
        return int(component.decoded(property_name))
    except Exception:
        try:
            return int(str(component.get(property_name)).strip())
        except Exception:
            return None


def normalize_temporal_value(value: Any) -> tuple[Optional[str], bool]:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat(), True
    if isinstance(value, datetime):
        return normalize_datetime(value).isoformat(), False
    return None, False


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone()
    return value.replace(tzinfo=datetime.now().astimezone().tzinfo)


def date_from_iso(value: str) -> date:
    if "T" in value:
        return datetime.fromisoformat(value).date()
    return date.fromisoformat(value)
