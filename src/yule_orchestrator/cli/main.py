from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Optional

from ..core.context_loader import ContextError
from ..integrations.github.issues import GitHubIssueError
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

    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    repo_root = Path(args.repo_root).resolve()

    try:
        if args.command == "context":
            return run_context_command(repo_root, args.agent_id, args.output)
        if args.command == "doctor":
            return run_doctor_command(repo_root, args.agent_id)
        if args.command == "github" and args.github_command == "issues":
            return run_github_issues_command(args.limit)
    except ContextError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except GitHubIssueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"unknown command: {args.command}")
    return 2
