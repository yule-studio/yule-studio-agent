from __future__ import annotations

import sys

from .config import DiscordBotConfig
from .engineering_team_runtime import (
    TeamTurnOutcome,
    handle_team_turn_message,
)
from .member_bots import GATEWAY_ROLE_KEY, MemberBotProfile


def run_member_bot(profile: MemberBotProfile) -> None:
    """Run a single member persona bot using its dedicated token.

    Behavior:

    1. Log in and announce identity (still useful for ops).
    2. Listen for ``[team-turn:<session_id> <role>]`` dispatch directives in
       the channels/threads the bot can see. When the directive targets
       this role, the bot posts the role's scripted opening turn into the
       same channel and appends the next directive so the chain continues.

    The actual conversation logic lives in
    :mod:`engineering_team_runtime`; this function is the Discord wrapper.
    """

    if not profile.active:
        raise ValueError(
            f"{profile.env_key} is required to start {profile.display_label}. "
            f"Add it to .env.local before running this role bot."
        )

    import discord
    from discord.ext import commands

    base_config = DiscordBotConfig.from_env()
    intents = discord.Intents.default()
    intents.message_content = True
    intents.messages = True

    class MemberBot(commands.Bot):
        async def on_ready(self) -> None:
            user_text = str(self.user) if self.user is not None else "unknown-user"
            print(
                f"member bot '{profile.display_label}' logged in as {user_text} "
                f"(guild={base_config.guild_id})",
                file=sys.stderr,
            )

        async def on_message(self, message: "discord.Message") -> None:  # noqa: D401 - discord callback
            if message.author == self.user:
                return
            if profile.role == GATEWAY_ROLE_KEY:
                # Gateway bot has its own conversation handlers in bot.py;
                # never let the member-bot loop process gateway traffic.
                return

            outcome = handle_team_turn_message(
                role=profile.role,
                text=message.content or "",
            )
            if outcome is None:
                return

            await _post_team_turn(message.channel, outcome)

    bot = MemberBot(command_prefix=commands.when_mentioned, intents=intents)
    print(
        f"starting member bot '{profile.display_label}' (gateway={GATEWAY_ROLE_KEY!r}, "
        f"guild={base_config.guild_id})",
        file=sys.stderr,
    )
    bot.run(profile.token)


async def _post_team_turn(channel, outcome: TeamTurnOutcome) -> None:
    """Send the rendered turn (and chain directive, if any) into *channel*.

    Extracted so tests can drive the post path without a live Discord
    client. Splitting the message + directive into one ``send`` keeps the
    handoff visually grouped in the thread.
    """

    await channel.send(outcome.full_post())
