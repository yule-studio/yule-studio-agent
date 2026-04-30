from __future__ import annotations

import unittest
from datetime import datetime, timedelta

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

from yule_orchestrator.agents.research_pack import (
    ResearchAttachment,
    ResearchPack,
    ResearchSource,
    dedup_urls,
    extract_urls,
    merge_packs,
    pack_from_discord_message,
    pack_with_extra_source,
)


class ExtractUrlsTestCase(unittest.TestCase):
    def test_finds_multiple(self) -> None:
        text = "참고: https://stripe.com/pricing 그리고 http://example.com/x?y=1, 끝"
        self.assertEqual(
            extract_urls(text),
            ("https://stripe.com/pricing", "http://example.com/x?y=1"),
        )

    def test_strips_trailing_punctuation(self) -> None:
        self.assertEqual(
            extract_urls("see (https://example.com/foo)."),
            ("https://example.com/foo",),
        )

    def test_dedup_within_text(self) -> None:
        text = "https://a.example/x and https://a.example/x"
        self.assertEqual(extract_urls(text), ("https://a.example/x",))

    def test_empty_text(self) -> None:
        self.assertEqual(extract_urls(""), ())
        self.assertEqual(extract_urls("그냥 평범한 문장"), ())


class DedupUrlsTestCase(unittest.TestCase):
    def test_preserves_first_seen_order(self) -> None:
        self.assertEqual(
            dedup_urls(["https://b", "https://a", "https://b"]),
            ("https://b", "https://a"),
        )

    def test_drops_none_and_empty(self) -> None:
        self.assertEqual(
            dedup_urls([None, "", " ", "https://x"]),
            ("https://x",),
        )

    def test_strips_trailing_punctuation(self) -> None:
        self.assertEqual(
            dedup_urls(["https://x).", "https://x;"]),
            ("https://x",),
        )


class PackFromDiscordMessageTestCase(unittest.TestCase):
    def test_extracts_primary_url(self) -> None:
        pack = pack_from_discord_message(
            title="Stripe Pricing 패턴",
            content="참고 https://stripe.com/pricing — hero 카피와 step copy",
            author_role="engineering-agent/product-designer",
            channel_id=111,
            thread_id=222,
            message_id=333,
        )
        self.assertEqual(pack.primary_url, "https://stripe.com/pricing")
        self.assertEqual(pack.urls, ("https://stripe.com/pricing",))
        self.assertEqual(len(pack.sources), 1)
        source = pack.sources[0]
        self.assertEqual(source.source_url, "https://stripe.com/pricing")
        self.assertEqual(source.author_role, "engineering-agent/product-designer")
        self.assertTrue(source.discord_origin)

    def test_no_url_yields_none_primary(self) -> None:
        pack = pack_from_discord_message(title="회의록", content="텍스트만 있음")
        self.assertIsNone(pack.primary_url)
        self.assertEqual(pack.urls, ())
        self.assertFalse(pack.sources[0].discord_origin)

    def test_attachments_round_trip(self) -> None:
        att = ResearchAttachment(kind="image", url="https://cdn/x.png", filename="x.png")
        pack = pack_from_discord_message(
            title="t",
            content="",
            attachments=[att],
        )
        self.assertEqual(pack.attachments, (att,))


