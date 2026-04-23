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
            if config.daily_channel_id is not None and config.daily_briefing_time is not None:
                self._daily_briefing_task = asyncio.create_task(self._run_daily_briefing_loop())
            if config.effective_checkpoint_channel_id is not None:
                self._checkpoint_prefetch_task = asyncio.create_task(self._run_checkpoint_prefetch_loop())
                self._checkpoint_notification_task = asyncio.create_task(
                    self._run_checkpoint_notification_loop()
                )

        async def on_ready(self) -> None:
            user_text = str(self.user) if self.user is not None else "unknown-user"
            print(f"Discord bot logged in as {user_text} (guild={config.guild_id})")
            for message in _startup_messages(config, now=datetime.now().astimezone()):
                print(message)

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
            if config.daily_channel_id is None:
                return

            channel = await _resolve_messageable_channel(
                self,
                channel_id=config.daily_channel_id,
                discord_module=discord,
                error_label="DISCORD_DAILY_CHANNEL_ID",
            )
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
                    channel_id=config.daily_channel_id,
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
                channel_id=config.daily_channel_id,
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
            if channel_id is None:
                return
            if scan_time <= last_scan:
                return

            channel = await _resolve_messageable_channel(
                self,
                channel_id=channel_id,
                discord_module=discord,
                error_label=_checkpoint_channel_error_label(config),
            )
            async with self._checkpoint_lock():
                due_checkpoints = await asyncio.to_thread(
                    _resolve_due_checkpoints,
                    last_scan,
                    scan_time,
                )
                unsent_checkpoints = await asyncio.to_thread(
                    _filter_unsent_checkpoints,
                    channel_id,
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
                    channel_id,
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

    messages.extend(_channel_configuration_warnings(config))

    if config.daily_briefing_time is not None and config.daily_channel_id is None:
        messages.append(
            "warning: DISCORD_DAILY_BRIEFING_TIME is set but DISCORD_DAILY_CHANNEL_ID is missing. "
            "Scheduled daily briefings will not run."
        )
    elif config.daily_briefing_time is None and config.daily_channel_id is not None:
        messages.append(
            "warning: DISCORD_DAILY_CHANNEL_ID is set but DISCORD_DAILY_BRIEFING_TIME is missing. "
            "Scheduled daily briefings will not run."
        )
    elif config.daily_briefing_time is not None and config.daily_channel_id is not None:
        next_run = _next_daily_run(config.daily_briefing_time)
        messages.append(
            "info: daily briefing enabled "
            f"(channel={config.daily_channel_id}, next_run={next_run.isoformat()})"
        )

    checkpoint_channel_id = config.effective_checkpoint_channel_id
    if checkpoint_channel_id is not None:
        next_run = _next_checkpoint_scan(after=now)
        messages.append(
            "info: checkpoint notifications enabled "
            f"(channel={checkpoint_channel_id}, prefetch_minutes={config.checkpoint_prefetch_minutes}, "
            f"next_scan={next_run.isoformat()})"
        )
    else:
        messages.append("info: checkpoint notifications disabled")

    if config.notify_user_id is not None:
        messages.append(f"info: Discord notifications will mention user {config.notify_user_id}")
    else:
        messages.append("info: Discord notifications will be sent without a user mention")

    return messages


def _channel_configuration_warnings(config: DiscordBotConfig) -> list[str]:
    if config.application_id is None:
        return []

    warnings = []
    configured_channels = [
        ("DISCORD_DAILY_CHANNEL_ID", config.daily_channel_id),
        ("DISCORD_CHECKPOINT_CHANNEL_ID", config.checkpoint_channel_id),
    ]
    for label, channel_id in configured_channels:
        if channel_id is not None and channel_id == config.application_id:
            warnings.append(
                f"warning: {label} looks like DISCORD_APPLICATION_ID. "
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
    channel_id: int,
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
    channel_id: int,
    discord_module: "discord",
    error_label: str,
) -> "discord.abc.Messageable":
    channel = bot.get_channel(channel_id)
    if channel is None:
        channel = await bot.fetch_channel(channel_id)

    if not isinstance(channel, discord_module.abc.Messageable):
        raise ValueError(f"Configured {error_label} is not a messageable channel.")

    return channel


async def _send_channel_message_chunks(
    channel: "discord.abc.Messageable",
    message: str,
    *,
    allowed_mentions: "discord.AllowedMentions",
) -> None:
    for chunk in split_discord_message(message):
        await channel.send(chunk, allowed_mentions=allowed_mentions)


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
