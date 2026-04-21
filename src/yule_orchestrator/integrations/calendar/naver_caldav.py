from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import os
from typing import Any, Iterable, List, Optional, Sequence


class CalendarIntegrationError(Exception):
    """Raised when Naver calendar events cannot be loaded."""


@dataclass(frozen=True)
class NaverCalDAVConfig:
    url: str
    username: str
    password: str
    calendar_name: Optional[str] = None


@dataclass(frozen=True)
class CalendarEvent:
    title: str
    start: str
    end: str
    all_day: bool
    calendar_name: str
    source: str
    description: str

    def sort_key(self) -> tuple[int, str, str]:
        return (0 if self.all_day else 1, self.start, self.title.lower())

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "start": self.start,
            "end": self.end,
            "all_day": self.all_day,
            "calendar_name": self.calendar_name,
            "source": self.source,
            "description": self.description,
        }


@dataclass(frozen=True)
class CalendarTodo:
    title: str
    start: Optional[str]
    due: Optional[str]
    start_all_day: bool
    due_all_day: bool
    status: str
    completed: bool
    completed_at: Optional[str]
    priority: Optional[int]
    percent_complete: Optional[int]
    calendar_name: str
    source: str
    description: str

    def sort_key(self) -> tuple[int, str, str]:
        return (
            1 if self.completed else 0,
            self.due or self.start or "9999-12-31T23:59:59+09:00",
            self.title.lower(),
        )

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "start": self.start,
            "due": self.due,
            "start_all_day": self.start_all_day,
            "due_all_day": self.due_all_day,
            "status": self.status,
            "completed": self.completed,
            "completed_at": self.completed_at,
            "priority": self.priority,
            "percent_complete": self.percent_complete,
            "calendar_name": self.calendar_name,
            "source": self.source,
            "description": self.description,
        }


@dataclass(frozen=True)
class CalendarQueryResult:
    source: str
    start_date: date
    end_date: date
    events: Sequence[CalendarEvent]
    todos: Sequence[CalendarTodo]


def list_naver_calendar_items(start_date: date, end_date: date) -> CalendarQueryResult:
    config = load_naver_caldav_config()
    client_cls, calendar_cls = _load_caldav_dependencies()

    query_start = _to_local_datetime(start_date)
    query_end = _to_local_datetime(end_date + timedelta(days=1))

    events: List[CalendarEvent] = []
    todos: List[CalendarTodo] = []
    seen_events: set[tuple[str, str, str, str]] = set()
    seen_todos: set[tuple[str, Optional[str], Optional[str], str, str]] = set()

    with client_cls(url=config.url, username=config.username, password=config.password) as client:
        principal = client.principal()
        calendars = principal.calendars()
        selected_calendars = _select_calendars(calendars, config.calendar_name)

        for calendar in selected_calendars:
            calendar_label = _calendar_label(calendar)
            resources = calendar.date_search(start=query_start, end=query_end, expand=True)

            for resource in resources:
                raw_ical = _resource_ical_payload(resource)
                calendar_obj = calendar_cls.from_ical(raw_ical)
                for component in calendar_obj.walk("VEVENT"):
                    event = _build_event(component, calendar_label)
                    if event is None:
                        continue
                    dedupe_key = (event.title, event.start, event.end, event.calendar_name)
                    if dedupe_key in seen_events:
                        continue
                    seen_events.add(dedupe_key)
                    events.append(event)
                for component in calendar_obj.walk("VTODO"):
                    todo = _build_todo(component, calendar_label)
                    if todo is None:
                        continue
                    dedupe_key = (todo.title, todo.start, todo.due, todo.status, todo.calendar_name)
                    if dedupe_key in seen_todos:
                        continue
                    seen_todos.add(dedupe_key)
                    todos.append(todo)

            for resource in _list_todo_resources(calendar):
                raw_ical = _resource_ical_payload(resource)
                calendar_obj = calendar_cls.from_ical(raw_ical)
                for component in calendar_obj.walk("VTODO"):
                    todo = _build_todo(component, calendar_label)
                    if todo is None or not _todo_matches_range(todo, start_date, end_date):
                        continue
                    dedupe_key = (todo.title, todo.start, todo.due, todo.status, todo.calendar_name)
                    if dedupe_key in seen_todos:
                        continue
                    seen_todos.add(dedupe_key)
                    todos.append(todo)

    events.sort(key=lambda event: event.sort_key())
    todos.sort(key=lambda todo: todo.sort_key())
    return CalendarQueryResult(
        source="naver-caldav",
        start_date=start_date,
        end_date=end_date,
        events=events,
        todos=todos,
    )


