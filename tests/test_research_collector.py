from __future__ import annotations

import os
import unittest
from unittest.mock import patch

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

from yule_orchestrator.agents.research_collector import (
    BraveSearchCollector,
    CollectionMode,
    CollectionOutcome,
    CollectorConfig,
    CollectorQuery,
    DEFAULT_MAX_RESULTS,
    ENV_AUTO_COLLECT_ENABLED,
    ENV_BRAVE_API_KEY,
    ENV_MAX_RESULTS,
    ENV_PROVIDER,
    ENV_TAVILY_API_KEY,
    MockSearchCollector,
    NoOpCollector,
    PROVIDER_BRAVE,
    PROVIDER_MOCK,
    PROVIDER_TAVILY,
    ProviderUnavailable,
    ResearchCollector,
    TavilySearchCollector,
    auto_collect_or_request_more_input,
    build_collector,
    build_query_for_role,
    collect_research_pack,
    extract_domain,
    format_collection_summary,
    short_role,
)
from yule_orchestrator.agents.research_pack import (
    ResearchAttachment,
    SourceType,
)


def _env(**overrides) -> dict:
    base = {k: v for k, v in os.environ.items() if not k.startswith("ENGINEERING_RESEARCH_")
            and k not in {ENV_TAVILY_API_KEY, ENV_BRAVE_API_KEY}}
    base.update({k: v for k, v in overrides.items() if v is not None})
    return base


# ---------------------------------------------------------------------------
# CollectorConfig
# ---------------------------------------------------------------------------


class CollectorConfigTestCase(unittest.TestCase):
    def test_defaults_when_env_blank(self) -> None:
        with patch.dict(os.environ, _env(), clear=True):
            cfg = CollectorConfig.from_env()
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.provider, PROVIDER_MOCK)
        self.assertEqual(cfg.max_results, DEFAULT_MAX_RESULTS)
        self.assertIsNone(cfg.api_key)

    def test_truthy_enabled_values(self) -> None:
        for raw in ("1", "true", "TRUE", "yes", "on"):
            with self.subTest(raw=raw):
                with patch.dict(
                    os.environ, _env(**{ENV_AUTO_COLLECT_ENABLED: raw}), clear=True
                ):
                    cfg = CollectorConfig.from_env()
                self.assertTrue(cfg.enabled)

    def test_unknown_provider_falls_back_to_mock(self) -> None:
        with patch.dict(
            os.environ,
            _env(
                **{
                    ENV_AUTO_COLLECT_ENABLED: "true",
                    ENV_PROVIDER: "made-up",
                }
            ),
            clear=True,
        ):
            cfg = CollectorConfig.from_env()
        self.assertEqual(cfg.provider, PROVIDER_MOCK)

    def test_max_results_invalid_uses_default(self) -> None:
        with patch.dict(
            os.environ,
            _env(**{ENV_AUTO_COLLECT_ENABLED: "true", ENV_MAX_RESULTS: "abc"}),
            clear=True,
        ):
            cfg = CollectorConfig.from_env()
        self.assertEqual(cfg.max_results, DEFAULT_MAX_RESULTS)

    def test_max_results_negative_uses_default(self) -> None:
        with patch.dict(
            os.environ,
            _env(**{ENV_AUTO_COLLECT_ENABLED: "true", ENV_MAX_RESULTS: "-3"}),
            clear=True,
        ):
            cfg = CollectorConfig.from_env()
        self.assertEqual(cfg.max_results, DEFAULT_MAX_RESULTS)

    def test_tavily_picks_up_api_key(self) -> None:
        with patch.dict(
            os.environ,
            _env(
                **{
                    ENV_AUTO_COLLECT_ENABLED: "true",
                    ENV_PROVIDER: PROVIDER_TAVILY,
                    ENV_TAVILY_API_KEY: "tav-key",
                }
            ),
            clear=True,
        ):
            cfg = CollectorConfig.from_env()
        self.assertEqual(cfg.provider, PROVIDER_TAVILY)
        self.assertEqual(cfg.api_key, "tav-key")


# ---------------------------------------------------------------------------
# Factory: build_collector
# ---------------------------------------------------------------------------


