from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knigovishte_podcast.config import ProjectPaths
from knigovishte_podcast.models import Article
from knigovishte_podcast.services.dedup import ArticleAudioManifest


class ArticleAudioManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workdir = Path(__file__).resolve().parent / "_artifacts" / self._testMethodName
        if self.workdir.exists():
            shutil.rmtree(self.workdir)
        self.paths = ProjectPaths.from_root(self.workdir)
        self.paths.ensure()
        self.manifest = ArticleAudioManifest.for_paths(self.paths)

    def tearDown(self) -> None:
        if self.workdir.exists():
            shutil.rmtree(self.workdir)

    def test_record_and_find_existing_audio(self) -> None:
        article = Article(
            source_url="https://www.knigovishte.bg/vijte/42-test",
            title_bg="Българско заглавие",
            sentences_bg=("Едно изречение.", "Още едно изречение."),
        )
        audio_path = self.paths.audio / "vijte-42-test.mp3"
        audio_path.write_bytes(b"audio")

        self.manifest.record(article, audio_path)

        self.assertEqual(self.manifest.find_existing_audio(article), audio_path)
        payload = json.loads(self.manifest.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 1)
        self.assertEqual(len(payload["articles"]), 1)

    def test_hash_treats_same_content_as_duplicate_even_when_url_changes(self) -> None:
        first_article = Article(
            source_url="https://www.knigovishte.bg/vijte/42-test",
            title_bg="Българско заглавие",
            sentences_bg=("Едно изречение.",),
        )
        republished_article = Article(
            source_url="https://www.knigovishte.bg/vijte/99-republished",
            title_bg="Българско заглавие",
            sentences_bg=("Едно изречение.",),
        )
        audio_path = self.paths.audio / "vijte-42-test.mp3"
        audio_path.write_bytes(b"audio")

        self.manifest.record(first_article, audio_path)

        self.assertEqual(self.manifest.find_existing_audio(republished_article), audio_path)


if __name__ == "__main__":
    unittest.main()
