from __future__ import annotations

import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knigovishte_podcast.config import DEFAULT_LANGBLY_BASE_URL, TranslationConfig


class TranslationConfigFromEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workdir = Path(__file__).resolve().parent / "_artifacts" / self._testMethodName
        if self.workdir.exists():
            shutil.rmtree(self.workdir)
        self.workdir.mkdir(parents=True)

    def tearDown(self) -> None:
        if self.workdir.exists():
            shutil.rmtree(self.workdir)

    def test_from_env_adds_default_fallback_for_custom_base_url(self) -> None:
        env_path = self.workdir / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "LANGBLY_API_KEY=test-key",
                    "LANGBLY_BASE_URL=https://eu.langbly.com",
                    "LANGBLY_TIMEOUT_SECONDS=15",
                    "LANGBLY_MAX_RETRIES=2",
                    "LANGBLY_RETRY_BACKOFF_SECONDS=0.5",
                ]
            ),
            encoding="utf-8",
        )

        with patch.dict(os.environ, {}, clear=True):
            config = TranslationConfig.from_env(self.workdir)

        self.assertEqual(
            config.all_base_urls(),
            ("https://eu.langbly.com", DEFAULT_LANGBLY_BASE_URL),
        )
        self.assertEqual(config.timeout_seconds, 15.0)
        self.assertEqual(config.max_retries, 2)
        self.assertEqual(config.retry_backoff_seconds, 0.5)


if __name__ == "__main__":
    unittest.main()