class BuildCollectorTestCase(unittest.TestCase):
    def test_returns_noop_when_disabled(self) -> None:
        cfg = CollectorConfig(enabled=False, provider=PROVIDER_MOCK, max_results=5)
        self.assertIsInstance(build_collector(cfg), NoOpCollector)

    def test_returns_mock_by_default_when_enabled(self) -> None:
        cfg = CollectorConfig(enabled=True, provider=PROVIDER_MOCK, max_results=5)
        self.assertIsInstance(build_collector(cfg), MockSearchCollector)

    def test_falls_back_to_mock_when_provider_key_missing(self) -> None:
        cfg = CollectorConfig(
            enabled=True, provider=PROVIDER_TAVILY, max_results=5, api_key=None
        )
        self.assertIsInstance(build_collector(cfg), MockSearchCollector)

    def test_returns_tavily_when_key_present(self) -> None:
        cfg = CollectorConfig(
            enabled=True, provider=PROVIDER_TAVILY, max_results=5, api_key="x"
        )
        self.assertIsInstance(build_collector(cfg), TavilySearchCollector)

    def test_returns_brave_when_key_present(self) -> None:
        cfg = CollectorConfig(
            enabled=True, provider=PROVIDER_BRAVE, max_results=5, api_key="x"
        )
        self.assertIsInstance(build_collector(cfg), BraveSearchCollector)


# ---------------------------------------------------------------------------
# Provider unavailable
# ---------------------------------------------------------------------------


class ProviderUnavailableTestCase(unittest.TestCase):
    def test_tavily_blocks_construction_without_key(self) -> None:
        with self.assertRaises(ProviderUnavailable):
            TavilySearchCollector(api_key="")

    def test_brave_blocks_construction_without_key(self) -> None:
        with self.assertRaises(ProviderUnavailable):
            BraveSearchCollector(api_key="")


# ---------------------------------------------------------------------------
# Query construction
# ---------------------------------------------------------------------------


class QueryConstructionTestCase(unittest.TestCase):
    def test_appends_role_boosters_for_designer(self) -> None:
        q = build_query_for_role(
            role="engineering-agent/product-designer",
            prompt="새 랜딩 hero 정리",
            task_type="landing-page",
        )
        self.assertIn("ui reference", q.lower())
        self.assertIn("design", q.lower())
        self.assertIn("랜딩 hero 정리", q)

    def test_appends_role_boosters_for_backend(self) -> None:
        q = build_query_for_role(
            role="engineering-agent/backend-engineer",
            prompt="users API 추가",
            task_type="backend-feature",
        )
        self.assertIn("official docs", q.lower())
        self.assertIn("api", q.lower())

    def test_dedup_skips_exact_repeat_tokens(self) -> None:
        # 'qa-engineer' boost already includes 'regression'; passing the same
        # token via extra_keywords must not double it (dedup by lowercase).
        q = build_query_for_role(
            role="engineering-agent/qa-engineer",
            prompt="회귀 시나리오",
            extra_keywords=("regression",),
        )
        # The standalone 'regression' token appears once even though it shows up
        # in both extra_keywords and the QA role booster list.
        tokens = q.split()
        self.assertEqual(tokens.count("regression"), 1)

    def test_unknown_role_returns_prompt_only(self) -> None:
        q = build_query_for_role(
            role="design-agent/illustrator",
            prompt="배너 시안",
        )
        self.assertEqual(q, "배너 시안")

    def test_uses_first_line_of_multiline_prompt(self) -> None:
        q = build_query_for_role(
            role="engineering-agent/tech-lead",
            prompt="결정 노트\n\n둘째 줄은 보너스",
        )
        self.assertIn("결정 노트", q)
        self.assertNotIn("둘째 줄", q)


# ---------------------------------------------------------------------------
# Mock collector — role-aware deterministic
# ---------------------------------------------------------------------------


