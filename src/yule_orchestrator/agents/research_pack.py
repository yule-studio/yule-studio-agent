"""ResearchPack — neutral data model for research artifacts.

A :class:`ResearchPack` bundles everything we know about *one research item*
inside engineering-agent (and any future department): one or more
:class:`ResearchSource` rows (with author/role/channel/thread provenance),
optional :class:`ResearchAttachment` rows for non-URL artifacts (images,
files, embeds), and a few free-text fields for title/summary.

The shape is **transport-agnostic on purpose**:

- Discord forum publisher (``discord/research_forum.py``) ingests these
  to produce thread bodies and per-role comments.
- dispatcher / workflow may later read ``url`` lists for reference packs.
- Obsidian export (``obsidian_export.py``) serializes these to markdown.

This module never calls Discord, never reads the network, and never
writes files. It's pure dataclasses + small URL/dedup helpers, so unit
tests can exercise it without any I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResearchAttachment:
    """A non-URL artifact attached to a source (image, file, embed).

    ``kind`` is free-form (``image``/``file``/``embed``/...) so we can carry
    Discord attachment shapes without coupling to discord.py types.
    """

    kind: str
    url: str
    filename: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    description: Optional[str] = None


@dataclass(frozen=True)
class ResearchSource:
    """A single piece of provenance for a research pack.

    A pack often has 1 source (the originating Discord message) but can
    grow to N when multiple messages get folded together (`merge`). Each
    source carries enough provenance for Obsidian export and audit.
    """

    source_url: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    author_role: Optional[str] = None
    channel_id: Optional[int] = None
    thread_id: Optional[int] = None
    message_id: Optional[int] = None
    posted_at: Optional[datetime] = None
    attachments: Sequence[ResearchAttachment] = field(default_factory=tuple)
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def discord_origin(self) -> bool:
        return any(
            v is not None for v in (self.channel_id, self.thread_id, self.message_id)
        )


@dataclass(frozen=True)
class ResearchPack:
    """The composite artifact: title + summary + N sources.

    ``primary_url`` is a convenience pointer (often the first source's URL).
    ``urls`` is the deduped union across all sources + ``primary_url``.
    Both are derived; constructing helpers preserve them.
    """

    title: str
    summary: str = ""
    primary_url: Optional[str] = None
    sources: Sequence[ResearchSource] = field(default_factory=tuple)
    tags: Sequence[str] = field(default_factory=tuple)
    created_at: Optional[datetime] = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def urls(self) -> Tuple[str, ...]:
        seen: dict[str, None] = {}
        for url in (self.primary_url, *(s.source_url for s in self.sources)):
            cleaned = _clean_url(url)
            if cleaned and cleaned not in seen:
                seen[cleaned] = None
        return tuple(seen.keys())

    @property
    def attachments(self) -> Tuple[ResearchAttachment, ...]:
        seen: dict[Tuple[str, str], ResearchAttachment] = {}
        for source in self.sources:
            for att in source.attachments:
                key = (att.kind, _clean_url(att.url) or att.url)
                if key not in seen:
                    seen[key] = att
        return tuple(seen.values())

    @property
    def author_roles(self) -> Tuple[str, ...]:
        seen: dict[str, None] = {}
        for source in self.sources:
            role = (source.author_role or "").strip()
            if role and role not in seen:
                seen[role] = None
        return tuple(seen.keys())


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


_URL_PATTERN = re.compile(r"https?://[\w\-./?=&%#:+,@!~*'();$]+", re.IGNORECASE)
_TRAILING_TRIM = ".,);"


def extract_urls(text: str) -> Tuple[str, ...]:
    """Pull URLs out of free text, dedup while preserving first-seen order."""

    if not text:
        return ()
    seen: dict[str, None] = {}
    for raw in _URL_PATTERN.findall(text):
        cleaned = _clean_url(raw)
        if cleaned and cleaned not in seen:
            seen[cleaned] = None
    return tuple(seen.keys())


def dedup_urls(urls: Iterable[Optional[str]]) -> Tuple[str, ...]:
    """Return *urls* with whitespace/trailing punctuation cleaned and deduped.

    Preserves first-seen order. Empty/None inputs are dropped.
    """

    seen: dict[str, None] = {}
    for url in urls:
        cleaned = _clean_url(url)
        if cleaned and cleaned not in seen:
            seen[cleaned] = None
    return tuple(seen.keys())


def _clean_url(value: Optional[str]) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text.rstrip(_TRAILING_TRIM)


# ---------------------------------------------------------------------------
# Pack constructors / merging
# ---------------------------------------------------------------------------


def pack_from_discord_message(
    *,
    title: str,
    content: str,
    author_role: Optional[str] = None,
    channel_id: Optional[int] = None,
    thread_id: Optional[int] = None,
    message_id: Optional[int] = None,
    posted_at: Optional[datetime] = None,
    attachments: Sequence[ResearchAttachment] = (),
    summary: Optional[str] = None,
    tags: Sequence[str] = (),
    extra: Optional[Mapping[str, Any]] = None,
) -> ResearchPack:
    """Build a single-source pack from one Discord message.

    URLs found in *content* populate ``primary_url`` (first match) and the
    source's ``source_url``. The remaining URLs end up only in
    :attr:`ResearchPack.urls` so callers can iterate them.
    """

    urls = extract_urls(content)
    primary = urls[0] if urls else None
    source = ResearchSource(
        source_url=primary,
        title=title or None,
        summary=(summary or content).strip() or None,
        author_role=author_role,
        channel_id=channel_id,
        thread_id=thread_id,
        message_id=message_id,
        posted_at=posted_at,
        attachments=tuple(attachments),
    )
    pack_summary = (summary or content).strip()
    return ResearchPack(
        title=title.strip() or "(untitled)",
        summary=pack_summary,
        primary_url=primary,
        sources=(source,),
        tags=tuple(tags),
        created_at=posted_at,
        extra=dict(extra or {}),
    )


def merge_packs(packs: Sequence[ResearchPack]) -> ResearchPack:
    """Fold N packs into one — preserving first non-empty title/summary.

    Sources, tags, and URLs are unioned with dedup. ``primary_url`` is the
    first non-empty URL seen across input packs. ``created_at`` is the
    earliest non-None timestamp. Useful when forum publisher folds
    multiple messages from a thread into one composite pack.
    """

    if not packs:
        raise ValueError("merge_packs requires at least one input pack")

    title = next((p.title for p in packs if (p.title or "").strip() and p.title != "(untitled)"), packs[0].title)
    summary = next((p.summary for p in packs if (p.summary or "").strip()), "")
    primary_url = next((p.primary_url for p in packs if _clean_url(p.primary_url)), None)

    seen_sources: dict[Tuple[Any, ...], ResearchSource] = {}
    for p in packs:
        for s in p.sources:
            key = (
                s.message_id,
                s.thread_id,
                s.channel_id,
                _clean_url(s.source_url),
            )
            if key not in seen_sources:
                seen_sources[key] = s

    seen_tags: dict[str, None] = {}
    for p in packs:
        for tag in p.tags:
            t = (tag or "").strip()
            if t and t not in seen_tags:
                seen_tags[t] = None

    timestamps = [p.created_at for p in packs if p.created_at is not None]
    created_at = min(timestamps) if timestamps else None

    merged_extra: dict[str, Any] = {}
    for p in packs:
        for k, v in (p.extra or {}).items():
            merged_extra.setdefault(k, v)

    return ResearchPack(
        title=title,
        summary=summary,
        primary_url=_clean_url(primary_url) or None,
        sources=tuple(seen_sources.values()),
        tags=tuple(seen_tags.keys()),
        created_at=created_at,
        extra=merged_extra,
    )


def pack_with_extra_source(
    pack: ResearchPack,
    source: ResearchSource,
) -> ResearchPack:
    """Return a copy of *pack* with *source* appended (deduped by message_id+url)."""

    key = (
        source.message_id,
        source.thread_id,
        source.channel_id,
        _clean_url(source.source_url),
    )
    existing_keys = {
        (
            s.message_id,
            s.thread_id,
            s.channel_id,
            _clean_url(s.source_url),
        )
        for s in pack.sources
    }
    if key in existing_keys:
        return pack
    new_sources = tuple(pack.sources) + (source,)
    new_primary = pack.primary_url or _clean_url(source.source_url) or None
    return replace(pack, sources=new_sources, primary_url=new_primary)
