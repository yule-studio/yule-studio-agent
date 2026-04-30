"""Routing logic for the engineering #업무-접수 channel.

The Discord bot's planning conversation layer is preserved as-is; this
router handles the *engineering* path: free conversation in the intake
channel (or a thread under it), and — when the user signals confirmation
— a workflow intake plus a thread kickoff message.

The module is pure-Python: all I/O dependencies (engineering conversation
provider, workflow intake, thread kickoff, message sender) are injected
as callables so unit tests can drive the router without spinning up
discord.py. ``bot.py`` wires the production callables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Union


# Single-source confirmation lexicon; the engineering conversation layer
# may also detect intent and pre-set ``confirmed=True`` itself, in which
# case the router trusts that signal.
_CONFIRMATION_KEYWORDS: tuple[str, ...] = (
    "확정",
    "진행",
    "시작해",
    "시작하자",
    "시작할게",
    "시작합시다",
    "고고",
    "ㄱㄱ",
    "ㄱㄱㄱ",
    "맞아 진행",
    "그대로 진행",
    "그대로 가",
    "오케이 진행",
    "오케 진행",
    "go ahead",
    "let's go",
    "lets go",
    "kick off",
    "kickoff",
    "proceed",
    "approve and start",
)


@dataclass(frozen=True)
class EngineeringRouteContext:
    """Where the engineering intake channel lives.

    Both ``intake_channel_id`` and ``intake_channel_name`` are optional
    individually — if either one matches the message channel (or its
    parent, for a thread), the message is treated as engineering.
    """

    intake_channel_id: Optional[int] = None
    intake_channel_name: Optional[str] = None

    @property
    def configured(self) -> bool:
        return self.intake_channel_id is not None or bool(
            _normalize_channel_name(self.intake_channel_name)
        )

    @classmethod
    def from_env(cls) -> "EngineeringRouteContext":
        return cls(
            intake_channel_id=_optional_int_env("DISCORD_ENGINEERING_INTAKE_CHANNEL_ID"),
            intake_channel_name=_optional_string_env(
                "DISCORD_ENGINEERING_INTAKE_CHANNEL_NAME"
            ),
        )


@dataclass(frozen=True)
class EngineeringConversationOutcome:
    """The shape returned by the engineering free-conversation layer.

    ``confirmed=True`` means the user just expressed intent to start
    a real intake; ``intake_prompt`` is the canonicalised request for
    the workflow.  The conversation layer is free to omit those fields
    — the router falls back to a keyword-based confirmation check on
    the original user text.
    """

    content: str
    confirmed: bool = False
    intake_prompt: Optional[str] = None
    write_requested: bool = False
    thread_topic: Optional[str] = None


@dataclass(frozen=True)
class EngineeringThreadKickoff:
    """Result of creating a working thread and posting kickoff."""

    thread_id: Optional[int] = None
    message: Optional[str] = None


@dataclass(frozen=True)
class EngineeringRouteResult:
    """What the router did with one Discord message.

    ``handled=False`` means this message is *not* an engineering channel
    message; the bot should fall through to its planning conversation
    path.  ``handled=True`` means the router has already replied (and
    optionally created an intake/thread), so the bot must not double-reply.
    """

    handled: bool
    conversation_message: Optional[str] = None
    intake_message: Optional[str] = None
    kickoff_message: Optional[str] = None
    session_id: Optional[str] = None
    thread_id: Optional[int] = None
    error: Optional[str] = None


SendChunksFn = Callable[[Any, str], Awaitable[None]]
ExtractPromptFn = Callable[..., str]
ConversationFn = Callable[..., Union[
    EngineeringConversationOutcome,
    Awaitable[EngineeringConversationOutcome],
    str,
    Awaitable[str],
]]
IntakeFn = Callable[..., Any]
ThreadKickoffFn = Callable[..., Awaitable[EngineeringThreadKickoff]]


def is_engineering_channel(
    *,
    message: Any,
    route_context: EngineeringRouteContext,
) -> bool:
    if not route_context.configured:
        return False

    channel = getattr(message, "channel", None)
    if channel is None:
        return False

    channel_id = getattr(channel, "id", None)
    parent = getattr(channel, "parent", None)
    parent_id = getattr(parent, "id", None) or getattr(channel, "parent_id", None)
    channel_name = _normalize_channel_name(getattr(channel, "name", None))
    parent_name = _normalize_channel_name(getattr(parent, "name", None))

    target_id = route_context.intake_channel_id
    target_name = _normalize_channel_name(route_context.intake_channel_name)

    if target_id is not None:
        if channel_id is not None and channel_id == target_id:
            return True
        if parent_id is not None and parent_id == target_id:
            return True
    if target_name:
        if channel_name == target_name:
            return True
        if parent_name == target_name:
            return True
    return False


def detect_confirmation_signal(text: str) -> bool:
    """Heuristic confirmation detector used when the conversation layer
    does not pre-classify intent.  Matches Korean and English go-ahead
    phrases conservatively — short ack words like ``yes``/``네`` are
    excluded so casual chat isn't promoted to a workflow intake."""

    if not text:
        return False
    normalized = " ".join(text.lower().split())
    if not normalized:
        return False
    return any(keyword in normalized for keyword in _CONFIRMATION_KEYWORDS)


