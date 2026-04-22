from __future__ import annotations

from datetime import date
import unittest

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401
from yule_orchestrator.integrations.calendar.cache import build_calendar_cache_key, resolve_calendar_cache_ttl_seconds
from yule_orchestrator.integrations.calendar.models import build_fallback_item_uid


class CalendarCachePolicyTestCase(unittest.TestCase):
    def test_current_range_uses_short_ttl(self) -> None:
        ttl = resolve_calendar_cache_ttl_seconds(
            start_date=date(2026, 4, 22),
            end_date=date(2026, 4, 22),
            configured_ttl_seconds=None,
            today=date(2026, 4, 22),
        )
        self.assertEqual(ttl, 300)

    def test_future_range_uses_medium_ttl(self) -> None:
        ttl = resolve_calendar_cache_ttl_seconds(
            start_date=date(2026, 4, 25),
            end_date=date(2026, 4, 26),
            configured_ttl_seconds=None,
            today=date(2026, 4, 22),
        )
        self.assertEqual(ttl, 1800)

    def test_past_range_uses_long_ttl(self) -> None:
        ttl = resolve_calendar_cache_ttl_seconds(
            start_date=date(2026, 4, 20),
            end_date=date(2026, 4, 20),
            configured_ttl_seconds=None,
            today=date(2026, 4, 22),
        )
        self.assertEqual(ttl, 86400)

    def test_configured_ttl_wins(self) -> None:
        ttl = resolve_calendar_cache_ttl_seconds(
            start_date=date(2026, 4, 20),
            end_date=date(2026, 4, 20),
            configured_ttl_seconds=42,
            today=date(2026, 4, 22),
        )
        self.assertEqual(ttl, 42)

    def test_cache_key_normalization_avoids_delimiter_collisions(self) -> None:
        left = build_calendar_cache_key("a", "b::c")
        right = build_calendar_cache_key("a::b", "c")

        self.assertNotEqual(left, right)

    def test_fallback_item_uid_normalization_avoids_delimiter_collisions(self) -> None:
        left = build_fallback_item_uid("todo", "a", "b::c")
        right = build_fallback_item_uid("todo", "a::b", "c")

        self.assertNotEqual(left, right)
