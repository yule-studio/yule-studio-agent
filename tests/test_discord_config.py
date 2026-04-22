from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

import os
import unittest
from unittest.mock import patch

from yule_orchestrator.discord.config import DiscordBotConfig


class DiscordConfigTestCase(unittest.TestCase):
    def test_from_env_reads_required_values(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DISCORD_BOT_TOKEN": "token-value",
                "DISCORD_GUILD_ID": "987654321",
                "DISCORD_DAILY_CHANNEL_ID": "555",
            },
            clear=False,
        ):
            config = DiscordBotConfig.from_env()

        self.assertEqual(config.token, "token-value")
        self.assertIsNone(config.application_id)
        self.assertEqual(config.guild_id, 987654321)
        self.assertEqual(config.daily_channel_id, 555)

    def test_from_env_reads_optional_application_id(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DISCORD_BOT_TOKEN": "token-value",
                "DISCORD_APPLICATION_ID": "123456789",
                "DISCORD_GUILD_ID": "987654321",
            },
            clear=False,
        ):
            config = DiscordBotConfig.from_env()

        self.assertEqual(config.application_id, 123456789)

    def test_from_env_requires_token(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DISCORD_BOT_TOKEN": "",
                "DISCORD_GUILD_ID": "987654321",
            },
            clear=False,
        ):
            with self.assertRaises(ValueError):
                DiscordBotConfig.from_env()
