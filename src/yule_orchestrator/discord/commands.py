from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any

from .formatter import (
    format_checkpoints_message,
    format_missing_plan_snapshot_message,
    format_plan_today_message,
    split_discord_message,
)
from .planning_runtime import build_due_checkpoints, load_plan_today_snapshot


def register_discord_commands(
    bot: "commands.Bot",
    guild_id: int,
    notify_user_id: int | None = None,
) -> None:
    import discord
    from discord import app_commands

    _bind_discord_runtime_globals(discord_module=discord, app_commands_module=app_commands)
    guild = discord.Object(id=guild_id)
    allowed_mentions = _build_allowed_mentions(discord)

    @bot.tree.command(name="ping", description="봇이 살아 있는지 확인합니다.", guild=guild)
    async def ping(interaction: discord.Interaction) -> None:
        await interaction.response.send_message("pong")

    @bot.tree.command(name="plan_today", description="저장된 오늘 daily-plan snapshot을 보여줍니다.", guild=guild)
    async def plan_today(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        plan_date = date.today()
        snapshot = await asyncio.to_thread(load_plan_today_snapshot, plan_date)
        if snapshot is None:
            content = format_missing_plan_snapshot_message(
                mention_user_id=notify_user_id or interaction.user.id,
            )
        else:
            content = format_plan_today_message(
                snapshot.envelope,
                mention_user_id=notify_user_id or interaction.user.id,
                snapshot=snapshot,
            )
        await _send_message_chunks(
            interaction,
            content,
            allowed_mentions=allowed_mentions,
        )

    @bot.tree.command(name="checkpoints_now", description="지금 기준으로 다가오는 체크포인트를 보여줍니다.", guild=guild)
    @app_commands.describe(window_minutes="몇 분 앞까지 확인할지 설정합니다.")
    async def checkpoints_now(
        interaction: discord.Interaction,
        window_minutes: app_commands.Range[int, 1, 60] = 10,
    ) -> None:
        await interaction.response.defer(thinking=True)
        now = datetime.now().astimezone()
        due_checkpoints = await asyncio.to_thread(
            build_due_checkpoints,
            now,
            window_minutes=window_minutes,
        )
        content = format_checkpoints_message(
            due_checkpoints,
            reference_time=now,
            mention_user_id=notify_user_id or interaction.user.id,
        )
        await _send_message_chunks(
            interaction,
            content,
            allowed_mentions=allowed_mentions,
        )


def _bind_discord_runtime_globals(*, discord_module: Any, app_commands_module: Any) -> None:
    globals()["discord"] = discord_module
    globals()["app_commands"] = app_commands_module


def _build_allowed_mentions(discord_module: Any) -> Any:
    return discord_module.AllowedMentions(
        users=True,
        roles=False,
        everyone=False,
        replied_user=False,
    )


async def _send_message_chunks(
    interaction: "discord.Interaction",
    message: str,
    *,
    allowed_mentions: Any,
) -> None:
    chunks = split_discord_message(message)
    first_chunk, *remaining = chunks
    await interaction.followup.send(first_chunk, allowed_mentions=allowed_mentions)
    for chunk in remaining:
        await interaction.followup.send(chunk, allowed_mentions=allowed_mentions)
