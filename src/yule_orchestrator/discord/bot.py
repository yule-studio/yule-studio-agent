from __future__ import annotations

import asyncio
import math
import time as time_module
from datetime import datetime, time, timedelta
from pathlib import Path

from ..observability import RuntimeStepMetric, save_runtime_metric_run
from ..planning.models import PlanningCheckpoint
from ..storage import load_json_cache, save_json_cache
from .commands import register_discord_commands
from .conversation import build_conversation_response
from .config import DiscordBotConfig
from .formatter import (
    format_checkpoints_message,
    format_missing_plan_snapshot_message,
    format_plan_today_message,
    split_discord_message,
)
from .planning_runtime import build_due_checkpoints, load_plan_today_snapshot
from .planning_runtime import load_prefetched_due_checkpoints, prefetch_checkpoint_snapshots

CHECKPOINT_NOTIFICATION_NAMESPACE = "discord-checkpoint-notifications"
CHECKPOINT_NOTIFICATION_TTL_SECONDS = 2 * 24 * 60 * 60


def run_discord_bot(repo_root: Path) -> None:
    import discord
    from discord.ext import commands

    config = DiscordBotConfig.from_env()

    class YuleDiscordBot(commands.Bot):
        def __init__(self) -> None:
            intents = discord.Intents.default()
            intents.message_content = True
            intents.messages = True
            self._daily_briefing_task: asyncio.Task[None] | None = None
            self._checkpoint_notification_task: asyncio.Task[None] | None = None
            self._checkpoint_prefetch_task: asyncio.Task[None] | None = None
            self._checkpoint_storage_lock: asyncio.Lock | None = None
            super().__init__(
                command_prefix=commands.when_mentioned,
                intents=intents,
            )

        async def setup_hook(self) -> None:
            actual_application_id = self.application_id
            if (
                config.application_id is not None
                and actual_application_id is not None
                and config.application_id != actual_application_id
            ):
                print(
                    "warning: DISCORD_APPLICATION_ID does not match the bot token's application. "
                    f"configured={config.application_id}, actual={actual_application_id}. "
                    "The token-linked application will be used."
                )
            register_discord_commands(
                self,
                guild_id=config.guild_id,
                notify_user_id=config.notify_user_id,
            )
            guild = discord.Object(id=config.guild_id)
            await self.tree.sync(guild=guild)
            self._checkpoint_storage_lock = asyncio.Lock()
            if config.daily_briefing_time is not None and (
                config.daily_channel_id is not None or config.daily_channel_name is not None
            ):
                self._daily_briefing_task = asyncio.create_task(self._run_daily_briefing_loop())
            if (
                config.effective_checkpoint_channel_id is not None
                or config.effective_checkpoint_channel_name is not None
            ):
                self._checkpoint_prefetch_task = asyncio.create_task(self._run_checkpoint_prefetch_loop())
                self._checkpoint_notification_task = asyncio.create_task(
                    self._run_checkpoint_notification_loop()
                )

        async def on_ready(self) -> None:
            user_text = str(self.user) if self.user is not None else "unknown-user"
            print(f"Discord bot logged in as {user_text} (guild={config.guild_id})")
            for message in _startup_messages(config, now=datetime.now().astimezone()):
                print(message)

        async def on_message(self, message: "discord.Message") -> None:
            if message.author.bot:
                return
            if message.guild is None or message.guild.id != config.guild_id:
                return
            if self.user is None:
                return
            if not _should_handle_message(
                message=message,
                bot_user=self.user,
                conversation_channel_id=config.effective_conversation_channel_id,
                conversation_channel_name=config.effective_conversation_channel_name,
            ):
                return

            prompt = _extract_conversation_prompt(message=message, bot_user=self.user).strip()
            if not prompt:
                prompt = "오늘 뭐부터 해야 해?"

            async with message.channel.typing():
                content = await asyncio.to_thread(
                    build_conversation_response,
                    prompt,
                    author_user_id=message.author.id,
                    mention_user=_message_mentions_bot(message=message, bot_user=self.user),
                )

            await _send_channel_message_chunks(
                message.channel,
                content,
                allowed_mentions=_build_allowed_mentions(discord),
            )

        async def close(self) -> None:
            await _cancel_task(self._daily_briefing_task)
            await _cancel_task(self._checkpoint_prefetch_task)
            await _cancel_task(self._checkpoint_notification_task)
            await super().close()

        async def _run_daily_briefing_loop(self) -> None:
            await self.wait_until_ready()
            while not self.is_closed():
                next_run = _next_daily_run(config.daily_briefing_time)
                wait_seconds = max(1.0, (next_run - datetime.now().astimezone()).total_seconds())
                await asyncio.sleep(wait_seconds)
                try:
                    await self._send_daily_briefing()
                except Exception as exc:
                    print(f"warning: failed to send scheduled daily briefing: {exc}")

        async def _send_daily_briefing(self) -> None:
            if config.daily_channel_id is None and config.daily_channel_name is None:
                return

            channel = await _resolve_messageable_channel(
                self,
                guild_id=config.guild_id,
                channel_id=config.daily_channel_id,
                channel_name=config.daily_channel_name,
                discord_module=discord,
                error_label="DISCORD_DAILY_CHANNEL_ID",
            )
            resolved_channel_id = getattr(channel, "id", None) or config.daily_channel_id
            plan_date = datetime.now().astimezone().date()
            snapshot = await asyncio.to_thread(load_plan_today_snapshot, plan_date)
            if snapshot is None:
                content = format_missing_plan_snapshot_message(
                    mention_user_id=config.notify_user_id,
                )
            else:
                content = format_plan_today_message(
                    snapshot.envelope,
                    mention_user_id=config.notify_user_id,
                    snapshot=snapshot,
                )
            send_started_at = datetime.now().astimezone()
            send_started = time_module.perf_counter()
            try:
                await _send_channel_message_chunks(
                    channel,
                    content,
                    allowed_mentions=_build_allowed_mentions(discord),
                )
            except Exception as exc:
                _save_discord_send_metric(
                    workflow="discord-daily-briefing",
                    started_at=send_started_at,
                    duration_seconds=time_module.perf_counter() - send_started,
                    ok=False,
                    channel_id=resolved_channel_id,
                    message_count=len(split_discord_message(content)),
                    snapshot_state=_snapshot_state_label(snapshot),
                    error=str(exc),
                )
                raise

            _save_discord_send_metric(
                workflow="discord-daily-briefing",
                started_at=send_started_at,
                duration_seconds=time_module.perf_counter() - send_started,
                ok=True,
                channel_id=resolved_channel_id,
                message_count=len(split_discord_message(content)),
                snapshot_state=_snapshot_state_label(snapshot),
            )

        async def _run_checkpoint_notification_loop(self) -> None:
            await self.wait_until_ready()
            last_scan = datetime.now().astimezone()
            while not self.is_closed():
                next_run = _next_checkpoint_scan()
                wait_seconds = max(1.0, (next_run - datetime.now().astimezone()).total_seconds())
                await asyncio.sleep(wait_seconds)
                scan_time = datetime.now().astimezone()
                try:
                    await self._send_due_checkpoints(last_scan=last_scan, scan_time=scan_time)
                except Exception as exc:
                    print(f"warning: failed to send checkpoint notifications: {exc}")
                last_scan = scan_time

        async def _run_checkpoint_prefetch_loop(self) -> None:
            await self.wait_until_ready()
            while not self.is_closed():
                started_at = datetime.now().astimezone()
                try:
                    async with self._checkpoint_lock():
                        await asyncio.to_thread(
                            prefetch_checkpoint_snapshots,
                            started_at,
                            prefetch_minutes=config.checkpoint_prefetch_minutes,
                        )
                except Exception as exc:
                    print(f"warning: failed to prefetch checkpoint snapshots: {exc}")

                next_run = _next_checkpoint_scan(after=started_at)
                wait_seconds = max(1.0, (next_run - datetime.now().astimezone()).total_seconds())
                await asyncio.sleep(wait_seconds)

        async def _send_due_checkpoints(
            self,
            *,
            last_scan: datetime,
            scan_time: datetime,
        ) -> None:
            channel_id = config.effective_checkpoint_channel_id
            channel_name = config.effective_checkpoint_channel_name
            if channel_id is None and channel_name is None:
                return
            if scan_time <= last_scan:
                return

            channel = await _resolve_messageable_channel(
                self,
                guild_id=config.guild_id,
                channel_id=channel_id,
                channel_name=channel_name,
                discord_module=discord,
                error_label=_checkpoint_channel_error_label(config),
            )
            resolved_channel_id = getattr(channel, "id", None) or channel_id or 0
            async with self._checkpoint_lock():
                due_checkpoints = await asyncio.to_thread(
                    _resolve_due_checkpoints,
                    last_scan,
                    scan_time,
                )
                unsent_checkpoints = await asyncio.to_thread(
                    _filter_unsent_checkpoints,
                    resolved_channel_id,
                    due_checkpoints,
                )
            if not unsent_checkpoints:
                return

            content = format_checkpoints_message(
                unsent_checkpoints,
                reference_time=scan_time,
                mention_user_id=config.notify_user_id,
            )
            await _send_channel_message_chunks(
                channel,
                content,
                allowed_mentions=_build_allowed_mentions(discord),
            )
            async with self._checkpoint_lock():
                await asyncio.to_thread(
                    _mark_checkpoints_sent,
                    resolved_channel_id,
                    unsent_checkpoints,
                )

        def _checkpoint_lock(self) -> asyncio.Lock:
            if self._checkpoint_storage_lock is None:
                self._checkpoint_storage_lock = asyncio.Lock()
            return self._checkpoint_storage_lock

    bot = YuleDiscordBot()
    try:
        bot.run(config.token)
    except discord.LoginFailure as exc:
        raise ValueError(
            "Discord bot token login failed. Check DISCORD_BOT_TOKEN in .env.local and regenerate the token if needed."
        ) from exc
    except discord.NotFound as exc:
        error_code = getattr(exc, "code", None)
        if error_code == 10002:
            raise ValueError(
                "Discord application could not be found while syncing slash commands. "
                "Remove DISCORD_APPLICATION_ID or update it to match the bot token's application."
            ) from exc
        if error_code == 10004:
            raise ValueError(
                "Discord guild could not be found. Check DISCORD_GUILD_ID and make sure the bot was invited to that server."
            ) from exc
        raise


