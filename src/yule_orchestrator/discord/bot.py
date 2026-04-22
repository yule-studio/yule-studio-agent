from __future__ import annotations

from pathlib import Path

from .commands import register_discord_commands
from .config import DiscordBotConfig


def run_discord_bot(repo_root: Path) -> None:
    import discord
    from discord.ext import commands

    config = DiscordBotConfig.from_env()

    class YuleDiscordBot(commands.Bot):
        def __init__(self) -> None:
            intents = discord.Intents.default()
            super().__init__(
                command_prefix="!",
                intents=intents,
                application_id=config.application_id,
            )

        async def setup_hook(self) -> None:
            register_discord_commands(self, guild_id=config.guild_id)
            guild = discord.Object(id=config.guild_id)
            await self.tree.sync(guild=guild)

        async def on_ready(self) -> None:
            user_text = str(self.user) if self.user is not None else "unknown-user"
            print(f"Discord bot logged in as {user_text} (guild={config.guild_id})")

    bot = YuleDiscordBot()
    bot.run(config.token)
