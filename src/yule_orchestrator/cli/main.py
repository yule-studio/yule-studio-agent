from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable, Optional

from ..core import ContextError, load_env_files
from ..integrations.calendar import CalendarIntegrationError
from ..integrations.github.issues import GitHubIssueError
from .calendar import run_calendar_events_command
from .context import run_context_command
from .doctor import run_doctor_command
from .github import run_github_issues_command


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yule",
        description="Yule Studio Agent orchestrator.",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root to read agent configuration from. Defaults to the current directory.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    context_parser = subparsers.add_parser(
        "context",
        help="Render the loaded context for an agent.",
    )
    context_parser.add_argument(
        "agent_id",
        help="Agent id to load, for example: coding-agent.",
    )
    context_parser.add_argument(
        "--output",
        help="Optional file path to write the rendered context to.",
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check local tool, auth, and model readiness.",
    )
    doctor_parser.add_argument(
        "--agent-id",
        default="coding-agent",
        help="Agent id to use for manifest-backed checks. Defaults to coding-agent.",
    )

    github_parser = subparsers.add_parser(
        "github",
        help="Read GitHub data through the authenticated gh CLI.",
    )
    github_subparsers = github_parser.add_subparsers(dest="github_command", required=True)

    github_issues_parser = github_subparsers.add_parser(
        "issues",
        help="List open GitHub issues for the current account.",
    )
    github_issues_parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Maximum number of open issues to fetch. Defaults to 30.",
    )

    calendar_parser = subparsers.add_parser(
        "calendar",
        help="Read calendar data through supported calendar integrations.",
    )
    calendar_subparsers = calendar_parser.add_subparsers(dest="calendar_command", required=True)

    calendar_events_parser = calendar_subparsers.add_parser(
        "events",
        help="Read Naver calendar items and convert them into structured data.",
    )
    calendar_events_parser.add_argument(
        "--start-date",
        help="Start date in YYYY-MM-DD format. Defaults to today.",
    )
    calendar_events_parser.add_argument(
        "--end-date",
        help="End date in YYYY-MM-DD format. Defaults to the same value as --start-date.",
    )
    calendar_events_parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON instead of the default text view.",
    )

    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    repo_root = Path(args.repo_root).resolve()
    os.environ["YULE_REPO_ROOT"] = str(repo_root)
    load_env_files(repo_root)

    try:
        if args.command == "context":
            return run_context_command(repo_root, args.agent_id, args.output)
        if args.command == "doctor":
            return run_doctor_command(repo_root, args.agent_id)
        if args.command == "github" and args.github_command == "issues":
            return run_github_issues_command(args.limit)
        if args.command == "calendar" and args.calendar_command == "events":
            return run_calendar_events_command(args.start_date, args.end_date, args.json)
    except ContextError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except GitHubIssueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except CalendarIntegrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"unknown command: {args.command}")
    return 2