def _next_daily_run(target_time: time | None) -> datetime:
    if target_time is None:
        raise ValueError("daily briefing time is required for scheduling.")

    now = datetime.now().astimezone()
    next_run = now.replace(
        hour=target_time.hour,
        minute=target_time.minute,
        second=0,
        microsecond=0,
    )
    if next_run <= now:
        next_run = next_run + timedelta(days=1)
    return next_run


def _startup_messages(config: DiscordBotConfig, *, now: datetime) -> list[str]:
    messages: list[str] = []
    daily_channel_configured = config.daily_channel_id is not None or config.daily_channel_name is not None

    messages.extend(_channel_configuration_warnings(config))

    if config.daily_briefing_time is not None and not daily_channel_configured:
        messages.append(
            "warning: DISCORD_DAILY_BRIEFING_TIME is set but DISCORD_DAILY_CHANNEL_ID or DISCORD_DAILY_CHANNEL_NAME is missing. "
            "Scheduled daily briefings will not run."
        )
    elif config.daily_briefing_time is None and daily_channel_configured:
        messages.append(
            "warning: DISCORD_DAILY_CHANNEL_ID or DISCORD_DAILY_CHANNEL_NAME is set but DISCORD_DAILY_BRIEFING_TIME is missing. "
            "Scheduled daily briefings will not run."
        )
    elif config.daily_briefing_time is not None and daily_channel_configured:
        next_run = _next_daily_run(config.daily_briefing_time)
        messages.append(
            "info: daily briefing enabled "
            f"({_channel_target_text(config.daily_channel_id, config.daily_channel_name)}, next_run={next_run.isoformat()})"
        )

    checkpoint_channel_id = config.effective_checkpoint_channel_id
    checkpoint_channel_name = config.effective_checkpoint_channel_name
    if checkpoint_channel_id is not None or checkpoint_channel_name is not None:
        next_run = _next_checkpoint_scan(after=now)
        messages.append(
            "info: checkpoint notifications enabled "
            f"({_channel_target_text(checkpoint_channel_id, checkpoint_channel_name)}, "
            f"prefetch_minutes={config.checkpoint_prefetch_minutes}, "
            f"next_scan={next_run.isoformat()})"
        )
    else:
        messages.append("info: checkpoint notifications disabled")

    if config.notify_user_id is not None:
        messages.append(f"info: Discord notifications will mention user {config.notify_user_id}")
    else:
        messages.append("info: Discord notifications will be sent without a user mention")

    if config.effective_conversation_channel_id is not None or config.effective_conversation_channel_name is not None:
        messages.append(
            "info: conversation replies enabled "
            f"({_channel_target_text(config.effective_conversation_channel_id, config.effective_conversation_channel_name)}, "
            "mode=plain-message-or-mention)"
        )
    else:
        messages.append("info: conversation replies enabled in mention-only mode")

    return messages