class MergePacksTestCase(unittest.TestCase):
    def _pack(self, **kwargs) -> ResearchPack:
        defaults = dict(
            title="t",
            content="https://a.example",
        )
        defaults.update(kwargs)
        return pack_from_discord_message(**defaults)

    def test_unions_sources_and_urls(self) -> None:
        p1 = self._pack(title="A", content="https://a", message_id=1)
        p2 = self._pack(title="B", content="https://b", message_id=2)
        merged = merge_packs([p1, p2])
        self.assertEqual(set(merged.urls), {"https://a", "https://b"})
        self.assertEqual(len(merged.sources), 2)

    def test_dedup_same_message(self) -> None:
        p1 = self._pack(title="A", content="https://a", message_id=1, channel_id=10, thread_id=20)
        p2 = self._pack(title="A", content="https://a", message_id=1, channel_id=10, thread_id=20)
        merged = merge_packs([p1, p2])
        self.assertEqual(len(merged.sources), 1)

    def test_picks_first_non_untitled_title(self) -> None:
        p1 = pack_from_discord_message(title="(untitled)", content="x")
        p2 = pack_from_discord_message(title="Real Title", content="y")
        merged = merge_packs([p1, p2])
        self.assertEqual(merged.title, "Real Title")

    def test_uses_earliest_created_at(self) -> None:
        t0 = datetime(2026, 4, 30, 9, 0)
        t1 = datetime(2026, 4, 30, 10, 0)
        p_old = pack_from_discord_message(title="t", content="x", posted_at=t1)
        p_new = pack_from_discord_message(title="t", content="x", posted_at=t0)
        merged = merge_packs([p_old, p_new])
        self.assertEqual(merged.created_at, t0)

    def test_unions_tags_dedup(self) -> None:
        p1 = pack_from_discord_message(title="t", content="x", tags=["a", "b"])
        p2 = pack_from_discord_message(title="t", content="x", tags=["b", "c"])
        merged = merge_packs([p1, p2])
        self.assertEqual(set(merged.tags), {"a", "b", "c"})

    def test_empty_input_raises(self) -> None:
        with self.assertRaises(ValueError):
            merge_packs([])


class PackWithExtraSourceTestCase(unittest.TestCase):
    def test_appends_new_source(self) -> None:
        pack = pack_from_discord_message(title="t", content="https://a", message_id=1)
        extra = ResearchSource(source_url="https://b", message_id=2)
        result = pack_with_extra_source(pack, extra)
        self.assertEqual(len(result.sources), 2)
        self.assertIn("https://b", result.urls)

    def test_no_dup_when_same_message(self) -> None:
        pack = pack_from_discord_message(title="t", content="https://a", message_id=1, channel_id=10)
        same = ResearchSource(source_url="https://a", message_id=1, channel_id=10, title=None)
        result = pack_with_extra_source(pack, same)
        self.assertEqual(len(result.sources), 1)

    def test_sets_primary_url_when_none(self) -> None:
        pack = pack_from_discord_message(title="t", content="텍스트만")
        self.assertIsNone(pack.primary_url)
        extra = ResearchSource(source_url="https://x", message_id=99)
        result = pack_with_extra_source(pack, extra)
        self.assertEqual(result.primary_url, "https://x")


class AuthorRolesTestCase(unittest.TestCase):
    def test_unions_roles_dedup(self) -> None:
        p1 = pack_from_discord_message(
            title="t", content="x", author_role="engineering-agent/tech-lead", message_id=1
        )
        p2 = pack_from_discord_message(
            title="t",
            content="y",
            author_role="engineering-agent/backend-engineer",
            message_id=2,
        )
        p3 = pack_from_discord_message(
            title="t", content="z", author_role="engineering-agent/tech-lead", message_id=3
        )
        merged = merge_packs([p1, p2, p3])
        self.assertEqual(
            set(merged.author_roles),
            {"engineering-agent/tech-lead", "engineering-agent/backend-engineer"},
        )


class AttachmentDedupTestCase(unittest.TestCase):
    def test_attachments_dedup_across_sources(self) -> None:
        att = ResearchAttachment(kind="image", url="https://cdn/x.png")
        s1 = ResearchSource(source_url="https://a", attachments=(att,))
        s2 = ResearchSource(source_url="https://b", attachments=(att,))
        pack = ResearchPack(
            title="t",
            sources=(s1, s2),
        )
        self.assertEqual(len(pack.attachments), 1)


if __name__ == "__main__":
    unittest.main()
