from __future__ import annotations

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tests import _bootstrap  # noqa: F401

import unittest
from unittest.mock import patch

from yule_orchestrator.planning.ollama_config import load_ollama_planning_config


class OllamaConfigTestCase(unittest.TestCase):
    def test_load_ollama_planning_config_uses_defaults(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            config = load_ollama_planning_config()

        self.assertFalse(config.enabled)
        self.assertEqual(config.endpoint, "http://localhost:11434")
        self.assertEqual(config.model, "gemma3:latest")
        self.assertEqual(config.timeout_seconds, 20)

    def test_load_ollama_planning_config_reads_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OLLAMA_PLANNING_ENABLED": "true",
                "OLLAMA_ENDPOINT": "http://ollama.local:11434",
                "OLLAMA_MODEL": "qwen2.5:3b",
                "OLLAMA_TIMEOUT_SECONDS": "45",
            },
            clear=True,
        ):
            config = load_ollama_planning_config()

        self.assertTrue(config.enabled)
        self.assertEqual(config.endpoint, "http://ollama.local:11434")
        self.assertEqual(config.model, "qwen2.5:3b")
        self.assertEqual(config.timeout_seconds, 45)


if __name__ == "__main__":
    unittest.main()
