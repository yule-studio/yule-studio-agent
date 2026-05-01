"""Persist ResearchPack/synthesis artifacts onto a workflow session.

Used by:

- The Discord engineering channel router, immediately after ``intake_fn``
  creates a session, so the collected ``ResearchPack`` lands in
  ``session.extra["research_pack"]`` even if the downstream research loop
  short-circuits as ``insufficient`` or fails entirely.
- The forum research-loop hook, after the deliberation runs, to
  additionally persist ``TechLeadSynthesis`` and the ``CollectionOutcome``
  metadata.

The function is idempotent — repeated calls with the same payload write
the same ``session.extra`` keys, so persisting eagerly at intake time and
again later from the forum hook is safe.

Failures are caught and logged so this helper never breaks the caller's
control flow; the worst case is that ``session.extra`` does not get the
new keys, which the Obsidian sync CLI surfaces explicitly.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any, Optional

from .deliberation import synthesis_to_dict
from .research_pack import pack_to_dict
from .workflow_state import WorkflowSession, update_session


def persist_research_artifacts(
    session: Optional[WorkflowSession],
    pack: Any = None,
    *,
    collection_outcome: Any = None,
    synthesis: Any = None,
    synthesis_text: Optional[str] = None,
) -> Optional[WorkflowSession]:
    """Write research artifacts onto ``session.extra`` and return the new session.

    Returns the original session unchanged when there is nothing to
    persist (all inputs None) or when the caller passed ``session=None``.
    Errors are swallowed with a stderr-style warning so a single failure
    cannot wedge the engineering flow.
    """

    if session is None:
        return session
    if pack is None and synthesis is None and collection_outcome is None:
        return session
    try:
        extra = dict(getattr(session, "extra", None) or {})
        if pack is not None:
            extra["research_pack"] = pack_to_dict(pack)
        if collection_outcome is not None:
            mode = getattr(collection_outcome, "mode", None)
            mode_value = getattr(mode, "value", mode)
            extra["research_collection"] = {
                "mode": str(mode_value) if mode_value is not None else None,
                "collector_name": getattr(collection_outcome, "collector_name", None),
                "query": getattr(collection_outcome, "query", None),
                "auto_collected_count": getattr(
                    collection_outcome, "auto_collected_count", None
                ),
            }
        if synthesis is not None:
            extra["research_synthesis"] = synthesis_to_dict(synthesis)
        if synthesis_text:
            extra["research_synthesis_text"] = str(synthesis_text)
        updated = replace(session, extra=extra)
        return update_session(updated, now=datetime.now().astimezone())
    except Exception as exc:  # noqa: BLE001 - forum loop can continue without persisted context
        print(f"warning: research pack persistence failed: {exc}")
        return session