class MockCollectorTestCase(unittest.TestCase):
    def test_designer_returns_design_references(self) -> None:
        collector = MockSearchCollector()
        results = collector.search(
            CollectorQuery(
                query="hero", role="engineering-agent/product-designer", max_results=3
            )
        )
        self.assertEqual(len(results), 3)
        for source in results:
            self.assertEqual(source.source_type, SourceType.DESIGN_REFERENCE)
            self.assertIn(source.extra["domain"], (
                "behance.net", "awwwards.com", "mobbin.com", "notefolio.net"
            ))
        # Designer sources should carry thumbnail metadata for at least one hit
        self.assertTrue(
            any(
                (s.extra or {}).get("thumbnail_url") for s in results
            )
        )

    def test_backend_returns_official_docs(self) -> None:
        collector = MockSearchCollector()
        results = collector.search(
            CollectorQuery(
                query="api", role="engineering-agent/backend-engineer", max_results=3
            )
        )
        self.assertEqual(len(results), 3)
        for source in results:
            self.assertEqual(source.source_type, SourceType.OFFICIAL_DOCS)
            self.assertIn(source.extra["domain"], (
                "fastapi.tiangolo.com", "postgresql.org", "cheatsheetseries.owasp.org"
            ))

    def test_frontend_returns_official_docs(self) -> None:
        collector = MockSearchCollector()
        results = collector.search(
            CollectorQuery(
                query="ui", role="engineering-agent/frontend-engineer", max_results=3
            )
        )
        self.assertEqual(len(results), 3)
        for source in results:
            self.assertEqual(source.source_type, SourceType.OFFICIAL_DOCS)

    def test_qa_returns_test_or_issue_sources(self) -> None:
        collector = MockSearchCollector()
        results = collector.search(
            CollectorQuery(
                query="regression", role="engineering-agent/qa-engineer", max_results=3
            )
        )
        self.assertEqual(len(results), 3)
        types = {r.source_type for r in results}
        self.assertTrue(types.issubset({SourceType.OFFICIAL_DOCS, SourceType.GITHUB_ISSUE}))

    def test_tech_lead_includes_decision_records(self) -> None:
        collector = MockSearchCollector()
        results = collector.search(
            CollectorQuery(
                query="architecture", role="engineering-agent/tech-lead", max_results=3
            )
        )
        self.assertEqual(len(results), 3)
        # Should include at least one community signal or github issue
        types = {r.source_type for r in results}
        self.assertTrue(types & {SourceType.OFFICIAL_DOCS, SourceType.COMMUNITY_SIGNAL, SourceType.GITHUB_ISSUE})

    def test_unknown_role_returns_empty(self) -> None:
        collector = MockSearchCollector()
        results = collector.search(
            CollectorQuery(query="x", role="design-agent/illustrator", max_results=3)
        )
        self.assertEqual(results, ())

    def test_results_carry_metadata_only(self) -> None:
        collector = MockSearchCollector()
        results = collector.search(
            CollectorQuery(
                query="hero", role="engineering-agent/product-designer", max_results=2
            )
        )
        for source in results:
            self.assertEqual(source.extra["provider"], "mock")
            self.assertIn("query", source.extra)
            self.assertEqual(source.collected_by_role, "engineering-agent/product-designer")
            self.assertIsNotNone(source.title)
            self.assertIsNotNone(source.source_url)
            # Attachments should be metadata-only — no file body
            for att in source.attachments:
                self.assertEqual(att.kind, "image")
                self.assertTrue(att.description.startswith("thumbnail"))

    def test_deterministic_for_same_query(self) -> None:
        collector = MockSearchCollector()
        a = collector.search(
            CollectorQuery(query="abc", role="engineering-agent/product-designer", max_results=2)
        )
        b = collector.search(
            CollectorQuery(query="abc", role="engineering-agent/product-designer", max_results=2)
        )
        self.assertEqual([s.title for s in a], [s.title for s in b])


# ---------------------------------------------------------------------------
# Pack assembly
# ---------------------------------------------------------------------------


class CollectResearchPackTestCase(unittest.TestCase):
    def test_pack_includes_user_message_and_collected_sources(self) -> None:
        collector = MockSearchCollector()
        pack = collect_research_pack(
            collector=collector,
            role="engineering-agent/product-designer",
            prompt="새 hero",
            task_type="landing-page",
            max_results=3,
        )
        types = [s.source_type for s in pack.sources]
        self.assertIn(SourceType.USER_MESSAGE, types)
        self.assertTrue(any(t == SourceType.DESIGN_REFERENCE for t in types))
        # Request is recorded with role and topic
        self.assertIsNotNone(pack.request)
        self.assertEqual(pack.request.role, "engineering-agent/product-designer")
        self.assertEqual(pack.request.topic, "새 hero")

    def test_user_links_become_url_sources(self) -> None:
        collector = NoOpCollector()
        pack = collect_research_pack(
            collector=collector,
            role="engineering-agent/tech-lead",
            prompt="결정 정리",
            user_links=("https://example.com/decision",),
        )
        url_sources = [s for s in pack.sources if s.source_type == SourceType.URL]
        self.assertEqual(len(url_sources), 1)
        self.assertEqual(url_sources[0].source_url, "https://example.com/decision")
        self.assertEqual(url_sources[0].confidence, "high")

    def test_user_image_attachment_becomes_image_reference(self) -> None:
        collector = NoOpCollector()
        att = ResearchAttachment(
            kind="image", url="https://cdn/x.png", filename="x.png", attachment_id="a1"
        )
        pack = collect_research_pack(
            collector=collector,
            role="engineering-agent/product-designer",
            prompt="시안",
            user_attachments=(att,),
        )
        image_sources = [s for s in pack.sources if s.source_type == SourceType.IMAGE_REFERENCE]
        self.assertEqual(len(image_sources), 1)
        self.assertEqual(image_sources[0].attachment_id, "a1")

    def test_role_aware_ranking_orders_design_first_for_designer(self) -> None:
        collector = MockSearchCollector()
        pack = collect_research_pack(
            collector=collector,
            role="engineering-agent/product-designer",
            prompt="hero",
            max_results=3,
        )
        # Filter out the user_message; the first non-user source should be DESIGN_REFERENCE
        non_user = [s for s in pack.sources if s.source_type != SourceType.USER_MESSAGE]
        self.assertEqual(non_user[0].source_type, SourceType.DESIGN_REFERENCE)


