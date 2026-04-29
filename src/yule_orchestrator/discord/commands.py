from __future__ import annotations

import asyncio
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from ..agents import (
    Dispatcher,
    TaskType,
    WorkflowError,
    WorkflowOrchestrator,
    build_participants_pool,
)
from .formatter import (
    format_checkpoints_message,
    format_plan_today_message,
    format_snapshot_regenerating_message,
    format_snapshot_regeneration_failed_message,
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
        if not await _safe_defer(interaction, discord_module=discord):
            return
        plan_date = date.today()
        recipient_mention = notify_user_id or interaction.user.id
        snapshot = await asyncio.to_thread(load_plan_today_snapshot, plan_date)

        if snapshot is None:
            ack = format_snapshot_regenerating_message(
                mention_user_id=recipient_mention,
                slot_title="오늘 브리핑",
            )
            await _send_message_chunks(
                interaction,
                ack,
                allowed_mentions=allowed_mentions,
                discord_module=discord,
            )
            ensure_snapshot = getattr(bot, "ensure_snapshot", None)
            if ensure_snapshot is None:
                fail = format_snapshot_regeneration_failed_message(
                    mention_user_id=recipient_mention,
                    error="snapshot 자동 재생성 기능을 찾지 못했습니다.",
                )
                await _send_message_chunks(
                    interaction,
                    fail,
                    allowed_mentions=allowed_mentions,
                    discord_module=discord,
                )
                return
            snapshot, error = await ensure_snapshot(plan_date)
            if snapshot is None:
                fail = format_snapshot_regeneration_failed_message(
                    mention_user_id=recipient_mention,
                    error=error,
                )
                await _send_message_chunks(
                    interaction,
                    fail,
                    allowed_mentions=allowed_mentions,
                    discord_module=discord,
                )
                return

        content = format_plan_today_message(
            snapshot.envelope,
            mention_user_id=recipient_mention,
            snapshot=snapshot,
        )
        await _send_message_chunks(
            interaction,
            content,
            allowed_mentions=allowed_mentions,
            discord_module=discord,
        )

    @bot.tree.command(
        name="engineer_intake",
        description="engineering-agent에게 작업을 위임합니다 (접수 메시지를 채널에 게시).",
        guild=guild,
    )
    @app_commands.describe(
        prompt="자연어 작업 요청.",
        task_type="명시 task type (생략 시 키워드 분류).",
        write_requested="이 작업이 코드/문서 쓰기를 요구하는지 여부.",
    )
    async def engineer_intake(
        interaction: "discord.Interaction",
        prompt: str,
        task_type: Optional[str] = None,
        write_requested: bool = False,
    ) -> None:
        if not await _safe_defer(interaction, discord_module=discord):
            return
        try:
            result = await asyncio.to_thread(
                _run_engineer_intake,
                prompt=prompt,
                task_type=task_type,
                write_requested=write_requested,
                channel_id=interaction.channel_id,
                user_id=interaction.user.id,
            )
        except (WorkflowError, ValueError) as exc:
            await _send_message_chunks(
                interaction,
                f"engineer intake 실패: {exc}",
                allowed_mentions=allowed_mentions,
                discord_module=discord,
            )
            return
        await _send_message_chunks(
            interaction,
            result.message,
            allowed_mentions=allowed_mentions,
            discord_module=discord,
        )

    @bot.tree.command(
        name="engineer_show",
        description="engineering-agent 워크플로 세션 상태를 조회합니다.",
        guild=guild,
    )
    @app_commands.describe(session_id="조회할 워크플로 세션 id.")
    async def engineer_show(
        interaction: "discord.Interaction",
        session_id: str,
    ) -> None:
        if not await _safe_defer(interaction, discord_module=discord):
            return
        try:
            session = await asyncio.to_thread(_load_engineer_session, session_id=session_id)
        except (WorkflowError, ValueError) as exc:
            await _send_message_chunks(
                interaction,
                f"engineer show 실패: {exc}",
                allowed_mentions=allowed_mentions,
                discord_module=discord,
            )
            return
        if session is None:
            await _send_message_chunks(
                interaction,
                f"session `{session_id}` 을 찾을 수 없습니다.",
                allowed_mentions=allowed_mentions,
                discord_module=discord,
            )
            return
        summary = (
            f"**[engineering-agent] 세션 상태**\n"
            f"세션 ID: `{session.session_id}`\n"
            f"상태: {session.state.value}\n"
            f"분류: {session.task_type}\n"
            f"실행자: {session.executor_role} ({session.executor_runner or '?'})"
        )
        if session.write_blocked_reason:
            summary += f"\n승인 대기: {session.write_blocked_reason}"
        await _send_message_chunks(
            interaction,
            summary,
            allowed_mentions=allowed_mentions,
            discord_module=discord,
        )

    @bot.tree.command(name="checkpoints_now", description="지금 기준으로 다가오는 체크포인트를 보여줍니다.", guild=guild)
    @app_commands.describe(window_minutes="몇 분 앞까지 확인할지 설정합니다.")
    async def checkpoints_now(
        interaction: discord.Interaction,
        window_minutes: app_commands.Range[int, 1, 60] = 10,
    ) -> None:
        if not await _safe_defer(interaction, discord_module=discord):
            return
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
            discord_module=discord,
        )


def _engineer_orchestrator() -> WorkflowOrchestrator:
    repo_root = Path(os.environ.get("YULE_REPO_ROOT", ".")).resolve()
    pool = build_participants_pool(repo_root, "engineering-agent")
    return WorkflowOrchestrator(Dispatcher(pool))


def _run_engineer_intake(
    *,
    prompt: str,
    task_type: Optional[str],
    write_requested: bool,
    channel_id: Optional[int],
    user_id: Optional[int],
):
    parsed: Optional[TaskType] = None
    if task_type:
        try:
            parsed = TaskType(task_type)
        except ValueError as exc:
            raise ValueError(
                f"task_type must be one of {[t.value for t in TaskType]}, got {task_type!r}"
            ) from exc
    orchestrator = _engineer_orchestrator()
    return orchestrator.intake(
        prompt=prompt,
        task_type=parsed,
        write_requested=write_requested,
        channel_id=channel_id,
        user_id=user_id,
    )


def _load_engineer_session(*, session_id: str):
    orchestrator = _engineer_orchestrator()
    return orchestrator.get(session_id)


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


async def _safe_defer(
    interaction: "discord.Interaction",
    *,
    discord_module: Any,
) -> bool:
    try:
        await interaction.response.defer(thinking=True)
    except discord_module.NotFound:
        print(
            "warning: discord interaction expired before defer could complete "
            f"(command={getattr(interaction.command, 'name', 'unknown')}, "
            f"user_id={getattr(interaction.user, 'id', 'unknown')})"
        )
        return False
    return True


async def _send_message_chunks(
    interaction: "discord.Interaction",
    message: str,
    *,
    allowed_mentions: Any,
    discord_module: Any,
) -> None:
    chunks = split_discord_message(message)
    first_chunk, *remaining = chunks
    try:
        await interaction.followup.send(first_chunk, allowed_mentions=allowed_mentions)
        for chunk in remaining:
            await interaction.followup.send(chunk, allowed_mentions=allowed_mentions)
    except discord_module.NotFound:
        print(
            "warning: discord interaction webhook expired before followup could be delivered "
            f"(command={getattr(interaction.command, 'name', 'unknown')}, "
            f"user_id={getattr(interaction.user, 'id', 'unknown')})"
        )
