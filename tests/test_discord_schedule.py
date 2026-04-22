from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

from datetime import datetime, time, timedelta
import unittest
from unittest.mock import patch

from yule_orchestrator.discord.bot import _next_daily_run


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
