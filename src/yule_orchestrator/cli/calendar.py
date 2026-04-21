from __future__ import annotations

import json
from datetime import date
from typing import Optional

from ..integrations.calendar import (
    CalendarIntegrationError,
    CalendarQueryResult,
    list_naver_calendar_items,
    render_calendar_items,
)
from ..integrations.calendar.errors import build_calendar_validation_error


def run_calendar_events_command(
    start_date_text: Optional[str],
    end_date_text: Optional[str],
    json_output: bool,
) -> int:
    try:
        start_date, end_date = _resolve_date_range(start_date_text, end_date_text)
        result = list_naver_calendar_items(start_date=start_date, end_date=end_date)
    except ValueError as exc:
        if not json_output:
            raise
        print(json.dumps({"error": build_calendar_validation_error(str(exc)).to_dict()}, ensure_ascii=False, indent=2))
        return 1
    except CalendarIntegrationError as exc:
        if not json_output:
            raise
        print(json.dumps({"error": exc.to_dict()}, ensure_ascii=False, indent=2))
        return 1

    if json_output:
        print(json.dumps(_result_to_dict(result), ensure_ascii=False, indent=2))
        return 0

    print(render_calendar_items(result), end="")
    return 0


def _resolve_date_range(
    start_date_text: Optional[str],
    end_date_text: Optional[str],
) -> tuple[date, date]:
    if start_date_text is None and end_date_text is None:
        today = date.today()
        return today, today

    if start_date_text is None:
        raise ValueError("--end-date requires --start-date.")

    start_date = _parse_date(start_date_text, flag_name="--start-date")
    end_date = start_date if end_date_text is None else _parse_date(end_date_text, flag_name="--end-date")

    if end_date < start_date:
        raise ValueError("--end-date must be the same as or later than --start-date.")

    return start_date, end_date


def _parse_date(value: str, flag_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{flag_name} must use YYYY-MM-DD format.") from exc


def _result_to_dict(result: CalendarQueryResult) -> dict:
    return result.to_dict()
