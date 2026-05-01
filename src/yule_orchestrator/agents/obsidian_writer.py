"""Thin file-writer layer for Obsidian notes.

Sits on top of :mod:`yule_orchestrator.agents.obsidian_export` and writes
the rendered :class:`ObsidianNote` content to a real Obsidian vault on
disk. The exporter still owns the contract (frontmatter, body, vault path
shape); this module only handles IO.

Safety guarantees:

- Vault root must be an absolute path that already exists as a directory.
- The resolved file path must remain inside the vault root (no traversal
  via ``..`` or symlinks resolving outside).
- Parent directories are created automatically.
- Overwrite of an existing file is refused unless ``overwrite=True``.
- ``dry_run=True`` performs all checks but never writes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .obsidian_export import ObsidianNote


ENV_VAULT_PATH = "OBSIDIAN_VAULT_PATH"


class ObsidianWriteError(RuntimeError):
    """Raised when an Obsidian write request cannot be honored safely."""


@dataclass(frozen=True)
class ObsidianWriteResult:
    """Outcome of one write attempt.

    ``written`` is False for dry-runs and for skipped overwrites; the
    caller can still report ``target_path`` to the user.
    """

    target_path: Path
    written: bool
    dry_run: bool
    overwrite: bool
    skipped_reason: Optional[str] = None


def resolve_vault_root(env: Optional[dict] = None, *, override: Optional[str] = None) -> Path:
    """Return the absolute vault root from ``override`` or ``OBSIDIAN_VAULT_PATH``.

    Raises :class:`ObsidianWriteError` with a human-readable message when
    the value is missing, not absolute, missing on disk, or not a
    directory. Validation lives here so the CLI gets one consistent
    failure mode regardless of how the path was supplied.
    """

    raw = (override or "").strip() if override is not None else ""
    if not raw:
        source = env if env is not None else os.environ
        raw = (source.get(ENV_VAULT_PATH) or "").strip()
    if not raw:
        raise ObsidianWriteError(
            f"{ENV_VAULT_PATH} is not set. "
            "Add it to .env.local with the absolute path to your Obsidian vault."
        )

    expanded = os.path.expanduser(raw)
    path = Path(expanded)
    if not path.is_absolute():
        raise ObsidianWriteError(
            f"{ENV_VAULT_PATH} must be an absolute path; got {raw!r}."
        )
    if not path.exists():
        raise ObsidianWriteError(
            f"Obsidian vault root does not exist: {path}. "
            "Open the vault in Obsidian once or fix the path in .env.local."
        )
    if not path.is_dir():
        raise ObsidianWriteError(
            f"Obsidian vault root is not a directory: {path}."
        )
    return path.resolve()


def write_note(
    note: ObsidianNote,
    vault_root: Path,
    *,
    overwrite: bool = False,
    dry_run: bool = False,
) -> ObsidianWriteResult:
    """Write *note.content* to ``<vault_root>/<note.path.full>``.

    Returns an :class:`ObsidianWriteResult` describing what happened.
    Caller is expected to surface ``target_path`` and ``skipped_reason``
    to the user.
    """

    vault_root_resolved = vault_root.resolve()
    relative = note.path.full
    target = (vault_root_resolved / relative).resolve()

    try:
        target.relative_to(vault_root_resolved)
    except ValueError as exc:
        raise ObsidianWriteError(
            f"Refusing to write outside the vault root. "
            f"vault={vault_root_resolved} target={target}"
        ) from exc

    if target.exists() and not overwrite:
        return ObsidianWriteResult(
            target_path=target,
            written=False,
            dry_run=dry_run,
            overwrite=overwrite,
            skipped_reason="file already exists; pass --overwrite to replace it",
        )

    if dry_run:
        return ObsidianWriteResult(
            target_path=target,
            written=False,
            dry_run=True,
            overwrite=overwrite,
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(note.content, encoding="utf-8")
    return ObsidianWriteResult(
        target_path=target,
        written=True,
        dry_run=False,
        overwrite=overwrite,
    )
