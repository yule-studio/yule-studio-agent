from __future__ import annotations

from ..integrations.github.issues import list_open_issues, render_open_issues


def run_github_issues_command(limit: int) -> int:
    issues = list_open_issues(limit=limit)
    print(render_open_issues(issues), end="")
    return 0