def list_naver_calendar_events(start_date: date, end_date: date) -> CalendarQueryResult:
    return list_naver_calendar_items(start_date=start_date, end_date=end_date)


def render_calendar_items(result: CalendarQueryResult) -> str:
    if not result.events and not result.todos:
        return (
            f"Naver Calendar Items ({result.start_date.isoformat()} to {result.end_date.isoformat()})\n\n"
            "No calendar items found for the requested range.\n"
        )

    lines: List[str] = [
        f"Naver Calendar Items ({result.start_date.isoformat()} to {result.end_date.isoformat()})",
        "",
    ]

    if result.events:
        lines.append("Events")
        lines.append("")
        for event in result.events:
            if event.all_day:
                lines.append(f"- [all-day] {event.title} ({event.calendar_name})")
            else:
                lines.append(f"- [{_format_time_range(event.start, event.end)}] {event.title} ({event.calendar_name})")
            if event.description:
                lines.append(f"  description: {event.description}")

    if result.todos:
        if len(lines) > 2:
            lines.append("")
        lines.append("Todos")
        lines.append("")
        for todo in result.todos:
            status_label = todo.status.lower()
            lines.append(f"- [{status_label}] {todo.title} ({todo.calendar_name})")
            if todo.start:
                lines.append(f"  start: {_format_temporal_value(todo.start, todo.start_all_day)}")
            if todo.due:
                lines.append(f"  due: {_format_temporal_value(todo.due, todo.due_all_day)}")
            if todo.priority is not None:
                lines.append(f"  priority: {todo.priority}")
            if todo.percent_complete is not None:
                lines.append(f"  progress: {todo.percent_complete}%")
            if todo.completed_at:
                lines.append(f"  completed_at: {_format_temporal_value(todo.completed_at, all_day=False)}")
            if todo.description:
                lines.append(f"  description: {todo.description}")

    return "\n".join(lines) + "\n"


def render_calendar_events(result: CalendarQueryResult) -> str:
    return render_calendar_items(result)


def load_naver_caldav_config() -> NaverCalDAVConfig:
    url = os.getenv("NAVER_CALDAV_URL", "https://caldav.calendar.naver.com")
    username = os.getenv("NAVER_CALDAV_USERNAME") or os.getenv("NAVER_ID")
    password = os.getenv("NAVER_CALDAV_PASSWORD") or os.getenv("NAVER_APP_PASSWORD")
    calendar_name = os.getenv("NAVER_CALDAV_CALENDAR")

    missing: List[str] = []
    if not username:
        missing.append("NAVER_CALDAV_USERNAME or NAVER_ID")
    if not password:
        missing.append("NAVER_CALDAV_PASSWORD or NAVER_APP_PASSWORD")

    if missing:
        raise CalendarIntegrationError(
            "Missing Naver CalDAV credentials: " + ", ".join(missing)
        )

    return NaverCalDAVConfig(
        url=url,
        username=username,
        password=password,
        calendar_name=calendar_name,
    )


def _load_caldav_dependencies() -> tuple[Any, Any]:
    try:
        from caldav import DAVClient
    except ImportError as exc:
        raise CalendarIntegrationError(
            "The `caldav` package is required. Run `python3 -m pip install -e .`."
        ) from exc

    try:
        from icalendar import Calendar
    except ImportError as exc:
        raise CalendarIntegrationError(
            "The `icalendar` package is required. Run `python3 -m pip install -e .`."
        ) from exc

    return DAVClient, Calendar


def _select_calendars(calendars: Iterable[Any], calendar_name: Optional[str]) -> List[Any]:
    calendars = list(calendars)
    if not calendars:
        raise CalendarIntegrationError("No calendars were found for the authenticated Naver account.")

    if calendar_name is None:
        return calendars

    selected = [calendar for calendar in calendars if _calendar_label(calendar) == calendar_name]
    if selected:
        return selected

    available = ", ".join(sorted(_calendar_label(calendar) for calendar in calendars))
    raise CalendarIntegrationError(
        f"Calendar `{calendar_name}` was not found. Available calendars: {available}"
    )


