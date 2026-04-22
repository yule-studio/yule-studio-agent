from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

import subprocess
import unittest
from unittest.mock import patch

from yule_orchestrator.integrations.github.issues import (
    GitHubIssue,
    GitHubViewerContext,
    list_open_issues,
)


class GitHubIssueCacheTestCase(unittest.TestCase):
    def test_list_open_issues_uses_cached_result_before_remote_fetch(self) -> None:
        cached_issue = GitHubIssue(
            number=12,
            repository="yule-studio/yule-studio-agent",
            title="Cached issue",
            url="https://example.com/issues/12",
            owner="yule-studio",
            scope="org:yule-studio",
        )

        with patch("yule_orchestrator.integrations.github.issues.shutil.which", return_value="/opt/homebrew/bin/gh"), patch(
            "yule_orchestrator.integrations.github.issues._load_viewer_context",
            return_value=GitHubViewerContext(viewer_login="codwithyc", org_logins=("yule-studio",)),
        ), patch(
            "yule_orchestrator.integrations.github.issues._load_issue_cache",
            return_value=[cached_issue],
        ), patch(
            "yule_orchestrator.integrations.github.issues._load_stale_issue_cache",
            return_value=None,
        ), patch(
            "yule_orchestrator.integrations.github.issues.subprocess.run"
        ) as run_mock:
            issues = list_open_issues(limit=20)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].title, "Cached issue")
        run_mock.assert_not_called()

    def test_list_open_issues_saves_remote_result_on_cache_miss(self) -> None:
        remote_payload = subprocess.CompletedProcess(
            args=["gh", "search", "issues"],
            returncode=0,
            stdout='[{"number":31,"title":"Remote issue","url":"https://example.com/issues/31","repository":"yule-studio/yule-studio-agent"}]',
            stderr="",
        )

        with patch("yule_orchestrator.integrations.github.issues.shutil.which", return_value="/opt/homebrew/bin/gh"), patch(
            "yule_orchestrator.integrations.github.issues._load_viewer_context",
            return_value=GitHubViewerContext(viewer_login="codwithyc", org_logins=("yule-studio",)),
        ), patch(
            "yule_orchestrator.integrations.github.issues._load_issue_cache",
            return_value=None,
        ), patch(
            "yule_orchestrator.integrations.github.issues._load_stale_issue_cache",
            return_value=None,
        ), patch(
            "yule_orchestrator.integrations.github.issues.subprocess.run",
            return_value=remote_payload,
        ) as run_mock, patch(
            "yule_orchestrator.integrations.github.issues.save_issue_payload"
        ) as save_mock:
            issues = list_open_issues(limit=20)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].title, "Remote issue")
        run_mock.assert_called_once()
        save_mock.assert_called_once()
