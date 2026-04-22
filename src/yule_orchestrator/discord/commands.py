from __future__ import annotations

from datetime import date, datetime

from discord import app_commands

from ..planning import build_daily_plan, collect_planning_inputs, select_due_checkpoints
from .formatter import format_checkpoints_message, format_plan_today_message, split_discord_message


def register_discord_commands(
    bot: "commands.Bot",
    guild_id: int,
    notify_user_id: int | None = None,
) -> None:
    import discord

    guild = discord.Object(id=guild_id)

    @bot.tree.command(name="ping", description="봇이 살아 있는지 확인합니다.", guild=guild)
    async def ping(interaction: discord.Interaction) -> None:
        await interaction.response.send_message("pong")

    @bot.tree.command(name="plan_today", description="오늘 Planning Agent 브리핑을 생성합니다.", guild=guild)
    @app_commands.describe(use_ollama="Ollama로 아침 브리핑을 더 자연스럽게 다듬을지 선택합니다.")
    async def plan_today(interaction: discord.Interaction, use_ollama: bool = False) -> None:
        await interaction.response.defer(thinking=True)
        plan_date = date.today()
        inputs = collect_planning_inputs(plan_date=plan_date)
        envelope = build_daily_plan(inputs, use_ollama=use_ollama)
        content = format_plan_today_message(
            envelope,
            mention_user_id=notify_user_id or interaction.user.id,
        )
        await _send_message_chunks(interaction, content)

    @bot.tree.command(name="checkpoints_now", description="지금 기준으로 다가오는 체크포인트를 보여줍니다.", guild=guild)
    @app_commands.describe(window_minutes="몇 분 앞까지 확인할지 설정합니다.")
    async def checkpoints_now(
        interaction: discord.Interaction,
        window_minutes: app_commands.Range[int, 1, 60] = 10,
    ) -> None:
        await interaction.response.defer(thinking=True)
        now = datetime.now().astimezone()
        plan_date = now.date()
        inputs = collect_planning_inputs(
            plan_date=plan_date,
            include_calendar=True,
            include_github=False,
            reminders=[],
        )
        envelope = build_daily_plan(inputs)
        due_checkpoints = select_due_checkpoints(
            envelope.daily_plan.checkpoints,
            at=now,
            window_minutes=window_minutes,
        )
        content = format_checkpoints_message(
            due_checkpoints,
            reference_time=now,
            mention_user_id=notify_user_id or interaction.user.id,
        )
        await _send_message_chunks(interaction, content)


async def _send_message_chunks(interaction: "discord.Interaction", message: str) -> None:
    chunks = split_discord_message(message)
    first_chunk, *remaining = chunks
    await interaction.followup.send(first_chunk)
    for chunk in remaining:
        await interaction.followup.send(chunk)