async def route_engineering_message(
    *,
    message: Any,
    bot_user: Any,
    route_context: EngineeringRouteContext,
    extract_prompt: ExtractPromptFn,
    conversation_fn: ConversationFn,
    intake_fn: IntakeFn,
    thread_kickoff_fn: ThreadKickoffFn,
    send_chunks: SendChunksFn,
) -> EngineeringRouteResult:
    """Drive the engineering channel response.

    Order:
      1. If the message is not in an engineering channel, return ``handled=False``.
      2. Call the conversation layer; reply with whatever it produced.
      3. If the conversation (or fallback heuristic) says the user just
         confirmed, call ``intake_fn`` to create a workflow session.
      4. Post the intake summary, then kick off a thread.
    """

    if not is_engineering_channel(message=message, route_context=route_context):
        return EngineeringRouteResult(handled=False)

    prompt_text = extract_prompt(message=message, bot_user=bot_user)
    prompt_text = (prompt_text or "").strip()
    if not prompt_text:
        return EngineeringRouteResult(handled=False)

    raw_outcome = await _maybe_await(
        conversation_fn(
            message_text=prompt_text,
            author_user_id=getattr(message.author, "id", None),
            channel_id=getattr(getattr(message, "channel", None), "id", None),
            bot_user=bot_user,
        )
    )
    outcome = _coerce_outcome(raw_outcome, prompt_text=prompt_text)

    if outcome.content:
        await send_chunks(message.channel, outcome.content)

    confirmed = outcome.confirmed or detect_confirmation_signal(prompt_text)
    intake_prompt = (outcome.intake_prompt or prompt_text).strip()
    if not confirmed or not intake_prompt:
        return EngineeringRouteResult(
            handled=True,
            conversation_message=outcome.content or None,
        )

    try:
        intake = intake_fn(
            prompt=intake_prompt,
            write_requested=outcome.write_requested,
            channel_id=getattr(getattr(message, "channel", None), "id", None),
            user_id=getattr(getattr(message, "author", None), "id", None),
        )
        intake = await _maybe_await(intake)
    except Exception as exc:  # noqa: BLE001 - surface error to user, do not crash bot
        error_text = f"⚠️ engineer intake 실패: {exc}"
        await send_chunks(message.channel, error_text)
        return EngineeringRouteResult(
            handled=True,
            conversation_message=outcome.content or None,
            error=str(exc),
        )

    intake_message = getattr(intake, "message", None)
    session = getattr(intake, "session", None)
    plan = getattr(intake, "plan", None)
    session_id = getattr(session, "session_id", None)

    if intake_message:
        await send_chunks(message.channel, intake_message)

    kickoff_message: Optional[str] = None
    thread_id: Optional[int] = None
    kickoff_error: Optional[str] = None
    try:
        kickoff = await thread_kickoff_fn(
            channel=message.channel,
            session=session,
            plan=plan,
            topic=outcome.thread_topic,
        )
    except Exception as exc:  # noqa: BLE001 - intake already saved, just note kickoff issue
        kickoff_error = str(exc)
        await send_chunks(
            message.channel,
            f"⚠️ thread kickoff 실패: {exc}\n세션 `{session_id or '?'}` 은 이미 생성되어 있습니다.",
        )
    else:
        if kickoff is not None:
            thread_id = kickoff.thread_id
            kickoff_message = kickoff.message

    return EngineeringRouteResult(
        handled=True,
        conversation_message=outcome.content or None,
        intake_message=intake_message,
        kickoff_message=kickoff_message,
        session_id=session_id,
        thread_id=thread_id,
        error=kickoff_error,
    )


def _coerce_outcome(
    raw: Any,
    *,
    prompt_text: str,
) -> EngineeringConversationOutcome:
    if isinstance(raw, EngineeringConversationOutcome):
        return raw
    if isinstance(raw, str):
        return EngineeringConversationOutcome(content=raw)
    # Allow the conversation layer to ship a custom dataclass with a
    # compatible ``content`` attribute.  We extract the optional fields
    # defensively so tomorrow's API additions don't break us today.
    content = str(getattr(raw, "content", "") or "")
    confirmed = bool(getattr(raw, "confirmed", False))
    intake_prompt_raw = getattr(raw, "intake_prompt", None)
    intake_prompt = (
        str(intake_prompt_raw).strip()
        if intake_prompt_raw is not None
        else None
    )
    write_requested = bool(getattr(raw, "write_requested", False))
    thread_topic_raw = getattr(raw, "thread_topic", None)
    thread_topic = (
        str(thread_topic_raw).strip()
        if thread_topic_raw is not None
        else None
    )
    return EngineeringConversationOutcome(
        content=content,
        confirmed=confirmed,
        intake_prompt=intake_prompt or None,
        write_requested=write_requested,
        thread_topic=thread_topic or None,
    )


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


def extract_message_attachments(message: Any) -> tuple[Any, ...]:
    """Return the message's attachments as a stable tuple, discord.py-agnostic.

    discord.py exposes ``message.attachments`` as a list of ``Attachment``
    objects, but tests pass plain dataclasses or dicts. We accept any iterable
    and drop ``None`` entries so the engineering conversation layer can rely
    on a clean sequence regardless of the Discord shape.
    """

    raw = getattr(message, "attachments", None)
    if raw is None:
        return ()
    if isinstance(raw, (list, tuple)):
        return tuple(item for item in raw if item is not None)
    try:
        return tuple(item for item in raw if item is not None)
    except TypeError:
        return ()


def _normalize_channel_name(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip().lstrip("#").lower()


def _optional_int_env(name: str) -> Optional[int]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    value = raw.strip()
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be an integer value, got: {value!r}"
        ) from exc


def _optional_string_env(name: str) -> Optional[str]:
    raw = os.environ.get(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None
