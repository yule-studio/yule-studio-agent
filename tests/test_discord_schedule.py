from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

from datetime import datetime, time, timedelta
import unittest
from unittest.mock import patch

from yule_orchestrator.discord.bot import _next_daily_run, _startup_messages
from yule_orchestrator.discord.config import DiscordBotConfig


class DiscordScheduleTestCase(unittest.TestCase):
    def test_next_daily_run_returns_same_day_when_future_time(self) -> None:
        fake_now = datetime.fromisoformat("2026-04-22T15:10:00+09:00")

        class FakeDateTime:
            @staticmethod
            def now():
                return fake_now

        with patch("yule_orchestrator.discord.bot.datetime", FakeDateTime):
            next_run = _next_daily_run(time(16, 15))

        self.assertEqual(next_run, fake_now.replace(hour=16, minute=15, second=0, microsecond=0))

    def test_next_daily_run_rolls_to_next_day_when_time_passed(self) -> None:
        fake_now = datetime.fromisoformat("2026-04-22T16:20:00+09:00")

        class FakeDateTime:
            @staticmethod
            def now():
                return fake_now

        with patch("yule_orchestrator.discord.bot.datetime", FakeDateTime):
            next_run = _next_daily_run(time(16, 15))

        expected = fake_now.replace(hour=16, minute=15, second=0, microsecond=0) + timedelta(days=1)
        self.assertEqual(next_run, expected)

    def test_startup_messages_warn_when_daily_channel_is_missing(self) -> None:
        fake_now = datetime.fromisoformat("2026-04-22T16:20:00+09:00")
        config = DiscordBotConfig(
            token="token",
            application_id=None,
            guild_id=123,
            daily_channel_id=None,
            daily_channel_name=None,
            checkpoint_channel_id=None,
            checkpoint_channel_name=None,
            conversation_channel_id=None,
            conversation_channel_name=None,
            notify_user_id=None,
            daily_briefing_time=time(17, 30),
            checkpoint_prefetch_minutes=5,
        )

        messages = _startup_messages(config, now=fake_now)

        self.assertTrue(
            any(
                "DISCORD_DAILY_BRIEFING_TIME is set but DISCORD_DAILY_CHANNEL_ID or DISCORD_DAILY_CHANNEL_NAME is missing"
                in message
                for message in messages
            )
        )
        self.assertIn("info: checkpoint notifications disabled", messages)

    def test_startup_messages_describe_enabled_schedules(self) -> None:
        fake_now = datetime.fromisoformat("2026-04-22T16:20:00+09:00")
        config = DiscordBotConfig(
            token="token",
            application_id=None,
            guild_id=123,
            daily_channel_id=456,
            daily_channel_name="planning",
            checkpoint_channel_id=789,
            checkpoint_channel_name="checkpoints",
            conversation_channel_id=654,
            conversation_channel_name="planning-chat",
            notify_user_id=999,
            daily_briefing_time=time(17, 30),
            checkpoint_prefetch_minutes=7,
        )

        messages = _startup_messages(config, now=fake_now)

        self.assertTrue(any("daily briefing enabled" in message for message in messages))
        self.assertTrue(any("channel_id=456" in message for message in messages))
        self.assertTrue(any("checkpoint notifications enabled" in message for message in messages))
        self.assertTrue(any("channel_id=789" in message for message in messages))
        self.assertIn("info: Discord notifications will mention user 999", messages)
        self.assertIn(
            "info: conversation replies enabled (channel_id=654, channel_name=planning-chat, mode=plain-message-or-mention)",
            messages,
        )

    def test_startup_messages_warn_when_channel_id_looks_like_application_id(self) -> None:
        fake_now = datetime.fromisoformat("2026-04-22T16:20:00+09:00")
        config = DiscordBotConfig(
            token="token",
            application_id=456,
            guild_id=123,
            daily_channel_id=456,
            daily_channel_name=None,
            checkpoint_channel_id=None,
            checkpoint_channel_name=None,
            conversation_channel_id=None,
            conversation_channel_name=None,
            notify_user_id=None,
            daily_briefing_time=time(17, 30),
            checkpoint_prefetch_minutes=5,
        )

        messages = _startup_messages(config, now=fake_now)

        self.assertTrue(
            any("DISCORD_DAILY_CHANNEL_ID looks like DISCORD_APPLICATION_ID" in message for message in messages)
        )

    def test_startup_messages_warn_when_channel_id_looks_like_guild_id(self) -> None:
        fake_now = datetime.fromisoformat("2026-04-22T16:20:00+09:00")
        config = DiscordBotConfig(
            token="token",
            application_id=None,
            guild_id=123,
            daily_channel_id=123,
            daily_channel_name=None,
            checkpoint_channel_id=None,
            checkpoint_channel_name=None,
            conversation_channel_id=None,
            conversation_channel_name=None,
            notify_user_id=None,
            daily_briefing_time=time(17, 30),
            checkpoint_prefetch_minutes=5,
        )

        messages = _startup_messages(config, now=fake_now)

        self.assertTrue(
            any("DISCORD_DAILY_CHANNEL_ID looks like DISCORD_GUILD_ID" in message for message in messages)
        )