def _calendar_label(calendar: Any) -> str:
    name = getattr(calendar, "name", None)
    if callable(name):
        try:
            resolved = name()
            if isinstance(resolved, str) and resolved:
                return resolved
        except Exception:
            pass
    if isinstance(name, str) and name:
        return name

    url = getattr(calendar, "url", None)
    if isinstance(url, str) and url:
        return url.rstrip("/").split("/")[-1] or "unnamed-calendar"

    return "unnamed-calendar"


def _resource_ical_payload(resource: Any) -> str:
    data = getattr(resource, "data", None)
    if isinstance(data, str) and data.strip():
        return data
    if isinstance(data, bytes) and data.strip():
        return data.decode("utf-8")

    icalendar_instance = getattr(resource, "icalendar_instance", None)
    if icalendar_instance is not None:
        try:
            return icalendar_instance.to_ical().decode("utf-8")
        except Exception:
            pass

    raise CalendarIntegrationError("Could not extract calendar event payload from a CalDAV resource.")


def _build_event(component: Any, calendar_name: str) -> Optional[CalendarEvent]:
    title_value = component.get("summary")
    title = str(title_value) if title_value else "(untitled event)"
    description = _extract_description(component)

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

    start_dt = _normalize_datetime(start_value)
    end_dt = _normalize_datetime(end_value) if isinstance(end_value, datetime) else start_dt

    return CalendarEvent(
        title=title,
        start=start_dt.isoformat(),
        end=end_dt.isoformat(),
        all_day=False,
        calendar_name=calendar_name,
        source="naver-caldav",
        description=description,
    )


def _build_todo(component: Any, calendar_name: str) -> Optional[CalendarTodo]:
    title_value = component.get("summary")
    title = str(title_value) if title_value else "(untitled todo)"
    description = _extract_description(component)

    start_value = component.decoded("dtstart") if component.get("dtstart") else None
    due_value = component.decoded("due") if component.get("due") else None
    duration_value = component.decoded("duration") if component.get("duration") else None
    if due_value is None and duration_value is not None and isinstance(start_value, (date, datetime)):
        due_value = start_value + duration_value

    completed_value = component.decoded("completed") if component.get("completed") else None

    start, start_all_day = _normalize_temporal_value(start_value)
    due, due_all_day = _normalize_temporal_value(due_value)
    completed_at, _ = _normalize_temporal_value(completed_value)
    status = _extract_status(component)
    priority = _extract_int(component, "priority")
    percent_complete = _extract_int(component, "percent-complete")
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


def _list_todo_resources(calendar: Any) -> List[Any]:
    todos = getattr(calendar, "todos", None)
    if not callable(todos):
        return []

    try:
        return list(todos(include_completed=True))
    except TypeError:
        try:
            return list(todos())
        except Exception:
            return []
    except Exception:
        return []


def _todo_matches_range(todo: CalendarTodo, start_date: date, end_date: date) -> bool:
    candidate_values = [todo.start, todo.due, todo.completed_at]
    for value in candidate_values:
        if value is None:
            continue
        candidate_date = _date_from_iso(value)
        if start_date <= candidate_date <= end_date:
            return True

    return not todo.completed


def _extract_description(component: Any) -> str:
    for field_name in ("description", "comment"):
        value = component.get(field_name)
        if value:
            return str(value).strip()
    return ""


def _extract_status(component: Any) -> str:
    value = component.get("status")
    if value is None:
        return "NEEDS-ACTION"
    return str(value).strip().upper() or "NEEDS-ACTION"


def _extract_int(component: Any, property_name: str) -> Optional[int]:
    if component.get(property_name) is None:
        return None

    try:
        return int(component.decoded(property_name))
    except Exception:
        try:
            return int(str(component.get(property_name)).strip())
        except Exception:
            return None


def _normalize_temporal_value(value: Any) -> tuple[Optional[str], bool]:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat(), True
    if isinstance(value, datetime):
        return _normalize_datetime(value).isoformat(), False
    return None, False


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone()
    return value.replace(tzinfo=datetime.now().astimezone().tzinfo)


def _to_local_datetime(value: date) -> datetime:
    return datetime.combine(value, time.min).astimezone()


def _format_time_range(start: str, end: str) -> str:
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)
    return f"{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}"


def _format_temporal_value(value: str, all_day: bool) -> str:
    if all_day:
        return value
    return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M")


def _date_from_iso(value: str) -> date:
    if "T" in value:
        return datetime.fromisoformat(value).date()
    return date.fromisoformat(value)
