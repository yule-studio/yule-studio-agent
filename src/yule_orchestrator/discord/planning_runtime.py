from __future__ import annotations

from datetime import date, datetime, timedelta

from ..planning import build_daily_plan, collect_planning_inputs
from ..planning.models import DailyPlanEnvelope, PlanningCheckpoint


def build_plan_today_envelope(
    plan_date: date,
    *,
    use_ollama: bool = False,
) -> DailyPlanEnvelope:
    inputs = collect_planning_inputs(plan_date=plan_date)
    return build_daily_plan(inputs, use_ollama=use_ollama)


def build_due_checkpoints(
    window_start: datetime,
    *,
    window_minutes: int,
) -> list[PlanningCheckpoint]:
    if window_minutes <= 0:
        return []

    window_end = window_start + timedelta(minutes=window_minutes)
    checkpoints: dict[str, PlanningCheckpoint] = {}
    plan_date = window_start.date()

    while plan_date <= window_end.date():
        inputs = collect_planning_inputs(
            plan_date=plan_date,
            include_calendar=True,
            include_github=False,
            reminders=[],
        )
        envelope = build_daily_plan(inputs)
        for checkpoint in envelope.daily_plan.checkpoints:
            remind_at = datetime.fromisoformat(checkpoint.remind_at)
            if window_start <= remind_at <= window_end:
                checkpoints[checkpoint.checkpoint_id] = checkpoint
        plan_date += timedelta(days=1)

    return sorted(checkpoints.values(), key=lambda checkpoint: checkpoint.remind_at)
