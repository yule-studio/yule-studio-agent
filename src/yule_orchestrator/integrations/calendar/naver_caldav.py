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
        }


@dataclass(frozen=True)
class CalendarQueryResult:
    source: str
    start_date: date
    end_date: date
    events: Sequence[CalendarEvent]


def list_naver_calendar_events(start_date: date, end_date: date) -> CalendarQueryResult:
    config = load_naver_caldav_config()
    client_cls, calendar_cls = _load_caldav_dependencies()

    query_start = _to_local_datetime(start_date)
    query_end = _to_local_datetime(end_date + timedelta(days=1))

    events: List[CalendarEvent] = []
    seen: set[tuple[str, str, str, str]] = set()

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
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    events.append(event)

    events.sort(key=lambda event: event.sort_key())
    return CalendarQueryResult(
        source="naver-caldav",
        start_date=start_date,
        end_date=end_date,
        events=events,
    )


def render_calendar_events(result: CalendarQueryResult) -> str:
    if not result.events:
        return (
            f"Naver Calendar Events ({result.start_date.isoformat()} to {result.end_date.isoformat()})\n\n"
            "No events found for the requested range.\n"
        )

    lines: List[str] = [
        f"Naver Calendar Events ({result.start_date.isoformat()} to {result.end_date.isoformat()})",
        "",
    ]
    for event in result.events:
        if event.all_day:
            lines.append(f"- [all-day] {event.title} ({event.calendar_name})")
        else:
            lines.append(f"- [{_format_time_range(event.start, event.end)}] {event.title} ({event.calendar_name})")

    return "\n".join(lines) + "\n"


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
    )


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
