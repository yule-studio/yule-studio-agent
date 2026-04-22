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
            register_discord_commands(self, guild_id=config.guild_id)
            guild = discord.Object(id=config.guild_id)
            await self.tree.sync(guild=guild)

        async def on_ready(self) -> None:
            user_text = str(self.user) if self.user is not None else "unknown-user"
            print(f"Discord bot logged in as {user_text} (guild={config.guild_id})")

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
