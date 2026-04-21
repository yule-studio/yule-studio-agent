from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, List, Sequence


class GitHubIssueError(Exception):
    """Raised when open issues cannot be loaded from GitHub CLI."""


@dataclass(frozen=True)
class GitHubIssue:
    number: int
    repository: str
    title: str
    url: str


def list_open_issues(limit: int = 30) -> Sequence[GitHubIssue]:
    if not shutil.which("gh"):
        raise GitHubIssueError("GitHub CLI (`gh`) is not installed.")

    command = [
        "gh",
        "search",
        "issues",
        "--assignee",
        "@me",
        "--state",
        "open",
        "--sort",
        "updated",
        "--order",
        "desc",
        "--limit",
        str(limit),
        "--json",
        "number,title,url,repository",
    ]
    result = subprocess.run(
        command,
        check=False,
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        raise GitHubIssueError(_format_gh_error(result.stderr))

    payload = result.stdout.strip()
    if not payload:
        return []

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise GitHubIssueError(f"Could not parse GitHub CLI output: {exc}") from exc

    if not isinstance(data, list):
        raise GitHubIssueError("Unexpected GitHub CLI response format.")

    issues: List[GitHubIssue] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        number = item.get("number")
        title = item.get("title")
        url = item.get("url")
        repository = _extract_repository_name(item.get("repository"))

        if not isinstance(number, int):
            continue
        if not isinstance(title, str):
            continue
        if not isinstance(url, str):
            continue

        issues.append(
            GitHubIssue(
                number=number,
                repository=repository,
                title=title,
                url=url,
            )
        )

    return issues


def render_open_issues(issues: Sequence[GitHubIssue]) -> str:
    lines: List[str] = []

    if not issues:
        lines.append("No open GitHub issues found for the current account.")
        return "\n".join(lines) + "\n"

    lines.append("Open GitHub Issues")
    lines.append("")
    for issue in issues:
        lines.append(f"#{issue.number} {issue.repository} - {issue.title}")
        lines.append(issue.url)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _extract_repository_name(value: Any) -> str:
    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        name_with_owner = value.get("nameWithOwner")
        if isinstance(name_with_owner, str):
            return name_with_owner

        owner = value.get("owner")
        name = value.get("name")
        if isinstance(owner, dict):
            owner_login = owner.get("login")
            if isinstance(owner_login, str) and isinstance(name, str):
                return f"{owner_login}/{name}"

        if isinstance(name, str):
            return name

    return "unknown-repo"


def _format_gh_error(stderr: str) -> str:
    message = (stderr or "").strip()
    lowered = message.lower()

    if "authentication" in lowered or "gh auth login" in lowered or "not logged into any hosts" in lowered:
        return "GitHub CLI is not authenticated. Run `gh auth login`."

    if "error connecting to" in lowered or "dial tcp" in lowered or "no such host" in lowered:
        return "Could not reach GitHub. Check your network connection and GitHub availability."

    if "rate limit" in lowered:
        return "GitHub API rate limit reached."

    if message:
        first_line = message.splitlines()[0]
        return f"GitHub issue query failed: {first_line}"

    return "GitHub issue query failed."