def _channel_configuration_warnings(config: DiscordBotConfig) -> list[str]:
    warnings = []
    configured_channels = [
        ("DISCORD_DAILY_CHANNEL_ID", config.daily_channel_id),
        ("DISCORD_CHECKPOINT_CHANNEL_ID", config.checkpoint_channel_id),
        ("DISCORD_CONVERSATION_CHANNEL_ID", config.conversation_channel_id),
    ]
    for label, channel_id in configured_channels:
        if config.application_id is not None and channel_id is not None and channel_id == config.application_id:
            warnings.append(
                f"warning: {label} looks like DISCORD_APPLICATION_ID. "
                "Use the target Discord text channel id instead."
            )
        if channel_id is not None and channel_id == config.guild_id:
            warnings.append(
                f"warning: {label} looks like DISCORD_GUILD_ID. "
                "Use the target Discord text channel id instead."
            )
    return warnings


def _next_checkpoint_scan(after: datetime | None = None) -> datetime:
    current = after or datetime.now().astimezone()
    rounded = current.replace(second=0, microsecond=0)
    if rounded <= current:
        rounded = rounded + timedelta(minutes=1)
    return rounded


def _checkpoint_channel_error_label(config: DiscordBotConfig) -> str:
    if config.checkpoint_channel_id is not None:
        return "DISCORD_CHECKPOINT_CHANNEL_ID"
    return "DISCORD_DAILY_CHANNEL_ID"


