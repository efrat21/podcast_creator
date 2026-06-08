from __future__ import annotations

import io
import shutil
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knigovishte_podcast.cli import main
from knigovishte_podcast.config import ProjectPaths, episode_slug_from_url
from knigovishte_podcast.models import Article, Translation
from knigovishte_podcast.services.dedup import ArticleAudioManifest
from knigovishte_podcast.services.rss import FeedBuildResult
from knigovishte_podcast.services.tts import AUDIO_FILE_EXTENSION


class StubFetcher:
    def __init__(self, article: Article, html: str) -> None:
        self.article = article
        self.html = html
        self.fetch_html_calls = 0
        self.parse_html_calls = 0

    def fetch_html(self, url: str) -> str:
        self.fetch_html_calls += 1
        return self.html

    def parse_html(self, url: str, html: str) -> Article:
        self.parse_html_calls += 1
        return self.article


class StubTranslator:
    def __init__(self, translation: Translation) -> None:
        self.translation = translation
        self.calls: list[Article] = []

    def translate(self, article: Article) -> Translation:
        self.calls.append(article)
        return self.translation


class StubAudioGenerator:
    def __init__(self, audio_root: Path) -> None:
        self.audio_root = audio_root
        self.calls: list[tuple[str, str]] = []

    def generate(self, script_text: str, episode_slug: str) -> Path:
        self.calls.append((script_text, episode_slug))
        self.audio_root.mkdir(parents=True, exist_ok=True)
        audio_path = self.audio_root / f"{episode_slug}{AUDIO_FILE_EXTENSION}"
        audio_path.write_bytes(b"audio")
        return audio_path


class CliCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workdir = Path(__file__).resolve().parent / "_artifacts" / self._testMethodName
        if self.workdir.exists():
            shutil.rmtree(self.workdir)
        self.paths = ProjectPaths.from_root(self.workdir)
        self.paths.ensure()

        self.article = Article(
            source_url="https://www.knigovishte.bg/vijte/42-test",
            title_bg="Българско заглавие",
            sentences_bg=("Едно изречение.", "Още едно изречение."),
        )
        self.translation = Translation(
            title_en="English Title",
            sentences_en=("One sentence.", "Another sentence."),
        )
        self.html = "<html>cached article</html>"

    def tearDown(self) -> None:
        if self.workdir.exists():
            shutil.rmtree(self.workdir)

    def test_plan_command_reports_expected_paths(self) -> None:
        stdout = io.StringIO()
        slug = episode_slug_from_url(self.article.source_url)

        with patch("knigovishte_podcast.cli.ProjectPaths.from_root", return_value=self.paths):
            with redirect_stdout(stdout):
                exit_code = main(["plan", "--url", self.article.source_url])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn(f"Episode slug: {slug}", output)
        self.assertIn(f"Article cache: {self.paths.articles / f'{slug}.html'}", output)
        self.assertIn(
            f"Translation output: {self.paths.scripts / f'{slug}.translation.txt'}",
            output,
        )
        self.assertIn(f"Audio output: {self.paths.audio / f'{slug}{AUDIO_FILE_EXTENSION}'}", output)

    def test_fetch_command_reuses_cached_html_and_reports_cache(self) -> None:
        slug = episode_slug_from_url(self.article.source_url)
        cache_path = self.paths.articles / f"{slug}.html"
        cache_path.write_text(self.html, encoding="utf-8")
        fetcher = StubFetcher(self.article, "<html>fresh article</html>")
        stdout = io.StringIO()

        with patch("knigovishte_podcast.cli.ProjectPaths.from_root", return_value=self.paths):
            with patch("knigovishte_podcast.cli.KnigovishteArticleFetcher", return_value=fetcher):
                with redirect_stdout(stdout):
                    exit_code = main(["fetch", "--url", self.article.source_url])

        self.assertEqual(exit_code, 0)
        self.assertEqual(fetcher.fetch_html_calls, 0)
        self.assertEqual(fetcher.parse_html_calls, 1)
        output = stdout.getvalue()
        self.assertIn("HTML source: cache", output)
        self.assertIn(f"Cached HTML: {cache_path}", output)

    def test_translate_command_writes_translation_artifact(self) -> None:
        fetcher = StubFetcher(self.article, self.html)
        translator = StubTranslator(self.translation)
        stdout = io.StringIO()
        translation_path = self.paths.scripts / f"{episode_slug_from_url(self.article.source_url)}.translation.txt"

        with patch("knigovishte_podcast.cli.ProjectPaths.from_root", return_value=self.paths):
            with patch("knigovishte_podcast.cli.KnigovishteArticleFetcher", return_value=fetcher):
                with patch("knigovishte_podcast.cli.TranslationConfig.from_env", return_value=Mock()):
                    with patch("knigovishte_podcast.cli.LangblyTranslator", return_value=translator):
                        with redirect_stdout(stdout):
                            exit_code = main(["translate", "--url", self.article.source_url])

        self.assertEqual(exit_code, 0)
        self.assertEqual(translator.calls, [self.article])
        self.assertTrue(translation_path.exists())
        artifact_text = translation_path.read_text(encoding="utf-8")
        self.assertIn("English title: English Title", artifact_text)
        self.assertIn("1. EN: One sentence.", artifact_text)
        output = stdout.getvalue()
        self.assertIn(f"Translation output: {translation_path}", output)
        self.assertIn("Translated title: English Title", output)

    def test_build_script_command_writes_script_output(self) -> None:
        fetcher = StubFetcher(self.article, self.html)
        translator = StubTranslator(self.translation)
        stdout = io.StringIO()
        script_path = self.paths.scripts / f"{episode_slug_from_url(self.article.source_url)}.txt"

        with patch("knigovishte_podcast.cli.ProjectPaths.from_root", return_value=self.paths):
            with patch("knigovishte_podcast.cli.KnigovishteArticleFetcher", return_value=fetcher):
                with patch("knigovishte_podcast.cli.TranslationConfig.from_env", return_value=Mock()):
                    with patch("knigovishte_podcast.cli.LangblyTranslator", return_value=translator):
                        with redirect_stdout(stdout):
                            exit_code = main(["build-script", "--url", self.article.source_url])

        self.assertEqual(exit_code, 0)
        self.assertTrue(script_path.exists())
        script_text = script_path.read_text(encoding="utf-8")
        self.assertIn("English title: English Title", script_text)
        self.assertIn("Едно изречение.", script_text)
        output = stdout.getvalue()
        self.assertIn(f"Script output: {script_path}", output)

    def test_generate_audio_command_writes_script_and_audio_output(self) -> None:
        fetcher = StubFetcher(self.article, self.html)
        translator = StubTranslator(self.translation)
        audio_generator = StubAudioGenerator(self.paths.audio)
        stdout = io.StringIO()
        slug = episode_slug_from_url(self.article.source_url)
        expected_audio_path = self.paths.audio / f"{slug}{AUDIO_FILE_EXTENSION}"
        expected_script_path = self.paths.scripts / f"{slug}.txt"

        with patch("knigovishte_podcast.cli.ProjectPaths.from_root", return_value=self.paths):
            with patch("knigovishte_podcast.cli.KnigovishteArticleFetcher", return_value=fetcher):
                with patch("knigovishte_podcast.cli.TranslationConfig.from_env", return_value=Mock()):
                    with patch("knigovishte_podcast.cli.LangblyTranslator", return_value=translator):
                        with patch(
                            "knigovishte_podcast.cli.build_default_audio_generator",
                            return_value=audio_generator,
                        ) as audio_factory:
                            with redirect_stdout(stdout):
                                exit_code = main(["generate-audio", "--url", self.article.source_url, "--refresh"])

        self.assertEqual(exit_code, 0)
        audio_factory.assert_called_once_with(voice_name=None, bg_voice_name=None)
        self.assertEqual(fetcher.fetch_html_calls, 1)
        self.assertTrue(expected_script_path.exists())
        self.assertTrue(expected_audio_path.exists())
        self.assertEqual(
            audio_generator.calls,
            [(expected_script_path.read_text(encoding="utf-8"), slug)],
        )
        output = stdout.getvalue()
        self.assertIn("HTML source: network", output)
        self.assertIn(f"Audio output: {expected_audio_path}", output)

    def test_generate_audio_command_passes_voice_overrides_to_audio_factory(self) -> None:
        fetcher = StubFetcher(self.article, self.html)
        translator = StubTranslator(self.translation)
        audio_generator = StubAudioGenerator(self.paths.audio)

        with patch("knigovishte_podcast.cli.ProjectPaths.from_root", return_value=self.paths):
            with patch("knigovishte_podcast.cli.KnigovishteArticleFetcher", return_value=fetcher):
                with patch("knigovishte_podcast.cli.TranslationConfig.from_env", return_value=Mock()):
                    with patch("knigovishte_podcast.cli.LangblyTranslator", return_value=translator):
                        with patch(
                            "knigovishte_podcast.cli.build_default_audio_generator",
                            return_value=audio_generator,
                        ) as audio_factory:
                            exit_code = main(
                                [
                                    "generate-audio",
                                    "--url",
                                    self.article.source_url,
                                    "--refresh",
                                    "--en-voice",
                                    "en-US-Standard-C",
                                    "--bg-voice",
                                    "bg-BG-Standard-B",
                                ]
                            )

        self.assertEqual(exit_code, 0)
        audio_factory.assert_called_once_with(
            voice_name="en-US-Standard-C",
            bg_voice_name="bg-BG-Standard-B",
        )

    def test_generate_audio_command_skips_duplicate_article(self) -> None:
        fetcher = StubFetcher(self.article, self.html)
        existing_audio_path = self.paths.audio / f"already-generated{AUDIO_FILE_EXTENSION}"
        existing_audio_path.write_bytes(b"audio")
        ArticleAudioManifest.for_paths(self.paths).record(self.article, existing_audio_path)
        stdout = io.StringIO()

        with patch("knigovishte_podcast.cli.ProjectPaths.from_root", return_value=self.paths):
            with patch("knigovishte_podcast.cli.KnigovishteArticleFetcher", return_value=fetcher):
                with patch(
                    "knigovishte_podcast.cli.TranslationConfig.from_env",
                    side_effect=AssertionError("translate should not run for duplicates"),
                ):
                    with patch(
                        "knigovishte_podcast.cli.build_default_audio_generator",
                        side_effect=AssertionError("audio generation should not run for duplicates"),
                    ):
                        with redirect_stdout(stdout):
                            exit_code = main(["generate-audio", "--url", self.article.source_url])

        self.assertEqual(exit_code, 0)
        self.assertEqual(fetcher.parse_html_calls, 1)
        output = stdout.getvalue()
        self.assertIn(f"Audio output: {existing_audio_path}", output)
        self.assertIn("Skipping audio generation because this article was already used.", output)

    def test_fetch_command_reports_failure_and_returns_one(self) -> None:
        stdout = io.StringIO()
        fetcher = Mock()
        fetcher.fetch_html.side_effect = ValueError("bad url")

        with patch("knigovishte_podcast.cli.ProjectPaths.from_root", return_value=self.paths):
            with patch("knigovishte_podcast.cli.KnigovishteArticleFetcher", return_value=fetcher):
                with redirect_stdout(stdout):
                    exit_code = main(["fetch", "--url", self.article.source_url, "--refresh"])

        self.assertEqual(exit_code, 1)
        self.assertIn("Fetch failed: bad url", stdout.getvalue())

    def test_run_command_reports_failure_and_returns_one(self) -> None:
        stdout = io.StringIO()
        mock_pipeline = Mock()
        mock_pipeline.run.side_effect = RuntimeError("translator offline")

        with patch("knigovishte_podcast.cli.ProjectPaths.from_root", return_value=self.paths):
            with patch("knigovishte_podcast.cli.build_pipeline", return_value=mock_pipeline):
                with redirect_stdout(stdout):
                    exit_code = main(["run", "--url", self.article.source_url])

        self.assertEqual(exit_code, 1)
        self.assertIn("Pipeline failed: translator offline", stdout.getvalue())

    def test_web_command_starts_local_ui(self) -> None:
        stdout = io.StringIO()
        mock_app = Mock()

        with patch("knigovishte_podcast.cli.ProjectPaths.from_root", return_value=self.paths):
            with patch("knigovishte_podcast.web.create_app", return_value=mock_app) as create_app_mock:
                with redirect_stdout(stdout):
                    exit_code = main(["web", "--host", "127.0.0.1", "--port", "5050"])

        self.assertEqual(exit_code, 0)
        create_app_mock.assert_called_once_with(self.paths)
        mock_app.run.assert_called_once_with(host="127.0.0.1", port=5050, debug=False)
        output = stdout.getvalue()
        self.assertIn("Starting local web UI at http://127.0.0.1:5050", output)
        self.assertIn(f"Output folder: {self.paths.data}", output)

    def test_daily_check_command_generates_new_episode(self) -> None:
        """Test daily-check command when a new article is found."""
        stdout = io.StringIO()

        with patch("knigovishte_podcast.cli.ProjectPaths.from_root", return_value=self.paths):
            with patch("knigovishte_podcast.cli.build_pipeline") as build_pipeline_mock:
                mock_pipeline = Mock()
                mock_pipeline.run.return_value = Mock(
                    audio_path=self.paths.audio / f"test{AUDIO_FILE_EXTENSION}"
                )
                build_pipeline_mock.return_value = mock_pipeline

                with patch("knigovishte_podcast.cli.ArticleSelector") as selector_mock:
                    selector_instance = Mock()
                    selector_instance.select_article.return_value = self.article
                    selector_mock.return_value = selector_instance

                    with redirect_stdout(stdout):
                        exit_code = main(["daily-check"])

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("Running daily episode check", output)

    def test_daily_check_command_passes_voice_overrides(self) -> None:
        """Test daily-check command with voice overrides."""
        stdout = io.StringIO()

        with patch("knigovishte_podcast.cli.ProjectPaths.from_root", return_value=self.paths):
            with patch("knigovishte_podcast.cli.build_pipeline") as build_pipeline_mock:
                mock_pipeline = Mock()
                mock_pipeline.run.return_value = Mock(
                    audio_path=self.paths.audio / f"test{AUDIO_FILE_EXTENSION}"
                )
                build_pipeline_mock.return_value = mock_pipeline

                with patch("knigovishte_podcast.cli.ArticleSelector") as selector_mock:
                    selector_instance = Mock()
                    selector_instance.select_article.return_value = self.article
                    selector_mock.return_value = selector_instance

                    with patch("knigovishte_podcast.cli.build_default_audio_generator") as audio_mock:
                        audio_mock.return_value = Mock()
                        with redirect_stdout(stdout):
                            exit_code = main([
                                "daily-check",
                                "--en-voice", "en-GB-Standard-A",
                                "--bg-voice", "bg-BG-Standard-B",
                            ])

        self.assertEqual(exit_code, 0)
        audio_mock.assert_called_once_with(
            voice_name="en-GB-Standard-A",
            bg_voice_name="bg-BG-Standard-B",
        )

    def test_local_rss_delivery_command_rebuilds_feed_without_serving(self) -> None:
        stdout = io.StringIO()
        feed_result = FeedBuildResult(
            feed_path=self.paths.rss / "podcast.xml",
            feed_url="http://127.0.0.1:8000/podcast.xml",
            staged_episode_paths=(self.paths.rss_episodes / "episode.wav",),
        )

        with patch("knigovishte_podcast.cli.ProjectPaths.from_root", return_value=self.paths):
            with patch("knigovishte_podcast.cli.LocalRSSService") as rss_service_cls:
                rss_service = rss_service_cls.return_value
                rss_service.build_public_base_url.return_value = "http://127.0.0.1:8000"
                rss_service.rebuild_feed.return_value = feed_result

                with redirect_stdout(stdout):
                    exit_code = main(["local-rss-delivery", "--no-serve", "--public-host", "127.0.0.1"])

        self.assertEqual(exit_code, 0)
        rss_service_cls.assert_called_once_with(self.paths)
        rss_service.build_public_base_url.assert_called_once_with(
            bind_host="0.0.0.0",
            port=8000,
            public_host="127.0.0.1",
        )
        rss_service.rebuild_feed.assert_called_once_with("http://127.0.0.1:8000")
        rss_service.create_server.assert_not_called()
        output = stdout.getvalue()
        self.assertIn(f"Staged RSS feed: {feed_result.feed_path}", output)
        self.assertIn(f"Feed URL: {feed_result.feed_url}", output)

    def test_local_rss_delivery_command_serves_feed_until_stopped(self) -> None:
        stdout = io.StringIO()
        feed_result = FeedBuildResult(
            feed_path=self.paths.rss / "podcast.xml",
            feed_url="http://127.0.0.1:8765/podcast.xml",
            staged_episode_paths=(self.paths.rss_episodes / "episode.wav",),
        )
        mock_server = Mock()
        mock_server.server_address = ("0.0.0.0", 8765)
        mock_server.serve_forever.side_effect = KeyboardInterrupt()

        with patch("knigovishte_podcast.cli.ProjectPaths.from_root", return_value=self.paths):
            with patch("knigovishte_podcast.cli.LocalRSSService") as rss_service_cls:
                rss_service = rss_service_cls.return_value
                rss_service.create_server.return_value = mock_server
                rss_service.build_public_base_url.return_value = "http://127.0.0.1:8765"
                rss_service.rebuild_feed.return_value = feed_result

                with redirect_stdout(stdout):
                    exit_code = main(["local-rss-delivery", "--public-host", "127.0.0.1"])

        self.assertEqual(exit_code, 0)
        rss_service.create_server.assert_called_once_with(host="0.0.0.0", port=8000)
        rss_service.build_public_base_url.assert_called_once_with(
            bind_host="0.0.0.0",
            port=8765,
            public_host="127.0.0.1",
        )
        rss_service.rebuild_feed.assert_called_once_with("http://127.0.0.1:8765")
        mock_server.serve_forever.assert_called_once_with()
        mock_server.server_close.assert_called_once_with()
        output = stdout.getvalue()
        self.assertIn(f"Feed URL: {feed_result.feed_url}", output)
        self.assertIn("Local RSS server stopped.", output)

if __name__ == "__main__":
    unittest.main()
