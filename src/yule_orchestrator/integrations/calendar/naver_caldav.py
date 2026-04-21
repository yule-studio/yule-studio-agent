from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import logging
import os
from typing import Any, Iterable, List, Optional

from .cache import build_calendar_cache_key, load_calendar_cache, save_calendar_cache
from .models import CalendarQueryResult
from .parsing import build_event, build_todo, todo_matches_range
from .rendering import render_calendar_events, render_calendar_items


class CalendarIntegrationError(Exception):
    """Raised when Naver calendar items cannot be loaded."""


@dataclass(frozen=True)
class NaverCalDAVConfig:
    url: str
    username: str
    password: str
    calendar_name: Optional[str] = None
    todo_calendar_name: Optional[str] = None
    timeout_seconds: int = 15
    include_all_todos: bool = False
    cache_seconds: int = 300


def list_naver_calendar_items(start_date: date, end_date: date) -> CalendarQueryResult:
    config = load_naver_caldav_config()
    cache_key = build_calendar_cache_key(
        "naver-caldav",
        config.url,
        config.username,
        config.calendar_name or "",
        config.todo_calendar_name or "",
        str(config.include_all_todos),
        start_date.isoformat(),
        end_date.isoformat(),
    )
    cached_result = load_calendar_cache(cache_key, ttl_seconds=config.cache_seconds)
    if cached_result is not None:
        return cached_result

    client_cls, calendar_cls = _load_caldav_dependencies()

    query_start = _to_local_datetime(start_date)
    query_end = _to_local_datetime(end_date + timedelta(days=1))

    events = []
    todos = []
    seen_events: set[tuple[str, str, str, str]] = set()
    seen_todos: set[tuple[str, Optional[str], Optional[str], str, str]] = set()

    try:
        with client_cls(
            url=config.url,
            username=config.username,
            password=config.password,
            timeout=config.timeout_seconds,
        ) as client:
            principal = client.principal()
            all_calendars = list(principal.calendars())
            todo_calendars = _select_todo_calendars(
                all_calendars=all_calendars,
                todo_calendar_name=config.todo_calendar_name,
                fallback_calendars=_select_calendars(all_calendars, config.calendar_name),
            )
            event_calendars = _select_event_calendars(
                all_calendars=all_calendars,
                calendar_name=config.calendar_name,
                todo_calendars=todo_calendars,
            )
            todo_calendar_ids = {_calendar_identifier(calendar) for calendar in todo_calendars}
            event_calendar_ids = {_calendar_identifier(calendar) for calendar in event_calendars}
            processed_calendar_ids: set[str] = set()

            for calendar in [*event_calendars, *todo_calendars]:
                calendar_id = _calendar_identifier(calendar)
                if calendar_id in processed_calendar_ids:
                    continue
                processed_calendar_ids.add(calendar_id)
                calendar_label = _calendar_label(calendar)
                _collect_dated_items(
                    calendar=calendar,
                    calendar_label=calendar_label,
                    calendar_cls=calendar_cls,
                    query_start=query_start,
                    query_end=query_end,
                    include_events=calendar_id in event_calendar_ids,
                    include_todos=calendar_id in todo_calendar_ids,
                    events=events,
                    todos=todos,
                    seen_events=seen_events,
                    seen_todos=seen_todos,
                )

            if not todos:
                for calendar in todo_calendars:
                    calendar_label = _calendar_label(calendar)
                    _collect_search_todos(
                        calendar=calendar,
                        calendar_label=calendar_label,
                        calendar_cls=calendar_cls,
                        query_start=query_start,
                        query_end=query_end,
                        start_date=start_date,
                        end_date=end_date,
                        todos=todos,
                        seen_todos=seen_todos,
                    )

                if config.include_all_todos:
                    for calendar in todo_calendars:
                        calendar_label = _calendar_label(calendar)
                        _collect_all_todos(
                            calendar=calendar,
                            calendar_label=calendar_label,
                            calendar_cls=calendar_cls,
                            start_date=start_date,
                            end_date=end_date,
                            todos=todos,
                            seen_todos=seen_todos,
                        )
    except CalendarIntegrationError:
        raise
    except Exception as exc:
        raise CalendarIntegrationError(
            _describe_caldav_error(exc, timeout_seconds=config.timeout_seconds)
        ) from exc

    events.sort(key=lambda event: event.sort_key())
    todos.sort(key=lambda todo: todo.sort_key())
    result = CalendarQueryResult(
        source="naver-caldav",
        start_date=start_date,
        end_date=end_date,
        events=events,
        todos=todos,
    )
    save_calendar_cache(cache_key, ttl_seconds=config.cache_seconds, result=result)
    return result


