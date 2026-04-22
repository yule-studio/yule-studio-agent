from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Sequence

from ..integrations.calendar.models import CalendarTodo
from ..integrations.github.issues import GitHubIssue
from .models import PlanningInputs, PlanningTaskCandidate, ReminderItem


def build_task_candidates(inputs: PlanningInputs) -> list[PlanningTaskCandidate]:
    tasks: list[PlanningTaskCandidate] = []

    for todo in inputs.calendar_todos:
        if todo.completed:
            continue
        tasks.append(_build_todo_candidate(inputs.plan_date, todo))

    for issue in inputs.github_issues:
        tasks.append(_build_issue_candidate(issue))

    for reminder in inputs.reminders:
        tasks.append(_build_reminder_candidate(inputs.plan_date, reminder))

    tasks.sort(key=lambda task: (-task.priority_score, task.due_date or "9999-12-31", task.title.lower()))
    return tasks


def _build_todo_candidate(plan_date: date, todo: CalendarTodo) -> PlanningTaskCandidate:
    score = 40
    reasons = ["calendar todo"]
    due_date = _date_only(todo.due or todo.start)

    if due_date is not None:
        offset = (due_date - plan_date).days
        if offset < 0:
            score += 50
            reasons.append("overdue")
        elif offset == 0:
            score += 35
            reasons.append("due today")
        elif offset == 1:
            score += 15
            reasons.append("due tomorrow")

    keyword_score, keyword_reasons = _keyword_boost(todo.title, todo.description)
    score += keyword_score
    reasons.extend(keyword_reasons)

    return PlanningTaskCandidate(
        task_id=f"todo:{todo.item_uid}",
        source_type="calendar_todo",
        title=todo.title,
        description=todo.description,
        due_date=todo.due or todo.start,
        priority_score=score,
        priority_level=_priority_level(score),
        estimated_minutes=60,
        reasons=reasons,
        coding_candidate=_looks_like_coding_work(todo.title, todo.description),
    )


def _build_issue_candidate(issue: GitHubIssue) -> PlanningTaskCandidate:
    score = 35
    reasons = ["open GitHub issue", "coding candidate"]

    if issue.scope == "personal":
        score += 10
        reasons.append("personal repository")
    elif issue.scope.startswith("org:"):
        score += 5
        reasons.append("organization repository")

    keyword_score, keyword_reasons = _keyword_boost(issue.title, "")
    score += keyword_score
    reasons.extend(keyword_reasons)

    return PlanningTaskCandidate(
        task_id=f"issue:{issue.repository}#{issue.number}",
        source_type="github_issue",
        title=issue.title,
        description=issue.url,
        due_date=None,
        priority_score=score,
        priority_level=_priority_level(score),
        estimated_minutes=90,
        reasons=reasons,
        coding_candidate=True,
    )


def _build_reminder_candidate(plan_date: date, reminder: ReminderItem) -> PlanningTaskCandidate:
    score = 45
    reasons = ["reminder item"]
    due_date = _date_only(reminder.due_date)

    if due_date is not None:
        offset = (due_date - plan_date).days
        if offset < 0:
            score += 40
            reasons.append("review overdue")
        elif offset == 0:
            score += 25
            reasons.append("review today")
        elif offset == 1:
            score += 10
            reasons.append("review tomorrow")

    if reminder.priority_hint:
        hint = reminder.priority_hint.strip().lower()
        if hint in {"high", "urgent", "critical"}:
            score += 20
            reasons.append("high priority hint")
        elif hint == "medium":
            score += 8
            reasons.append("medium priority hint")

    keyword_score, keyword_reasons = _keyword_boost(reminder.title, reminder.description)
    score += keyword_score
    reasons.extend(keyword_reasons)

    return PlanningTaskCandidate(
        task_id=f"reminder:{reminder.item_id}",
        source_type="review_reminder",
        title=reminder.title,
        description=reminder.description,
        due_date=reminder.due_date,
        priority_score=score,
        priority_level=_priority_level(score),
        estimated_minutes=max(15, reminder.estimated_minutes),
        reasons=reasons,
        coding_candidate=_looks_like_coding_work(reminder.title, reminder.description, reminder.tags),
    )


def _date_only(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    if "T" in value:
        return datetime.fromisoformat(value).date()
    return date.fromisoformat(value)


def _priority_level(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _keyword_boost(title: str, description: str) -> tuple[int, list[str]]:
    haystack = f"{title}\n{description}".lower()
    score = 0
    reasons: list[str] = []

    high_keywords = ["오늘", "urgent", "긴급", "마감", "시험", "신청", "fix", "bug", "hotfix", "error"]
    medium_keywords = ["정리", "문서", "분석", "review", "복습"]

    if any(keyword in haystack for keyword in high_keywords):
        score += 20
        reasons.append("urgent keyword")
    if any(keyword in haystack for keyword in medium_keywords):
        score += 8
        reasons.append("review or documentation keyword")

    return score, reasons


def _looks_like_coding_work(title: str, description: str, tags: Optional[Sequence[str]] = None) -> bool:
    combined = f"{title}\n{description}".lower()
    tag_values = [tag.lower() for tag in (tags or [])]
    coding_keywords = [
        "api",
        "backend",
        "bug",
        "code",
        "coding",
        "dev",
        "docs",
        "issue",
        "pr",
        "refactor",
        "repository",
        "server",
        "test",
        "agent",
    ]
    if any(keyword in combined for keyword in coding_keywords):
        return True
    return any(tag in {"coding", "dev", "backend", "review"} for tag in tag_values)
