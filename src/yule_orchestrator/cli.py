from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Optional

from .context_loader import ContextError, load_agent_context, render_context
from .doctor import doctor_exit_code, render_doctor_report, run_doctor


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

    return parser


def run_context_command(repo_root: Path, agent_id: str, output: Optional[str]) -> int:
    loaded_context = load_agent_context(repo_root=repo_root, agent_id=agent_id)
    rendered = render_context(loaded_context)

    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
        print(str(output_path))
        return 0

    print(rendered)
    return 0


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    repo_root = Path(args.repo_root).resolve()

    try:
        if args.command == "context":
            return run_context_command(repo_root, args.agent_id, args.output)
        if args.command == "doctor":
            checks = run_doctor(repo_root=repo_root, agent_id=args.agent_id)
            print(render_doctor_report(checks), end="")
            return doctor_exit_code(checks)
    except ContextError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"unknown command: {args.command}")
    return 2