def list_naver_calendar_events(start_date: date, end_date: date) -> CalendarQueryResult:
    return list_naver_calendar_items(start_date=start_date, end_date=end_date)


def load_naver_caldav_config() -> NaverCalDAVConfig:
    url = os.getenv("NAVER_CALDAV_URL", "https://caldav.calendar.naver.com")
    username = os.getenv("NAVER_CALDAV_USERNAME") or os.getenv("NAVER_ID")
    password = os.getenv("NAVER_CALDAV_PASSWORD") or os.getenv("NAVER_APP_PASSWORD")
    calendar_name = os.getenv("NAVER_CALDAV_CALENDAR")
    todo_calendar_name = os.getenv("NAVER_CALDAV_TODO_CALENDAR")
    timeout_seconds = _load_timeout_seconds()
    include_all_todos = _load_bool_env("NAVER_CALDAV_INCLUDE_ALL_TODOS", default=False)
    cache_seconds = _load_cache_seconds()

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
        todo_calendar_name=todo_calendar_name,
        timeout_seconds=timeout_seconds,
        include_all_todos=include_all_todos,
        cache_seconds=cache_seconds,
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

    logging.getLogger("caldav").setLevel(logging.ERROR)
    return DAVClient, Calendar


def _collect_dated_items(
    calendar: Any,
    calendar_label: str,
    calendar_cls: Any,
    query_start: datetime,
    query_end: datetime,
    include_events: bool,
    include_todos: bool,
    events: List[Any],
    todos: List[Any],
    seen_events: set[tuple[str, str, str, str]],
    seen_todos: set[tuple[str, Optional[str], Optional[str], str, str]],
) -> None:
    resources = calendar.date_search(start=query_start, end=query_end, expand=True)

    for resource in resources:
        raw_ical = _resource_ical_payload(resource)
        calendar_obj = calendar_cls.from_ical(raw_ical)

        if include_events:
            for component in calendar_obj.walk("VEVENT"):
                event = build_event(component, calendar_label)
                if event is None:
                    continue
                dedupe_key = (event.title, event.start, event.end, event.calendar_name)
                if dedupe_key in seen_events:
                    continue
                seen_events.add(dedupe_key)
                events.append(event)

        if include_todos:
            for component in calendar_obj.walk("VTODO"):
                todo = build_todo(component, calendar_label)
                dedupe_key = (todo.title, todo.start, todo.due, todo.status, todo.calendar_name)
                if dedupe_key in seen_todos:
                    continue
                seen_todos.add(dedupe_key)
                todos.append(todo)


def _collect_all_todos(
    calendar: Any,
    calendar_label: str,
    calendar_cls: Any,
    start_date: date,
    end_date: date,
    todos: List[Any],
    seen_todos: set[tuple[str, Optional[str], Optional[str], str, str]],
) -> None:
    for resource in _list_todo_resources(calendar):
        raw_ical = _resource_ical_payload(resource)
        calendar_obj = calendar_cls.from_ical(raw_ical)

        for component in calendar_obj.walk("VTODO"):
            todo = build_todo(component, calendar_label)
            if not todo_matches_range(todo, start_date, end_date):
                continue

            dedupe_key = (todo.title, todo.start, todo.due, todo.status, todo.calendar_name)
            if dedupe_key in seen_todos:
                continue
            seen_todos.add(dedupe_key)
            todos.append(todo)


def _collect_search_todos(
    calendar: Any,
    calendar_label: str,
    calendar_cls: Any,
    query_start: datetime,
    query_end: datetime,
    start_date: date,
    end_date: date,
    todos: List[Any],
    seen_todos: set[tuple[str, Optional[str], Optional[str], str, str]],
) -> None:
    search = getattr(calendar, "search", None)
    if not callable(search):
        return

    try:
        resources = search(
            todo=True,
            start=query_start,
            end=query_end,
            include_completed=True,
            expand=False,
        )
    except Exception:
        return

    for resource in resources:
        raw_ical = _resource_ical_payload(resource)
        calendar_obj = calendar_cls.from_ical(raw_ical)

        for component in calendar_obj.walk("VTODO"):
            todo = build_todo(component, calendar_label)
            if not todo_matches_range(todo, start_date, end_date):
                continue

            dedupe_key = (todo.title, todo.start, todo.due, todo.status, todo.calendar_name)
            if dedupe_key in seen_todos:
                continue
            seen_todos.add(dedupe_key)
            todos.append(todo)


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


