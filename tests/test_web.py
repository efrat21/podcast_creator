from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knigovishte_podcast.config import ProjectPaths
from knigovishte_podcast.models import Article, PodcastPlan, Translation
from knigovishte_podcast.services.article_selector import ArticleFilter
from knigovishte_podcast.services.dedup import DuplicateArticleError
from knigovishte_podcast.services.translator import LangblyTimeoutError
from knigovishte_podcast.web import UNEXPECTED_ERROR_MESSAGE, create_app


class WebUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workdir = Path(__file__).resolve().parent / "_artifacts" / self._testMethodName
        if self.workdir.exists():
            shutil.rmtree(self.workdir)
        self.paths = ProjectPaths.from_root(self.workdir)
        self.paths.ensure()

        self.article = Article(
            source_url="https://www.knigovishte.bg/vijte/42-test",
            title_bg="Българско заглавие",
            sentences_bg=("Едно изречение.",),
        )
        self.translation = Translation(
            title_en="English Title",
            sentences_en=("One sentence.",),
        )
        self.plan = PodcastPlan(
            article=self.article,
            translation=self.translation,
            script_text="script",
            script_path=self.paths.scripts / "vijte-42-test.txt",
            audio_path=self.paths.audio / "vijte-42-test.mp3",
            article_html_path=self.paths.articles / "vijte-42-test.html",
        )

    def tearDown(self) -> None:
        if self.workdir.exists():
            shutil.rmtree(self.workdir)

    def test_index_renders_form_without_local_path_leaks(self) -> None:
        client = create_app(self.paths).test_client()

        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Article URL (optional)", page)
        self.assertIn("Minimum length (sentences)", page)
        self.assertIn("Category", page)
        self.assertIn("Working...", page)
        self.assertIn("Society", page)
        self.assertNotIn("Общество", page)
        self.assertNotIn("Output folder", page)
        self.assertNotIn(str(self.paths.data), page)
        self.assertNotIn("file:///", page)
        self.assertIn('meta name="robots" content="noindex, nofollow"', page)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("form-action 'self'", response.headers["Content-Security-Policy"])

    def test_post_runs_pipeline_for_explicit_url(self) -> None:
        mock_pipeline = Mock()
        mock_pipeline.run.return_value = self.plan

        with patch("knigovishte_podcast.web.pipeline", return_value=mock_pipeline) as pipeline_factory:
            client = create_app(self.paths).test_client()
            response = client.post("/", data={"url": self.article.source_url, "refresh": "on"})

        self.assertEqual(response.status_code, 200)
        pipeline_factory.assert_called_once_with(paths=self.paths, use_cached_html=False)
        mock_pipeline.run.assert_called_once_with(self.article.source_url)
        page = response.get_data(as_text=True)
        self.assertIn("Your episode is ready.", page)
        self.assertNotIn("Podcast artifacts generated", page)
        self.assertNotIn("Used the URL you entered.", page)
        self.assertNotIn(str(self.paths.data), page)
        self.assertNotIn("file:///", page)
        self.assertNotIn(str(self.plan.audio_path.resolve()), page)
        self.assertNotIn("Article URL:", page)
        self.assertNotIn(f'href="{self.plan.audio_path.resolve().as_uri()}"', page)

    def test_post_normalizes_explicit_url_before_running_pipeline(self) -> None:
        mock_pipeline = Mock()
        mock_pipeline.run.return_value = self.plan

        with patch("knigovishte_podcast.web.pipeline", return_value=mock_pipeline):
            client = create_app(self.paths).test_client()
            response = client.post(
                "/",
                data={"url": "http://www.knigovishte.bg/vijte/42-test?utm_source=portfolio#intro"},
            )

        self.assertEqual(response.status_code, 200)
        mock_pipeline.run.assert_called_once_with("https://www.knigovishte.bg/vijte/42-test")

    def test_post_rejects_non_knigovishte_url_before_pipeline_runs(self) -> None:
        with patch("knigovishte_podcast.web.pipeline") as pipeline_factory:
            client = create_app(self.paths).test_client()
            response = client.post("/", data={"url": "https://example.com/not-allowed"})

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Only knigovishte.bg/vijte article URLs are supported.",
            response.get_data(as_text=True),
        )
        pipeline_factory.assert_not_called()

    def test_post_uses_latest_article_when_url_is_blank(self) -> None:
        mock_pipeline = Mock()
        mock_pipeline.run.return_value = self.plan
        selector = Mock()
        selector.select_article.return_value = self.article

        with patch("knigovishte_podcast.web.pipeline", return_value=mock_pipeline):
            with patch("knigovishte_podcast.web.ArticleSelector", return_value=selector):
                client = create_app(self.paths).test_client()
                response = client.post("/", data={"url": ""})

        self.assertEqual(response.status_code, 200)
        selector.select_article.assert_called_once_with()
        mock_pipeline.run.assert_called_once_with(self.article.source_url)
        page = response.get_data(as_text=True)
        self.assertIn("Your episode is ready.", page)
        self.assertNotIn("No URL was provided, so the latest article was selected automatically.", page)

    def test_post_uses_filters_when_url_is_blank(self) -> None:
        mock_pipeline = Mock()
        mock_pipeline.run.return_value = self.plan
        selector = Mock()
        selector.select_article.return_value = self.article

        with patch("knigovishte_podcast.web.pipeline", return_value=mock_pipeline):
            with patch("knigovishte_podcast.web.ArticleSelector", return_value=selector):
                client = create_app(self.paths).test_client()
                response = client.post(
                    "/",
                    data={"url": "", "min_length": "5", "max_length": "20", "category": "nauka"},
                )

        self.assertEqual(response.status_code, 200)
        selector.select_article.assert_called_once_with(
            article_filter=ArticleFilter(min_length=5, max_length=20, category="nauka")
        )
        mock_pipeline.run.assert_called_once_with(self.article.source_url)
        page = response.get_data(as_text=True)
        self.assertIn("Your episode is ready.", page)
        self.assertNotIn(
            "No URL was provided, so a matching article was selected from the requested filters.",
            page,
        )

    def test_post_reports_invalid_filter_range(self) -> None:
        client = create_app(self.paths).test_client()

        response = client.post("/", data={"url": "", "min_length": "10", "max_length": "5"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Minimum length cannot be greater than maximum length.", response.get_data(as_text=True))

    def test_post_rejects_invalid_category_before_selector_runs(self) -> None:
        with patch("knigovishte_podcast.web.ArticleSelector") as selector_factory:
            with patch("knigovishte_podcast.web.pipeline") as pipeline_factory:
                client = create_app(self.paths).test_client()
                response = client.post("/", data={"url": "", "category": "not-a-real-category"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Unsupported category: not-a-real-category", response.get_data(as_text=True))
        selector_factory.assert_not_called()
        pipeline_factory.assert_not_called()

    def test_post_rejects_overlong_url_before_pipeline_runs(self) -> None:
        with patch("knigovishte_podcast.web.pipeline") as pipeline_factory:
            client = create_app(self.paths).test_client()
            response = client.post("/", data={"url": f"https://www.knigovishte.bg/vijte/42-{'a' * 2100}"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Article URL is too long.", response.get_data(as_text=True))
        pipeline_factory.assert_not_called()

    def test_post_reports_existing_audio_for_duplicate_article(self) -> None:
        existing_audio_path = self.paths.audio / "existing.mp3"
        existing_audio_path.write_bytes(b"audio")
        mock_pipeline = Mock()
        mock_pipeline.run.side_effect = DuplicateArticleError(
            article=self.article,
            audio_path=existing_audio_path,
        )

        with patch("knigovishte_podcast.web.pipeline", return_value=mock_pipeline):
            client = create_app(self.paths).test_client()
            response = client.post("/", data={"url": self.article.source_url})

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Your episode is ready.", page)
        self.assertNotIn("Existing audio reused", page)
        self.assertNotIn(str(self.paths.data), page)
        self.assertNotIn("file:///", page)
        self.assertNotIn(str(existing_audio_path.resolve()), page)
        self.assertNotIn(f'href="{existing_audio_path.resolve().as_uri()}"', page)

    def test_post_reports_langbly_timeout_with_deliberate_message(self) -> None:
        mock_pipeline = Mock()
        mock_pipeline.run.side_effect = LangblyTimeoutError(
            "Langbly timed out after 12s per endpoint while trying "
            "eu.langbly.com, api.langbly.com. No translation was returned."
        )

        with patch("knigovishte_podcast.web.pipeline", return_value=mock_pipeline):
            client = create_app(self.paths).test_client()
            response = client.post("/", data={"url": self.article.source_url})

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Pipeline failed", page)
        self.assertIn(
            "Langbly timed out after 12s per endpoint while trying eu.langbly.com, "
            "api.langbly.com. No translation was returned.",
            page,
        )
        self.assertIn(
            "The episode was not generated; please try again in a few minutes.",
            page,
        )

    def test_post_hides_unexpected_error_details(self) -> None:
        mock_pipeline = Mock()
        mock_pipeline.run.side_effect = RuntimeError("secret stack detail")

        with patch("knigovishte_podcast.web.pipeline", return_value=mock_pipeline):
            client = create_app(self.paths).test_client()
            response = client.post("/", data={"url": self.article.source_url})

        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn(UNEXPECTED_ERROR_MESSAGE, page)
        self.assertNotIn("secret stack detail", page)