def _save_discord_send_metric(
    *,
    workflow: str,
    started_at: datetime,
    duration_seconds: float,
    ok: bool,
    channel_id: int | None,
    message_count: int,
    snapshot_state: str,
    error: str | None = None,
) -> None:
    ended_at = datetime.now().astimezone()
    step = RuntimeStepMetric(
        name="discord_send",
        duration_seconds=duration_seconds,
        ok=ok,
        started_at=started_at.isoformat(),
        ended_at=ended_at.isoformat(),
        metadata={
            "channel_id": channel_id,
            "message_count": message_count,
            "snapshot_state": snapshot_state,
        },
        error=error,
    )
    save_runtime_metric_run(
        workflow=workflow,
        started_at=started_at,
        ended_at=ended_at,
        steps=[step],
        metadata={
            "channel_id": channel_id,
            "snapshot_state": snapshot_state,
        },
    )


def _snapshot_state_label(snapshot: object | None) -> str:
    if snapshot is None:
        return "missing"
    is_stale = getattr(snapshot, "is_stale", False)
    return "stale" if is_stale else "fresh"


async def _cancel_task(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def _resolve_messageable_channel(
    bot: "commands.Bot",
    *,
    guild_id: int,
    channel_id: int | None,
    channel_name: str | None,
    discord_module: "discord",
    error_label: str,
) -> "discord.abc.Messageable":
    channel = None
    if channel_id is not None:
        channel = bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(channel_id)
            except Exception:
                channel = None

    if channel is None and channel_name:
        channel = await _find_messageable_channel_by_name(
            bot,
            guild_id=guild_id,
            channel_name=channel_name,
            discord_module=discord_module,
        )

    if not isinstance(channel, discord_module.abc.Messageable):
        target_text = _channel_target_text(channel_id, channel_name)
        raise ValueError(f"Configured {error_label} could not be resolved to a messageable channel ({target_text}).")

    return channel


async def _find_messageable_channel_by_name(
    bot: "commands.Bot",
    *,
    guild_id: int,
    channel_name: str,
    discord_module: "discord",
) -> "discord.abc.Messageable | None":
    normalized_target = _normalize_channel_name(channel_name)
    guild = bot.get_guild(guild_id)

    channels = []
    if guild is not None:
        channels.extend(getattr(guild, "channels", []) or [])
        fetch_channels = getattr(guild, "fetch_channels", None)
        if not channels and callable(fetch_channels):
            try:
                channels.extend(await fetch_channels())
            except Exception:
                pass

    if not channels:
        channels.extend(
            channel
            for channel in bot.get_all_channels()
            if getattr(getattr(channel, "guild", None), "id", None) == guild_id
        )

    for channel in channels:
        if _normalize_channel_name(getattr(channel, "name", None)) != normalized_target:
            continue
        if isinstance(channel, discord_module.abc.Messageable):
            return channel

    return None


async def _send_channel_message_chunks(
    channel: "discord.abc.Messageable",
    message: str,
    *,
    allowed_mentions: "discord.AllowedMentions",
) -> None:
    for chunk in split_discord_message(message):
        await channel.send(chunk, allowed_mentions=allowed_mentions)


def _should_handle_message(
    *,
    message: object,
    bot_user: object,
    conversation_channel_id: int | None,
    conversation_channel_name: str | None,
) -> bool:
    content = str(getattr(message, "content", "") or "").strip()
    if content.startswith("/"):
        return False

    channel = getattr(message, "channel", None)
    channel_id = getattr(channel, "id", None)
    parent = getattr(channel, "parent", None)
    parent_id = getattr(parent, "id", None) or getattr(channel, "parent_id", None)
    channel_name = getattr(channel, "name", None)
    parent_name = getattr(parent, "name", None)

    if conversation_channel_id is not None and channel_id == conversation_channel_id:
        return True
    if conversation_channel_id is not None and parent_id == conversation_channel_id:
        return True
    if _normalize_channel_name(conversation_channel_name) and (
        _normalize_channel_name(channel_name) == _normalize_channel_name(conversation_channel_name)
        or _normalize_channel_name(parent_name) == _normalize_channel_name(conversation_channel_name)
    ):
        return True

    return _message_mentions_bot(message=message, bot_user=bot_user)


def _extract_conversation_prompt(*, message: object, bot_user: object) -> str:
    content = str(getattr(message, "content", "") or "")
    bot_id = getattr(bot_user, "id", None)
    bot_name = str(getattr(bot_user, "name", "") or "").strip()

    if bot_id is not None:
        content = content.replace(f"<@{bot_id}>", " ")
        content = content.replace(f"<@!{bot_id}>", " ")
    if bot_name:
        content = content.replace(f"@{bot_name}", " ")

    return " ".join(content.split())


def _message_mentions_bot(*, message: object, bot_user: object) -> bool:
    mentions = getattr(message, "mentions", None) or []
    bot_id = getattr(bot_user, "id", None)
    return any(getattr(user, "id", None) == bot_id for user in mentions)


def _build_allowed_mentions(discord_module: "discord") -> "discord.AllowedMentions":
    return discord_module.AllowedMentions(
        users=True,
        roles=False,
        everyone=False,
        replied_user=False,
    )


def _checkpoint_window_minutes(window_start: datetime, window_end: datetime) -> int:
    total_seconds = max(0.0, (window_end - window_start).total_seconds())
    return max(1, math.ceil(total_seconds / 60.0))


def _resolve_due_checkpoints(window_start: datetime, window_end: datetime) -> list[PlanningCheckpoint]:
    prefetched_checkpoints, cache_complete = load_prefetched_due_checkpoints(window_start, window_end)
    if cache_complete:
        return prefetched_checkpoints

    return build_due_checkpoints(
        window_start,
        window_minutes=_checkpoint_window_minutes(window_start, window_end),
    )


def _filter_unsent_checkpoints(
    channel_id: int,
    checkpoints: list[PlanningCheckpoint],
) -> list[PlanningCheckpoint]:
    return [
        checkpoint
        for checkpoint in checkpoints
        if not _has_checkpoint_been_sent(channel_id, checkpoint.checkpoint_id)
    ]


def _mark_checkpoints_sent(channel_id: int, checkpoints: list[PlanningCheckpoint]) -> None:
    for checkpoint in checkpoints:
        save_json_cache(
            namespace=CHECKPOINT_NOTIFICATION_NAMESPACE,
            cache_key=_checkpoint_cache_key(channel_id, checkpoint.checkpoint_id),
            provider="discord-bot",
            range_start=None,
            range_end=None,
            scope_hash=str(channel_id),
            ttl_seconds=CHECKPOINT_NOTIFICATION_TTL_SECONDS,
            payload={
                "channel_id": channel_id,
                "checkpoint_id": checkpoint.checkpoint_id,
                "remind_at": checkpoint.remind_at,
            },
            metadata={"kind": checkpoint.kind},
        )


def _has_checkpoint_been_sent(channel_id: int, checkpoint_id: str) -> bool:
    entry = load_json_cache(
        namespace=CHECKPOINT_NOTIFICATION_NAMESPACE,
        cache_key=_checkpoint_cache_key(channel_id, checkpoint_id),
        touch=False,
    )
    return entry is not None


def _checkpoint_cache_key(channel_id: int, checkpoint_id: str) -> str:
    return f"{channel_id}:{checkpoint_id}"


def _normalize_channel_name(value: object | None) -> str:
    if value is None:
        return ""
    return str(value).strip().lstrip("#").lower()


def _channel_target_text(channel_id: int | None, channel_name: str | None) -> str:
    parts = []
    if channel_id is not None:
        parts.append(f"channel_id={channel_id}")
    if channel_name:
        parts.append(f"channel_name={channel_name}")
    return ", ".join(parts) if parts else "channel=unconfigured"
