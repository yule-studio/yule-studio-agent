from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

import os
from datetime import time
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
                "DISCORD_DAILY_CHANNEL_NAME": "planning",
                "DISCORD_CONVERSATION_CHANNEL_ID": "666",
                "DISCORD_CONVERSATION_CHANNEL_NAME": "chat-bot",
                "DISCORD_NOTIFY_USER_ID": "777",
                "DISCORD_DAILY_BRIEFING_TIME": "16:15",
            },
            clear=False,
        ):
            config = DiscordBotConfig.from_env()

        self.assertEqual(config.token, "token-value")
        self.assertIsNone(config.application_id)
        self.assertEqual(config.guild_id, 987654321)
        self.assertEqual(config.daily_channel_id, 555)
        self.assertEqual(config.daily_channel_name, "planning")
        self.assertEqual(config.conversation_channel_id, 666)
        self.assertEqual(config.conversation_channel_name, "chat-bot")
        self.assertEqual(config.effective_conversation_channel_id, 666)
        self.assertEqual(config.effective_conversation_channel_name, "chat-bot")
        self.assertIsNone(config.checkpoint_channel_id)
        self.assertEqual(config.effective_checkpoint_channel_id, 555)
        self.assertEqual(config.effective_checkpoint_channel_name, "planning")
        self.assertEqual(config.notify_user_id, 777)
        self.assertEqual(config.daily_briefing_time, time(16, 15))
        self.assertEqual(config.checkpoint_prefetch_minutes, 5)

    def test_from_env_reads_optional_application_id(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DISCORD_BOT_TOKEN": "token-value",
                "DISCORD_APPLICATION_ID": "123456789",
                "DISCORD_GUILD_ID": "987654321",
                "DISCORD_DAILY_CHANNEL_NAME": "planning",
                "DISCORD_CHECKPOINT_CHANNEL_ID": "222333444",
                "DISCORD_CHECKPOINT_CHANNEL_NAME": "checkpoints",
                "DISCORD_CHECKPOINT_PREFETCH_MINUTES": "7",
            },
            clear=False,
        ):
            config = DiscordBotConfig.from_env()

        self.assertEqual(config.application_id, 123456789)
        self.assertEqual(config.daily_channel_name, "planning")
        self.assertEqual(config.checkpoint_channel_id, 222333444)
        self.assertEqual(config.checkpoint_channel_name, "checkpoints")
        self.assertEqual(config.effective_checkpoint_channel_id, 222333444)
        self.assertEqual(config.effective_checkpoint_channel_name, "checkpoints")
        self.assertEqual(config.effective_conversation_channel_id, None)
        self.assertEqual(config.effective_conversation_channel_name, "planning")
        self.assertEqual(config.checkpoint_prefetch_minutes, 7)

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

    def test_from_env_rejects_invalid_daily_briefing_time(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DISCORD_BOT_TOKEN": "token-value",
                "DISCORD_GUILD_ID": "987654321",
                "DISCORD_DAILY_BRIEFING_TIME": "25:99",
            },
            clear=False,
        ):
            with self.assertRaises(ValueError):
                DiscordBotConfig.from_env()

    def test_from_env_rejects_invalid_checkpoint_prefetch_minutes(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DISCORD_BOT_TOKEN": "token-value",
                "DISCORD_GUILD_ID": "987654321",
                "DISCORD_CHECKPOINT_PREFETCH_MINUTES": "0",
            },
            clear=False,
        ):
            with self.assertRaises(ValueError):
                DiscordBotConfig.from_env()
