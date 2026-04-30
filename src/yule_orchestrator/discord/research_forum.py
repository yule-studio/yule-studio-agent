"""Adapter layer for the agent research Forum (`#운영-리서치`).

The hard work — actually creating threads and posting messages via
discord.py — is intentionally a *small* surface here (`create_research_post`
and `post_agent_comment`). Everything else (env config, body and comment
formatting, prefix detection) is **pure functions** so unit tests can
exercise them without spinning up Discord.

Operating rules: ``policies/runtime/agents/engineering-agent/research-forum.md``.
The forum is shared across departments; the env keys are
``DISCORD_AGENT_RESEARCH_FORUM_*`` (not ``DISCORD_ENGINEERING_*``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Awaitable, Iterable, Mapping, Optional

from ..agents.research_pack import ResearchAttachment, ResearchPack, ResearchSource


# ---------------------------------------------------------------------------
# Env config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResearchForumContext:
    """Resolved Forum channel target.

    Either ``channel_id`` or ``channel_name`` is enough to route. When both
    are missing, ``configured`` is False and forum publishing is disabled.
    """

    channel_id: Optional[int] = None
    channel_name: Optional[str] = None

    @property
    def configured(self) -> bool:
        return self.channel_id is not None or bool((self.channel_name or "").strip())

    @classmethod
    def from_env(cls) -> "ResearchForumContext":
        return cls(
            channel_id=_optional_int_env("DISCORD_AGENT_RESEARCH_FORUM_CHANNEL_ID"),
            channel_name=_optional_string_env(
                "DISCORD_AGENT_RESEARCH_FORUM_CHANNEL_NAME"
            ),
        )


# ---------------------------------------------------------------------------
# Prefix vocabulary (research-forum.md §3)
# ---------------------------------------------------------------------------


PREFIX_RESEARCH = "[Research]"
PREFIX_TOOL = "[Tool]"
PREFIX_REFERENCE = "[Reference]"
PREFIX_DECISION = "[Decision]"
PREFIX_OBSIDIAN = "[Obsidian]"

THREAD_TITLE_PREFIXES = (PREFIX_RESEARCH, PREFIX_TOOL, PREFIX_REFERENCE)
COMMENT_PREFIXES = (PREFIX_DECISION, PREFIX_OBSIDIAN)
ALL_PREFIXES = THREAD_TITLE_PREFIXES + COMMENT_PREFIXES


# ---------------------------------------------------------------------------
# Title / body / comment formatters (pure)
# ---------------------------------------------------------------------------


def normalize_thread_title(title: str, *, prefix: Optional[str] = None) -> str:
    """Ensure the thread title starts with one of the THREAD_TITLE_PREFIXES.

    If *title* already begins with a known thread prefix, returns it as-is.
    If *prefix* is given and *title* doesn't have one yet, prepends it.
    Otherwise defaults to ``[Research]``.
    """

    cleaned = (title or "").strip()
    if not cleaned:
        cleaned = "(untitled)"
    for known in ALL_PREFIXES:
        if cleaned.startswith(known):
            return cleaned
    chosen = prefix if prefix in THREAD_TITLE_PREFIXES else PREFIX_RESEARCH
    return f"{chosen} {cleaned}"


def format_research_post_body(
    pack: ResearchPack,
    *,
    posted_by: Optional[str] = None,
) -> str:
    """Render a ResearchPack as the body of a forum thread."""

    lines: list[str] = []
    if posted_by:
        lines.append(f"_posted by_ `{posted_by}`")
        lines.append("")
    if pack.summary:
        lines.append("**요약**")
        lines.append(pack.summary.strip())
        lines.append("")
    if pack.urls:
        lines.append("**자료 링크**")
        for url in pack.urls:
            lines.append(f"- {url}")
        lines.append("")
    attachments = pack.attachments
    if attachments:
        lines.append("**첨부**")
        for att in attachments:
            lines.append(_format_attachment_line(att))
        lines.append("")
    if pack.tags:
        lines.append(f"**태그** {' '.join(f'`{t}`' for t in pack.tags)}")
        lines.append("")
    sources = list(pack.sources)
    if len(sources) > 1:
        lines.append(f"**출처 {len(sources)}건**")
        for source in sources:
            lines.append(_format_source_line(source))
    elif sources:
        # When there's exactly one source, we still include provenance for
        # Obsidian export later — but compactly.
        only = sources[0]
        provenance = _format_source_line(only)
        if provenance.strip("- ").strip():
            lines.append("**출처**")
            lines.append(provenance)
    return "\n".join(line for line in lines).strip()


def format_agent_comment(
    *,
    role: str,
    collected_materials: Iterable[str] = (),
    interpretation: str = "",
    risks: str = "",
    next_actions: Iterable[str] = (),
    confidence: str = "medium",
    confidence_reason: str = "",
) -> str:
    """Render the standard role-review comment.

    Layout follows research-forum.md §4.1:
    ``역할 / 수집 자료 / 해석 / 리스크 / 다음 행동`` plus a trailing
    confidence line.  ``collected_materials`` and ``next_actions`` are
    rendered as numbered sub-lists; empty inputs degrade to a short
    fallback so a comment is never silent.
    """

    safe_role = role.strip() or "<unknown-role>"
    safe_conf = (confidence or "medium").strip().lower()
    if safe_conf not in {"high", "medium", "low"}:
        safe_conf = "medium"

    material_items = [m for m in (collected_materials or ()) if m and m.strip()]
    material_lines = (
        "\n".join(f"  {idx}. {item.strip()}" for idx, item in enumerate(material_items, start=1))
        if material_items
        else "  - 수집된 자료 없음 — 추가 조사 필요"
    )

    actions = [a for a in (next_actions or ()) if a and a.strip()]
    action_lines = (
        "\n".join(f"  {idx}. {action.strip()}" for idx, action in enumerate(actions, start=1))
        if actions
        else "  - 추가 행동 없음"
    )

    interpretation_text = interpretation.strip() or "(해석 미기재)"
    risk_text = risks.strip() or "특별한 리스크 없음"
    confidence_line = (
        f"신뢰도: {safe_conf}"
        + (f" — {confidence_reason.strip()}" if confidence_reason.strip() else "")
    )
    return (
        f"[role:{safe_role}]\n"
        f"- 역할: {safe_role}\n"
        f"- 수집 자료:\n"
        f"{material_lines}\n"
        f"- 해석: {interpretation_text}\n"
        f"- 리스크: {risk_text}\n"
        f"- 다음 행동:\n"
        f"{action_lines}\n"
        f"- {confidence_line}"
    )


def format_thread_markdown_fallback(
    pack: ResearchPack,
    *,
    title: Optional[str] = None,
    posted_by: Optional[str] = None,
    reason: Optional[str] = None,
) -> str:
    """Markdown blob for posting to a regular text channel when the
    forum endpoint is unavailable (no token / 403 / unconfigured).

    The shape mirrors a forum thread: H2 title, an optional warning
    line explaining why we're falling back, and the same body the
    forum thread would have carried.  Callers can pipe this directly
    into ``channel.send`` (split if it exceeds 2000 chars).
    """

    final_title = normalize_thread_title(title or pack.title)
    body = format_research_post_body(pack, posted_by=posted_by)
    notice_bits = ["⚠️ 운영-리서치 forum 게시에 실패했습니다 — 일반 thread markdown fallback."]
    if reason and reason.strip():
        notice_bits.append(f"사유: {reason.strip()}")
    notice = " ".join(notice_bits)

    parts: list[str] = [f"## {final_title}", f"_{notice}_"]
    if body:
        parts.append(body)
    return "\n\n".join(parts).strip()


def detect_thread_prefix(title: str) -> Optional[str]:
    """Return the matching thread prefix, or None if title has none."""

    cleaned = (title or "").strip()
    for known in ALL_PREFIXES:
        if cleaned.startswith(known):
            return known
    return None


# ---------------------------------------------------------------------------
# Discord-touching helpers (small)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ForumPostOutcome:
    posted: bool
    thread_id: Optional[int] = None
    thread_url: Optional[str] = None
    error: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None
    fallback_markdown: Optional[str] = None


@dataclass(frozen=True)
class ForumCommentOutcome:
    posted: bool
    message_id: Optional[int] = None
    error: Optional[str] = None
    body: Optional[str] = None


CreateThreadFn = Any  # Callable[[*, channel_id, name, content], Awaitable]
PostMessageFn = Any   # Callable[[*, thread_id, content], Awaitable]


async def create_research_post(
    pack: ResearchPack,
    *,
    forum_context: ResearchForumContext,
    create_thread_fn: CreateThreadFn,
    posted_by: Optional[str] = None,
    prefix: Optional[str] = None,
) -> ForumPostOutcome:
    """Compose title+body, hand them to *create_thread_fn*, return outcome.

    *create_thread_fn* is injected so production can wrap discord.py and
    tests can stub it. It is awaited with kwargs ``channel_id``, ``name``,
    ``content``, and is expected to return an object with ``id``/``url``
    or a Mapping-shaped result.
    """

    title = normalize_thread_title(pack.title, prefix=prefix)
    body = format_research_post_body(pack, posted_by=posted_by)

    if not forum_context.configured:
        reason = "forum channel not configured"
        return ForumPostOutcome(
            posted=False,
            error=reason,
            title=title,
            body=body,
            fallback_markdown=format_thread_markdown_fallback(
                pack,
                title=title,
                posted_by=posted_by,
                reason=reason,
            ),
        )

    try:
        result = await _maybe_await(
            create_thread_fn(
                channel_id=forum_context.channel_id,
                channel_name=forum_context.channel_name,
                name=title,
                content=body,
            )
        )
    except Exception as exc:  # noqa: BLE001 - surface to caller, do not crash
        return ForumPostOutcome(
            posted=False,
            error=str(exc),
            title=title,
            body=body,
            fallback_markdown=format_thread_markdown_fallback(
                pack,
                title=title,
                posted_by=posted_by,
                reason=str(exc),
            ),
        )

    thread_id = _extract_thread_id(result)
    thread_url = _extract_thread_url(result)
    return ForumPostOutcome(
        posted=True,
        thread_id=thread_id,
        thread_url=thread_url,
        title=title,
        body=body,
    )


async def post_agent_comment(
    *,
    thread_id: int,
    role: str,
    collected_materials: Iterable[str] = (),
    interpretation: str = "",
    risks: str = "",
    next_actions: Iterable[str] = (),
    confidence: str = "medium",
    confidence_reason: str = "",
    post_message_fn: PostMessageFn,
) -> ForumCommentOutcome:
    """Format the role review comment and post it via *post_message_fn*."""

    body = format_agent_comment(
        role=role,
        collected_materials=collected_materials,
        interpretation=interpretation,
        risks=risks,
        next_actions=next_actions,
        confidence=confidence,
        confidence_reason=confidence_reason,
    )
    try:
        result = await _maybe_await(
            post_message_fn(thread_id=thread_id, content=body)
        )
    except Exception as exc:  # noqa: BLE001
        return ForumCommentOutcome(posted=False, error=str(exc), body=body)
    message_id = _extract_message_id(result)
    return ForumCommentOutcome(posted=True, message_id=message_id, body=body)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _format_attachment_line(att: ResearchAttachment) -> str:
    parts = [f"`{att.kind}`"]
    if att.filename:
        parts.append(att.filename)
    parts.append(f"<{att.url}>")
    if att.description:
        parts.append(f"— {att.description}")
    return "- " + " ".join(parts)


def _format_source_line(source: ResearchSource) -> str:
    bits: list[str] = []
    if source.author_role:
        bits.append(f"`{source.author_role}`")
    if source.posted_at:
        bits.append(source.posted_at.isoformat())
    if source.source_url:
        bits.append(source.source_url)
    if not bits and (source.title or "").strip():
        bits.append(source.title.strip())
    if not bits:
        return "- (출처 미상)"
    return "- " + " · ".join(bits)


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


def _extract_thread_id(result: Any) -> Optional[int]:
    if result is None:
        return None
    if isinstance(result, Mapping):
        for key in ("id", "thread_id"):
            value = result.get(key)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None
        return None
    for attr in ("id", "thread_id"):
        value = getattr(result, attr, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


def _extract_thread_url(result: Any) -> Optional[str]:
    if result is None:
        return None
    if isinstance(result, Mapping):
        value = result.get("url") or result.get("jump_url")
    else:
        value = getattr(result, "jump_url", None) or getattr(result, "url", None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_message_id(result: Any) -> Optional[int]:
    return _extract_thread_id(result)


def _optional_int_env(name: str) -> Optional[int]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer value, got: {raw!r}") from exc


def _optional_string_env(name: str) -> Optional[str]:
    raw = os.environ.get(name)
    if raw is None:
        return None
    text = raw.strip()
    return text or None
