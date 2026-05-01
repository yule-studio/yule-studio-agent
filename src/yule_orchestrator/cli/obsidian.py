from __future__ import annotations

import sys
from typing import Optional

from ..agents.obsidian_export import render_research_note
from ..agents.obsidian_writer import (
    ObsidianWriteError,
    resolve_vault_root,
    write_note,
)
from ..agents.research_pack import pack_from_dict
from ..agents.workflow_state import load_session


VALID_KINDS = ("research", "decision", "reference")


def run_obsidian_sync_command(
    session_id: str,
    *,
    kind: Optional[str],
    vault_path: Optional[str],
    overwrite: bool,
    dry_run: bool,
) -> int:
    if kind is not None and kind not in VALID_KINDS:
        print(
            f"error: --kind must be one of {list(VALID_KINDS)}, got {kind!r}",
            file=sys.stderr,
        )
        return 1

    session = load_session(session_id)
    if session is None:
        print(
            f"error: workflow session {session_id!r} not found in local cache.",
            file=sys.stderr,
        )
        return 1

    pack_payload = (session.extra or {}).get("research_pack")
    if not pack_payload:
        print(
            f"error: session {session_id!r} has no research_pack in session.extra. "
            "Run the engineering-agent research flow first so a pack is collected.",
            file=sys.stderr,
        )
        return 1

    try:
        pack = pack_from_dict(pack_payload)
    except Exception as exc:  # noqa: BLE001 - surface parse failures plainly
        print(f"error: could not parse stored research_pack: {exc}", file=sys.stderr)
        return 1

    try:
        vault_root = resolve_vault_root(override=vault_path)
    except ObsidianWriteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    note = render_research_note(pack, session=session, kind=kind)

    try:
        result = write_note(
            note,
            vault_root,
            overwrite=overwrite,
            dry_run=dry_run,
        )
    except ObsidianWriteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    relative = note.path.full
    if result.dry_run:
        print(f"dry-run: would write {result.target_path}")
        print(f"vault={vault_root} relative={relative}")
        return 0
    if not result.written:
        print(f"skipped: {result.target_path}")
        if result.skipped_reason:
            print(f"reason: {result.skipped_reason}")
        return 0
    print(f"wrote: {result.target_path}")
    print(f"vault={vault_root} relative={relative}")
    return 0