def _select_todo_calendars(
    all_calendars: Iterable[Any],
    todo_calendar_name: Optional[str],
    fallback_calendars: Iterable[Any],
) -> List[Any]:
    calendars = list(all_calendars)
    fallback = list(fallback_calendars)

    if not calendars:
        return []

    if todo_calendar_name:
        selected = [calendar for calendar in calendars if _calendar_label(calendar) == todo_calendar_name]
        if selected:
            return selected
        auto_detected = _autodetect_todo_calendars(calendars)
        if auto_detected:
            return auto_detected
        return fallback or calendars

    auto_detected = _autodetect_todo_calendars(calendars)
    if auto_detected:
        return auto_detected

    return fallback or calendars


def _select_event_calendars(
    all_calendars: Iterable[Any],
    calendar_name: Optional[str],
    todo_calendars: Iterable[Any],
) -> List[Any]:
    selected = _select_calendars(all_calendars, calendar_name)
    if calendar_name is not None:
        return selected

    todo_calendar_ids = {_calendar_identifier(calendar) for calendar in todo_calendars}
    filtered = [
        calendar
        for calendar in selected
        if _calendar_identifier(calendar) not in todo_calendar_ids
    ]
    return filtered or selected


def _autodetect_todo_calendars(calendars: Iterable[Any]) -> List[Any]:
    matches = [calendar for calendar in calendars if _looks_like_todo_calendar(_calendar_label(calendar))]
    if len(matches) == 1:
        return matches
    if len(matches) > 1:
        return matches
    return []


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


def _calendar_identifier(calendar: Any) -> str:
    url = getattr(calendar, "url", None)
    if isinstance(url, str) and url:
        return url
    return _calendar_label(calendar)


def _looks_like_todo_calendar(label: str) -> bool:
    normalized = label.strip().lower()
    return "할 일" in normalized or "todo" in normalized or "task" in normalized


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

    raise CalendarIntegrationError("Could not extract calendar item payload from a CalDAV resource.")


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


def _load_timeout_seconds() -> int:
    raw_value = os.getenv("NAVER_CALDAV_TIMEOUT_SECONDS", "15").strip()
    try:
        timeout = int(raw_value)
    except ValueError as exc:
        raise CalendarIntegrationError(
            "NAVER_CALDAV_TIMEOUT_SECONDS must be an integer."
        ) from exc

    if timeout <= 0:
        raise CalendarIntegrationError(
            "NAVER_CALDAV_TIMEOUT_SECONDS must be greater than 0."
        )

    return timeout


def _load_cache_seconds() -> int:
    raw_value = os.getenv("NAVER_CALDAV_CACHE_SECONDS", "300").strip()
    try:
        ttl = int(raw_value)
    except ValueError as exc:
        raise CalendarIntegrationError(
            "NAVER_CALDAV_CACHE_SECONDS must be an integer."
        ) from exc

    if ttl < 0:
        raise CalendarIntegrationError(
            "NAVER_CALDAV_CACHE_SECONDS must be 0 or greater."
        )

    return ttl


def _load_bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    raise CalendarIntegrationError(
        f"{name} must be one of: true, false, 1, 0, yes, no, on, off."
    )


def _describe_caldav_error(exc: Exception, timeout_seconds: int) -> str:
    class_name = exc.__class__.__name__.lower()
    message = str(exc).strip()
    message_lower = message.lower()

    if "timeout" in class_name or "timed out" in message_lower or "read timed out" in message_lower:
        return (
            "Naver CalDAV request timed out. "
            f"Check your network or reduce server delay, then try again. "
            f"Current timeout: {timeout_seconds}s."
        )

    if "401" in message_lower or "403" in message_lower or "unauthorized" in message_lower or "forbidden" in message_lower:
        return (
            "Naver CalDAV authentication failed. "
            "Check NAVER_ID, NAVER_APP_PASSWORD, and CalDAV app-password settings."
        )

    if message:
        return f"Naver CalDAV request failed: {message}"

    return "Naver CalDAV request failed for an unknown reason."


def _to_local_datetime(value: date) -> datetime:
    return datetime.combine(value, time.min).astimezone()


__all__ = [
    "CalendarIntegrationError",
    "NaverCalDAVConfig",
    "list_naver_calendar_items",
    "list_naver_calendar_events",
    "load_naver_caldav_config",
    "render_calendar_items",
    "render_calendar_events",
]