# ---------------------------------------------------------------------------
# Outcome flow — collect first, ask user only when nothing
# ---------------------------------------------------------------------------


class OutcomeFlowTestCase(unittest.TestCase):
    def _cfg(self, *, enabled: bool) -> CollectorConfig:
        return CollectorConfig(
            enabled=enabled, provider=PROVIDER_MOCK, max_results=3
        )

    def test_auto_collected_when_mock_returns_results(self) -> None:
        outcome = auto_collect_or_request_more_input(
            role="engineering-agent/product-designer",
            prompt="새 hero 정리",
            task_type="landing-page",
            config=self._cfg(enabled=True),
        )
        self.assertEqual(outcome.mode, CollectionMode.AUTO_COLLECTED)
        self.assertIsNotNone(outcome.pack)
        self.assertEqual(outcome.collector_name, "mock")
        self.assertGreaterEqual(outcome.auto_collected_count, 1)

    def test_user_provided_when_collector_disabled_but_user_pasted_link(self) -> None:
        outcome = auto_collect_or_request_more_input(
            role="engineering-agent/qa-engineer",
            prompt="회귀 잡아",
            task_type="qa-test",
            user_links=("https://example.com/issue",),
            config=self._cfg(enabled=False),
        )
        self.assertEqual(outcome.mode, CollectionMode.USER_PROVIDED)
        self.assertIsNotNone(outcome.pack)
        self.assertEqual(outcome.collector_name, "noop")
        self.assertEqual(outcome.auto_collected_count, 0)

    def test_needs_user_input_when_disabled_and_no_user_supply(self) -> None:
        outcome = auto_collect_or_request_more_input(
            role="engineering-agent/backend-engineer",
            prompt="users API 정리",
            task_type="backend-feature",
            config=self._cfg(enabled=False),
        )
        self.assertEqual(outcome.mode, CollectionMode.NEEDS_USER_INPUT)
        self.assertIsNone(outcome.pack)
        self.assertIn("API 스펙", outcome.user_prompt or "")

    def test_unknown_role_falls_back_to_needs_user_input(self) -> None:
        # Unknown role → mock returns nothing → no user supply → ask user.
        outcome = auto_collect_or_request_more_input(
            role="design-agent/illustrator",
            prompt="시안",
            config=self._cfg(enabled=True),
        )
        self.assertEqual(outcome.mode, CollectionMode.NEEDS_USER_INPUT)


# ---------------------------------------------------------------------------
# Forum-friendly summary
# ---------------------------------------------------------------------------


class FormatCollectionSummaryTestCase(unittest.TestCase):
    def test_summary_includes_role_and_why_relevant(self) -> None:
        outcome = auto_collect_or_request_more_input(
            role="engineering-agent/product-designer",
            prompt="새 hero",
            task_type="landing-page",
            config=CollectorConfig(enabled=True, provider=PROVIDER_MOCK, max_results=2),
        )
        summary = format_collection_summary(
            outcome.pack,
            collector_name=outcome.collector_name,
            query=outcome.query,
            role="engineering-agent/product-designer",
        )
        self.assertIn("1차 자료 수집 — product-designer", summary)
        self.assertIn("collector: `mock`", summary)
        # at least one why_relevant shows
        self.assertIn("활용 가능성", summary)

    def test_summary_skips_user_message_block(self) -> None:
        outcome = auto_collect_or_request_more_input(
            role="engineering-agent/product-designer",
            prompt="새 hero",
            config=CollectorConfig(enabled=True, provider=PROVIDER_MOCK, max_results=2),
        )
        summary = format_collection_summary(
            outcome.pack,
            collector_name=outcome.collector_name,
            query=outcome.query,
            role="engineering-agent/product-designer",
        )
        # user_message is not a "collected" source — its summary line shouldn't show
        self.assertNotIn("[user_message]", summary)


# ---------------------------------------------------------------------------
# Domain helper
# ---------------------------------------------------------------------------


class ExtractDomainTestCase(unittest.TestCase):
    def test_extracts_lowercase_host(self) -> None:
        self.assertEqual(extract_domain("https://Example.COM/x?y=1"), "example.com")

    def test_handles_none_or_blank(self) -> None:
        self.assertEqual(extract_domain(None), "")
        self.assertEqual(extract_domain(""), "")
        self.assertEqual(extract_domain("not a url"), "")


# ---------------------------------------------------------------------------
# short_role helper
# ---------------------------------------------------------------------------


class ShortRoleTestCase(unittest.TestCase):
    def test_strips_agent_prefix(self) -> None:
        self.assertEqual(
            short_role("engineering-agent/product-designer"), "product-designer"
        )

    def test_returns_unchanged_when_no_slash(self) -> None:
        self.assertEqual(short_role("tech-lead"), "tech-lead")


if __name__ == "__main__":
    unittest.main()
