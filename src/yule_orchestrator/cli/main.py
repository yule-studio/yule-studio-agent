from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable, Optional

from ..core import ContextError, load_env_files
from ..integrations.calendar import CalendarIntegrationError
from ..integrations.github.issues import GitHubIssueError
from .calendar import (
    run_calendar_cache_cleanup_command,
    run_calendar_cache_inspect_command,
    run_calendar_events_command,
    run_calendar_warmup_command,
)
from .context import run_context_command
from .discord import run_discord_bot_command
from .doctor import run_doctor_command
from .github import run_github_issues_command
from .planning import run_planning_checkpoints_command, run_planning_daily_command


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
    calendar_events_parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore the local cache and fetch fresh calendar data.",
    )

    calendar_warmup_parser = calendar_subparsers.add_parser(
        "warmup",
        help="Prefetch and store calendar data in the local cache.",
    )
    calendar_warmup_parser.add_argument(
        "--start-date",
        help="Start date in YYYY-MM-DD format. Defaults to today.",
    )
    calendar_warmup_parser.add_argument(
        "--end-date",
        help="End date in YYYY-MM-DD format. Defaults to the same value as --start-date.",
    )
    calendar_warmup_parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON instead of the default text view.",
    )
    calendar_warmup_parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore the local cache and fetch fresh calendar data.",
    )

    calendar_cache_parser = calendar_subparsers.add_parser(
        "cache",
        help="Inspect or clean up the local calendar cache.",
    )
    calendar_cache_subparsers = calendar_cache_parser.add_subparsers(dest="calendar_cache_command", required=True)

    calendar_cache_inspect_parser = calendar_cache_subparsers.add_parser(
        "inspect",
        help="Show cached calendar query entries.",
    )
    calendar_cache_inspect_parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON instead of the default text view.",
    )
    calendar_cache_inspect_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of cache entries to show. Defaults to 20.",
    )
    calendar_cache_inspect_parser.add_argument(
        "--fresh-only",
        action="store_true",
        help="Show only unexpired cache entries.",
    )

    calendar_cache_cleanup_parser = calendar_cache_subparsers.add_parser(
        "cleanup",
        help="Delete old cache entries and stale calendar state records.",
    )
    calendar_cache_cleanup_parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON instead of the default text view.",
    )
    calendar_cache_cleanup_parser.add_argument(
        "--cache-retention-days",
        type=int,
        default=7,
        help="Keep expired cache entries for this many days before deletion. Defaults to 7.",
    )
    calendar_cache_cleanup_parser.add_argument(
        "--state-retention-days",
        type=int,
        default=30,
        help="Keep unseen calendar state records for this many days before deletion. Defaults to 30.",
    )

    planning_parser = subparsers.add_parser(
        "planning",
        help="Build a daily plan from calendar, issues, and reminder inputs.",
    )
    planning_subparsers = planning_parser.add_subparsers(dest="planning_command", required=True)

    planning_daily_parser = planning_subparsers.add_parser(
        "daily",
        help="Generate a daily plan for the target date.",
    )
    planning_daily_parser.add_argument(
        "--date",
        help="Target date in YYYY-MM-DD format. Defaults to today.",
    )
    planning_daily_parser.add_argument(
        "--github-limit",
        type=int,
        default=20,
        help="Maximum number of GitHub open issues to include. Defaults to 20.",
    )
    planning_daily_parser.add_argument(
        "--reminders-file",
        help="Optional JSON file with reminder items.",
    )
    planning_daily_parser.add_argument(
        "--skip-calendar",
        action="store_true",
        help="Skip calendar inputs and build the plan from the remaining sources.",
    )
    planning_daily_parser.add_argument(
        "--skip-github",
        action="store_true",
        help="Skip GitHub issues and build the plan from the remaining sources.",
    )
    planning_daily_parser.add_argument(
        "--reminder-lead-minutes",
        type=int,
        default=5,
        help="How many minutes before a parsed execution block ends to generate a checkpoint. Defaults to 5.",
    )
    planning_daily_parser.add_argument(
        "--use-ollama",
        action="store_true",
        help="Use Ollama to rewrite the morning briefing in a more natural tone.",
    )
    planning_daily_parser.add_argument(
        "--ollama-model",
        default="gemma3:latest",
        help="Ollama model to use when --use-ollama is enabled. Defaults to gemma3:latest.",
    )
    planning_daily_parser.add_argument(
        "--ollama-endpoint",
        default="http://localhost:11434",
        help="Ollama API endpoint. Defaults to http://localhost:11434.",
    )
    planning_daily_parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON instead of the default text view.",
    )

    planning_checkpoints_parser = planning_subparsers.add_parser(
        "checkpoints",
        help="Show due planning checkpoints for the target time window.",
    )
    planning_checkpoints_parser.add_argument(
        "--date",
        help="Target date in YYYY-MM-DD format. Defaults to the date part of --at or today.",
    )
    planning_checkpoints_parser.add_argument(
        "--at",
        help="Reference time in ISO datetime format. Defaults to now.",
    )
    planning_checkpoints_parser.add_argument(
        "--reminder-lead-minutes",
        type=int,
        default=5,
        help="How many minutes before a parsed execution block ends to generate a checkpoint. Defaults to 5.",
    )
    planning_checkpoints_parser.add_argument(
        "--window-minutes",
        type=int,
        default=10,
        help="How many minutes ahead to scan for due checkpoints. Defaults to 10.",
    )
    planning_checkpoints_parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured JSON instead of the default text view.",
    )

    discord_parser = subparsers.add_parser(
        "discord",
        help="Run Discord integrations backed by the local orchestrator.",
    )
    discord_subparsers = discord_parser.add_subparsers(dest="discord_command", required=True)

    discord_bot_parser = discord_subparsers.add_parser(
        "bot",
        help="Run the Discord bot process.",
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
            return run_calendar_events_command(
                args.start_date,
                args.end_date,
                args.json,
                args.force_refresh,
            )
        if args.command == "calendar" and args.calendar_command == "warmup":
            return run_calendar_warmup_command(
                args.start_date,
                args.end_date,
                args.json,
                args.force_refresh,
            )
        if args.command == "calendar" and args.calendar_command == "cache":
            if args.calendar_cache_command == "inspect":
                return run_calendar_cache_inspect_command(
                    args.json,
                    args.limit,
                    args.fresh_only,
                )
            if args.calendar_cache_command == "cleanup":
                return run_calendar_cache_cleanup_command(
                    args.json,
                    args.cache_retention_days,
                    args.state_retention_days,
                )
        if args.command == "planning" and args.planning_command == "daily":
            return run_planning_daily_command(
                args.date,
                args.github_limit,
                args.reminders_file,
                args.skip_calendar,
                args.skip_github,
                args.reminder_lead_minutes,
                args.use_ollama,
                args.ollama_model,
                args.ollama_endpoint,
                args.json,
            )
        if args.command == "planning" and args.planning_command == "checkpoints":
            return run_planning_checkpoints_command(
                args.date,
                args.at,
                args.reminder_lead_minutes,
                args.window_minutes,
                args.json,
            )
        if args.command == "discord" and args.discord_command == "bot":
            return run_discord_bot_command(repo_root)
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
