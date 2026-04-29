from __future__ import annotations

import sys

from .config import DiscordBotConfig
from .member_bots import GATEWAY_ROLE_KEY, MemberBotProfile


def run_member_bot(profile: MemberBotProfile) -> None:
    """Run a single member persona bot using its dedicated token.

    MVP behavior: log in, announce identity in stdout, sit idle. The
    department's outward-facing logic still lives in the gateway path.
    Member bots will eventually receive internal IPC messages from the
    gateway; for now their only job is to prove the token works and the
    persona is recognised in the guild.
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
            # Gateway handles all outward replies; member bots stay silent
            # until the dispatcher milestone wires internal IPC.
            return

    bot = MemberBot(command_prefix=commands.when_mentioned, intents=intents)
    print(
        f"starting member bot '{profile.display_label}' (gateway={GATEWAY_ROLE_KEY!r}, "
        f"guild={base_config.guild_id})",
        file=sys.stderr,
    )
    bot.run(profile.token)
