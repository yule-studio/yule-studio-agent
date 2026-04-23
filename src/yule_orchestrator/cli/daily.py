from __future__ import annotations

from datetime import date, datetime
import json
import time
from typing import Any, Callable, Optional, Sequence, TypeVar

from ..integrations.calendar import list_naver_calendar_items
from ..integrations.github.issues import list_open_issues
from ..observability import RuntimeStepMetric, save_runtime_metric_run
from ..planning import (
    build_daily_plan,
    collect_planning_inputs,
    load_reminder_items,
    save_daily_plan_snapshot,
)
from ..storage import local_cache_database_path

T = TypeVar("T")


def run_daily_warmup_command(
    date_text: Optional[str],
    github_limit: int,
    reminders_file: Optional[str],
    skip_calendar: bool,
    skip_github: bool,
    force_refresh: bool,
    reminder_lead_minutes: int | str | Sequence[int],
    json_output: bool,
    use_ollama: Optional[bool] = None,
    ollama_model: Optional[str] = None,
    ollama_endpoint: Optional[str] = None,
    ollama_timeout_seconds: Optional[int] = None,
) -> int:
    plan_date = _parse_date(date_text)
    started_at = datetime.now().astimezone()
    steps: list[RuntimeStepMetric] = []
    payload: dict[str, Any] = {
        "action": "daily_warmup",
        "plan_date": plan_date.isoformat(),
        "force_refresh": force_refresh,
        "database_path": str(local_cache_database_path()),
    }

    calendar_result = None
    if skip_calendar:
        steps.append(_skipped_step("calendar_fetch"))
    else:
        calendar_result, metric = _measure_step(
            "calendar_fetch",
            lambda: list_naver_calendar_items(plan_date, plan_date, force_refresh=force_refresh),
            metadata=lambda result: {
                "event_count": len(result.events),
                "todo_count": len(result.todos),
                "calendar_metrics": dict(getattr(result, "metrics", {}) or {}),
                "force_refresh": force_refresh,
            },
        )
        steps.append(metric)
        if calendar_result is not None:
            payload["calendar"] = {
                "event_count": len(calendar_result.events),
                "todo_count": len(calendar_result.todos),
                "metrics": dict(getattr(calendar_result, "metrics", {}) or {}),
            }

    github_issues = None
    if skip_github:
        steps.append(_skipped_step("github_fetch"))
    else:
        github_issues, metric = _measure_step(
            "github_fetch",
            lambda: list_open_issues(limit=github_limit, force_refresh=force_refresh),
            metadata=lambda result: {
                "issue_count": len(result),
                "limit": github_limit,
                "force_refresh": force_refresh,
            },
        )
        steps.append(metric)
        if github_issues is not None:
            payload["github"] = {"issue_count": len(github_issues)}

    snapshot_payload = None
    snapshot, metric = _measure_step(
        "planning_build",
        lambda: _build_and_save_snapshot(
            plan_date=plan_date,
            github_limit=github_limit,
            reminders_file=reminders_file,
            skip_calendar=skip_calendar,
            skip_github=skip_github,
            reminder_lead_minutes=reminder_lead_minutes,
            use_ollama=use_ollama,
            ollama_model=ollama_model,
            ollama_endpoint=ollama_endpoint,
            ollama_timeout_seconds=ollama_timeout_seconds,
        ),
        metadata=lambda result: {
            "recommended_task_count": result["recommended_task_count"],
            "checkpoint_count": result["checkpoint_count"],
        },
    )
    steps.append(metric)
    if snapshot is not None:
        snapshot_payload = snapshot
        payload["snapshot"] = snapshot_payload

    ended_at = datetime.now().astimezone()
    metric_payload = save_runtime_metric_run(
        workflow="daily-warmup",
        started_at=started_at,
        ended_at=ended_at,
        steps=steps,
        metadata={
            "plan_date": plan_date.isoformat(),
            "skip_calendar": skip_calendar,
            "skip_github": skip_github,
            "force_refresh": force_refresh,
        },
    )
    payload["metrics"] = metric_payload

    has_error = any(not step.ok for step in steps)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1 if has_error else 0

    print(f"daily warmup for {plan_date.isoformat()}")
    for step in steps:
        status = "ok" if step.ok else "failed"
        if step.metadata.get("skipped"):
            status = "skipped"
        print(f"- {step.name}: {status} ({step.duration_seconds:.3f}s)")
        if step.error:
            print(f"  error: {step.error}")
    if snapshot_payload is not None:
        print(f"snapshot: {snapshot_payload['cache_key']}")
    print(f"metrics: {metric_payload['run_id']}")
    return 1 if has_error else 0


def _build_and_save_snapshot(
    *,
    plan_date: date,
    github_limit: int,
    reminders_file: Optional[str],
    skip_calendar: bool,
    skip_github: bool,
    reminder_lead_minutes: int | str | Sequence[int],
    use_ollama: Optional[bool],
    ollama_model: Optional[str],
    ollama_endpoint: Optional[str],
    ollama_timeout_seconds: Optional[int],
) -> dict[str, Any]:
    reminders = load_reminder_items(reminders_file)
    inputs = collect_planning_inputs(
        plan_date=plan_date,
        github_limit=github_limit,
        include_calendar=not skip_calendar,
        include_github=not skip_github,
        reminders=reminders,
    )
    envelope = build_daily_plan(
        inputs,
        reminder_lead_minutes=reminder_lead_minutes,
        use_ollama=use_ollama,
        ollama_model=ollama_model,
        ollama_endpoint=ollama_endpoint,
        ollama_timeout_seconds=ollama_timeout_seconds,
    )
    snapshot = save_daily_plan_snapshot(envelope)
    return {
        "cache_key": snapshot.cache_key,
        "generated_at": snapshot.generated_at.isoformat(),
        "recommended_task_count": envelope.daily_plan.summary.recommended_task_count,
        "checkpoint_count": len(envelope.daily_plan.checkpoints),
    }


def _measure_step(
    name: str,
    callback: Callable[[], T],
    metadata: Optional[Callable[[T], dict[str, Any]]] = None,
) -> tuple[Optional[T], RuntimeStepMetric]:
    started_at = datetime.now().astimezone()
    started = time.perf_counter()
    try:
        result = callback()
    except Exception as exc:
        ended_at = datetime.now().astimezone()
        return None, RuntimeStepMetric(
            name=name,
            duration_seconds=time.perf_counter() - started,
            ok=False,
            started_at=started_at.isoformat(),
            ended_at=ended_at.isoformat(),
            metadata={},
            error=str(exc),
        )

    ended_at = datetime.now().astimezone()
    return result, RuntimeStepMetric(
        name=name,
        duration_seconds=time.perf_counter() - started,
        ok=True,
        started_at=started_at.isoformat(),
        ended_at=ended_at.isoformat(),
        metadata=metadata(result) if metadata is not None else {},
    )


def _skipped_step(name: str) -> RuntimeStepMetric:
    now = datetime.now().astimezone().isoformat()
    return RuntimeStepMetric(
        name=name,
        duration_seconds=0.0,
        ok=True,
        started_at=now,
        ended_at=now,
        metadata={"skipped": True},
    )


def _parse_date(value: Optional[str]) -> date:
    if value is None:
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("--date must use YYYY-MM-DD format.") from exc
