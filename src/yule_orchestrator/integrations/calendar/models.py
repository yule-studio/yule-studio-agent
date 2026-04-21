from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence


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
