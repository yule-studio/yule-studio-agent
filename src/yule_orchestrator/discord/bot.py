from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
from pathlib import Path

from ..planning import build_daily_plan, collect_planning_inputs
from .commands import register_discord_commands
from .config import DiscordBotConfig
from .formatter import format_plan_today_message, split_discord_message


def run_discord_bot(repo_root: Path) -> None:
    import discord
    from discord.ext import commands

    config = DiscordBotConfig.from_env()

    class YuleDiscordBot(commands.Bot):
        def __init__(self) -> None:
            intents = discord.Intents.default()
            self._daily_briefing_task: asyncio.Task[None] | None = None
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
            if config.daily_channel_id is not None and config.daily_briefing_time is not None:
                self._daily_briefing_task = asyncio.create_task(self._run_daily_briefing_loop())

        async def on_ready(self) -> None:
            user_text = str(self.user) if self.user is not None else "unknown-user"
            print(f"Discord bot logged in as {user_text} (guild={config.guild_id})")

        async def close(self) -> None:
            if self._daily_briefing_task is not None:
                self._daily_briefing_task.cancel()
                try:
                    await self._daily_briefing_task
                except asyncio.CancelledError:
                    pass
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

            channel = self.get_channel(config.daily_channel_id)
            if channel is None:
                channel = await self.fetch_channel(config.daily_channel_id)

            if not isinstance(channel, discord.abc.Messageable):
                raise ValueError("Configured DISCORD_DAILY_CHANNEL_ID is not a messageable channel.")

            plan_date = datetime.now().astimezone().date()
            inputs = collect_planning_inputs(plan_date=plan_date)
            envelope = build_daily_plan(inputs)
            content = format_plan_today_message(
                envelope,
                mention_user_id=config.notify_user_id,
            )
            for chunk in split_discord_message(content):
                await channel.send(chunk)

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
