from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

from yule_orchestrator.discord.formatter import format_references_block
from yule_orchestrator.discord.member_bots import (
    GATEWAY_ROLE_KEY,
    env_key_for,
    load_member_bot_config,
    render_startup_summary,
    select_profile_for_role,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class EnvKeyTestCase(unittest.TestCase):
    def test_gateway_key(self) -> None:
        self.assertEqual(
            env_key_for("engineering-agent", GATEWAY_ROLE_KEY),
            "ENGINEERING_AGENT_BOT_GATEWAY_TOKEN",
        )

    def test_member_key(self) -> None:
        self.assertEqual(
            env_key_for("engineering-agent", "backend-engineer"),
            "ENGINEERING_AGENT_BOT_BACKEND_ENGINEER_TOKEN",
        )

    def test_other_department_prefix(self) -> None:
        self.assertEqual(
            env_key_for("design-agent", "product-designer"),
            "DESIGN_AGENT_BOT_PRODUCT_DESIGNER_TOKEN",
        )


class LoadMemberBotConfigTestCase(unittest.TestCase):
    def test_engineering_agent_lists_gateway_and_members(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            for key in list(os.environ):
                if key.startswith("ENGINEERING_AGENT_BOT_"):
                    del os.environ[key]
            config = load_member_bot_config(REPO_ROOT, "engineering-agent")

        self.assertEqual(
            config.role_ids(),
            (
                GATEWAY_ROLE_KEY,
                "tech-lead",
                "ai-engineer",
                "product-designer",
                "backend-engineer",
                "frontend-engineer",
                "qa-engineer",
            ),
        )
        for profile in config.profiles:
            self.assertFalse(profile.active)

    def test_token_in_env_marks_profile_active(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("ENGINEERING_AGENT_BOT_")}
        env["ENGINEERING_AGENT_BOT_BACKEND_ENGINEER_TOKEN"] = "abc"
        with patch.dict(os.environ, env, clear=True):
            config = load_member_bot_config(REPO_ROOT, "engineering-agent")
            profile = config.get("backend-engineer")
            self.assertTrue(profile.active)
            self.assertEqual(profile.token, "abc")

    def test_unknown_agent_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            load_member_bot_config(REPO_ROOT, "no-such-agent")

    def test_ai_engineer_role_is_registered_with_expected_env_key(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            for key in list(os.environ):
                if key.startswith("ENGINEERING_AGENT_BOT_"):
                    del os.environ[key]
            config = load_member_bot_config(REPO_ROOT, "engineering-agent")

        ai_engineer = config.get("ai-engineer")
        self.assertEqual(
            ai_engineer.env_key,
            "ENGINEERING_AGENT_BOT_AI_ENGINEER_TOKEN",
        )
        self.assertFalse(ai_engineer.active)

    def test_ai_engineer_token_in_env_marks_profile_active(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("ENGINEERING_AGENT_BOT_")}
        env["ENGINEERING_AGENT_BOT_AI_ENGINEER_TOKEN"] = "ai-token"
        with patch.dict(os.environ, env, clear=True):
            config = load_member_bot_config(REPO_ROOT, "engineering-agent")
            profile = config.get("ai-engineer")
            self.assertTrue(profile.active)
            self.assertEqual(profile.token, "ai-token")


class SelectProfileTestCase(unittest.TestCase):
    def test_unknown_role_lists_available(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            for key in list(os.environ):
                if key.startswith("ENGINEERING_AGENT_BOT_"):
                    del os.environ[key]
            config = load_member_bot_config(REPO_ROOT, "engineering-agent")

        with self.assertRaises(ValueError) as ctx:
            select_profile_for_role(config, "phantom", require_token=False)

        message = str(ctx.exception)
        self.assertIn("phantom", message)
        self.assertIn("backend-engineer", message)

    def test_missing_token_blocks_real_run(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            for key in list(os.environ):
                if key.startswith("ENGINEERING_AGENT_BOT_"):
                    del os.environ[key]
            config = load_member_bot_config(REPO_ROOT, "engineering-agent")

        with self.assertRaises(ValueError) as ctx:
            select_profile_for_role(config, "tech-lead")

        self.assertIn("ENGINEERING_AGENT_BOT_TECH_LEAD_TOKEN", str(ctx.exception))

    def test_dry_run_allows_inactive_profile(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            for key in list(os.environ):
                if key.startswith("ENGINEERING_AGENT_BOT_"):
                    del os.environ[key]
            config = load_member_bot_config(REPO_ROOT, "engineering-agent")

        profile = select_profile_for_role(config, "tech-lead", require_token=False)
        self.assertFalse(profile.active)


class StartupSummaryTestCase(unittest.TestCase):
    def test_summary_includes_status_and_env_key(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("ENGINEERING_AGENT_BOT_")}
        env["ENGINEERING_AGENT_BOT_GATEWAY_TOKEN"] = "tok"
        with patch.dict(os.environ, env, clear=True):
            config = load_member_bot_config(REPO_ROOT, "engineering-agent")

        lines = render_startup_summary(config)
        joined = "\n".join(lines)
        self.assertIn("engineering-agent (gateway): active", joined)
        self.assertIn("engineering-agent/qa-engineer: skipped", joined)
        self.assertIn("ENGINEERING_AGENT_BOT_QA_ENGINEER_TOKEN", joined)


class ReferencesBlockTestCase(unittest.TestCase):
    def test_empty_returns_empty(self) -> None:
        self.assertEqual(format_references_block([]), "")

    def test_renders_title_source_url_takeaway(self) -> None:
        block = format_references_block(
            [
                {
                    "title": "Stripe Pricing",
                    "source": "Mobbin",
                    "url": "https://example.com/stripe",
                    "takeaway": "step copy 시각 강조 차용",
                },
                {"title": "Naked Wines"},
            ]
        )
        self.assertIn("**참고 레퍼런스**", block)
        self.assertIn("Stripe Pricing", block)
        self.assertIn("Mobbin", block)
        self.assertIn("https://example.com/stripe", block)
        self.assertIn("step copy", block)
        self.assertIn("Naked Wines", block)

    def test_limit_truncates_to_top_n(self) -> None:
        items = [{"title": f"item-{i}"} for i in range(10)]
        block = format_references_block(items, limit=3)
        self.assertEqual(block.count("item-"), 3)


if __name__ == "__main__":
    unittest.main()
