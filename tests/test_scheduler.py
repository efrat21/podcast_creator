from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

from knigovishte_podcast.config import ProjectPaths
from knigovishte_podcast.models import Article, PodcastPlan, Translation
from knigovishte_podcast.pipeline import ArticleToPodcastPipeline
from knigovishte_podcast.services.article_selector import ArticleSelector
from knigovishte_podcast.services.dedup import DuplicateArticleError
from knigovishte_podcast.services.scheduler import (
    DailyEpisodeScheduler,
    SchedulerState,
)


class TestSchedulerState(unittest.TestCase):
    def test_to_dict_and_from_dict_roundtrip(self) -> None:
        state = SchedulerState(
            last_check_time="2026-04-19T10:30:00",
            last_article_url="https://example.com/article",
            last_episode_path="data/audio/episode.mp3",
        )
        data = state.to_dict()
        restored = SchedulerState.from_dict(data)
        self.assertEqual(state, restored)

    def test_optional_fields(self) -> None:
        state = SchedulerState(last_check_time="2026-04-19T10:30:00")
        self.assertIsNone(state.last_article_url)
        self.assertIsNone(state.last_episode_path)

        data = state.to_dict()
        restored = SchedulerState.from_dict(data)
        self.assertEqual(state, restored)


class TestDailyEpisodeScheduler(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = Path(__file__).resolve().parent / "_artifacts" / "scheduler_test"
        self.test_dir.mkdir(parents=True, exist_ok=True)

        self.paths = ProjectPaths(
            root=self.test_dir,
            data=self.test_dir / "data",
            articles=self.test_dir / "data" / "articles",
            scripts=self.test_dir / "data" / "scripts",
            audio=self.test_dir / "data" / "audio",
        )
        self.paths.ensure()

        self.mock_pipeline = Mock(spec=ArticleToPodcastPipeline)
        self.mock_selector = Mock(spec=ArticleSelector)

        self.scheduler = DailyEpisodeScheduler(
            pipeline=self.mock_pipeline,
            article_selector=self.mock_selector,
            paths=self.paths,
        )
        self.scheduler._rebuild_rss_and_push = Mock()

        # Clean up state file
        if self.scheduler.state_path.exists():
            self.scheduler.state_path.unlink()

    def tearDown(self) -> None:
        if self.scheduler.state_path.exists():
            self.scheduler.state_path.unlink()

    def test_check_and_generate_first_run_success(self) -> None:
        """First run with no prior state should generate an episode."""
        article = Article(
            source_url="https://knigovishte.bg/article/123",
            title_bg="Тест заглавие",
            sentences_bg=["Изречение едно.", "Изречение две."],
        )
        audio_path = self.paths.audio / "article-123.mp3"
        audio_path.touch()

        plan = PodcastPlan(
            article=article,
            translation=Translation(title_en="Test Title", sentences_en=["One.", "Two."]),
            script_text="Bulgarian:\nТест заглавие\n\nEnglish:\nTest Title\n",
            script_path=self.paths.scripts / "article-123.txt",
            audio_path=audio_path,
            article_html_path=None,
        )

        self.mock_selector.select_article.return_value = article
        self.mock_pipeline.run.return_value = plan

        result = self.scheduler.check_and_generate()

        self.assertTrue(result.new_episode_created)
        self.assertEqual(result.article_url, article.source_url)
        self.assertEqual(result.episode_path, audio_path)
        self.assertIsNone(result.skip_reason)

        # State should be saved
        state = self.scheduler._load_state()
        assert state is not None
        self.assertEqual(state.last_article_url, article.source_url)

    def test_check_and_generate_same_article_skips(self) -> None:
        """Running again with the same article should skip generation."""
        article = Article(
            source_url="https://knigovishte.bg/article/123",
            title_bg="Тест заглавие",
            sentences_bg=["Изречение едно."],
        )

        # Save prior state
        prior_state = SchedulerState(
            last_check_time=(datetime.now() - timedelta(days=1)).isoformat(),
            last_article_url=article.source_url,
            last_episode_path="data/audio/article-123.mp3",
        )
        self.scheduler._save_state(prior_state)

        self.mock_selector.select_article.return_value = article

        result = self.scheduler.check_and_generate()

        self.assertFalse(result.new_episode_created)
        self.assertEqual(result.article_url, article.source_url)
        self.assertEqual(result.skip_reason, "Latest article already processed")
        self.mock_pipeline.run.assert_not_called()

    def test_check_and_generate_duplicate_article_error(self) -> None:
        """Duplicate article content should be handled gracefully."""
        article = Article(
            source_url="https://knigovishte.bg/article/456",
            title_bg="Ново заглавие",
            sentences_bg=["Ново изречение."],
        )
        audio_path = self.paths.audio / "article-456.mp3"
        audio_path.touch()

        self.mock_selector.select_article.return_value = article
        self.mock_pipeline.run.side_effect = DuplicateArticleError(
            article=article, audio_path=audio_path
        )

        result = self.scheduler.check_and_generate()

        self.assertFalse(result.new_episode_created)
        self.assertEqual(result.article_url, article.source_url)
        self.assertEqual(result.episode_path, audio_path)
        self.assertIn("duplicate", result.skip_reason.lower())

        # State should be updated
        state = self.scheduler._load_state()
        assert state is not None
        self.assertEqual(state.last_article_url, article.source_url)

    def test_check_and_generate_fetch_error(self) -> None:
        """Network errors should be reported gracefully."""
        self.mock_selector.select_article.side_effect = RuntimeError("Network timeout")

        result = self.scheduler.check_and_generate()

        self.assertFalse(result.new_episode_created)
        self.assertIsNone(result.article_url)
        self.assertIn("Failed to fetch", result.skip_reason)

    def test_check_and_generate_fetch_error_updates_state(self) -> None:
        """Fetch error should still update state to avoid same-day retry spam."""
        self.mock_selector.select_article.side_effect = RuntimeError("Network timeout")

        result = self.scheduler.check_and_generate()

        self.assertFalse(result.new_episode_created)
        # State should be saved with today's timestamp
        state = self.scheduler._load_state()
        assert state is not None
        self.assertEqual(state.last_check_time, result.checked_at)
        # After state update, should_check_today should return False
        self.assertFalse(self.scheduler.should_check_today())

    def test_check_and_generate_pipeline_error(self) -> None:
        """Pipeline errors should be caught and daemon should survive."""
        article = Article(
            source_url="https://knigovishte.bg/article/789",
            title_bg="Ново заглавие",
            sentences_bg=["Изречение."],
        )
        self.mock_selector.select_article.return_value = article
        self.mock_pipeline.run.side_effect = ValueError("Translation service unavailable")

        result = self.scheduler.check_and_generate()

        self.assertFalse(result.new_episode_created)
        self.assertEqual(result.article_url, article.source_url)
        self.assertIn("Pipeline error", result.skip_reason)
        self.assertIn("Translation service unavailable", result.skip_reason)

    def test_check_and_generate_pipeline_error_updates_state(self) -> None:
        """Pipeline error should update state to avoid same-day retry spam."""
        article = Article(
            source_url="https://knigovishte.bg/article/789",
            title_bg="Ново заглавие",
            sentences_bg=["Изречение."],
        )
        self.mock_selector.select_article.return_value = article
        self.mock_pipeline.run.side_effect = RuntimeError("Audio generation failed")

        result = self.scheduler.check_and_generate()

        self.assertFalse(result.new_episode_created)
        # State should be saved with today's timestamp and the article URL
        state = self.scheduler._load_state()
        assert state is not None
        self.assertEqual(state.last_check_time, result.checked_at)
        self.assertEqual(state.last_article_url, article.source_url)
        # After state update, should_check_today should return False
        self.assertFalse(self.scheduler.should_check_today())

    def test_should_check_today_no_prior_state(self) -> None:
        """Should check if there's no prior state."""
        self.assertTrue(self.scheduler.should_check_today())

    def test_should_check_today_already_checked(self) -> None:
        """Should not check if already checked today."""
        state = SchedulerState(
            last_check_time=datetime.now().isoformat(),
            last_article_url="https://example.com/article",
        )
        self.scheduler._save_state(state)

        self.assertFalse(self.scheduler.should_check_today())

    def test_should_check_today_checked_yesterday(self) -> None:
        """Should check if last check was yesterday."""
        yesterday = datetime.now() - timedelta(days=1)
        state = SchedulerState(
            last_check_time=yesterday.isoformat(),
            last_article_url="https://example.com/article",
        )
        self.scheduler._save_state(state)

        self.assertTrue(self.scheduler.should_check_today())

    def test_load_and_save_state_roundtrip(self) -> None:
        """State should persist correctly."""
        state = SchedulerState(
            last_check_time="2026-04-19T12:00:00",
            last_article_url="https://example.com/test",
            last_episode_path="data/audio/test.mp3",
        )

        self.scheduler._save_state(state)
        loaded = self.scheduler._load_state()

        self.assertEqual(loaded, state)

    def test_load_state_missing_file(self) -> None:
        """Should return None if state file doesn't exist."""
        self.assertIsNone(self.scheduler._load_state())

    def test_load_state_corrupted_file(self) -> None:
        """Should return None if state file is corrupted."""
        self.scheduler.state_path.write_text("not valid json", encoding="utf-8")
        self.assertIsNone(self.scheduler._load_state())

    def test_run_daemon_successful_check_does_not_raise(self) -> None:
        """run_daemon should handle a successful check with skip_reason=None without raising a TypeError."""
        from unittest.mock import patch
        from knigovishte_podcast.services.scheduler import DailyCheckResult

        success_result = DailyCheckResult(
            checked_at=datetime.now().isoformat(),
            new_episode_created=True,
            article_url="https://example.com/article",
            episode_path=Path("dummy.mp3"),
            skip_reason=None,
        )
        self.scheduler.check_and_generate = Mock(return_value=success_result)

        should_check_mock = Mock(side_effect=[True, KeyboardInterrupt("Stop loop")])
        self.scheduler.should_check_today = should_check_mock

        with patch("knigovishte_podcast.services.scheduler.time.sleep") as mock_sleep:
            self.scheduler.run_daemon(check_interval_seconds=10)
            mock_sleep.assert_called_once_with(10)

    def test_check_and_generate_calls_rebuild_rss_and_push(self) -> None:
        """Should call _rebuild_rss_and_push on successful run."""
        article = Article(
            source_url="https://knigovishte.bg/article/123",
            title_bg="Тест заглавие",
            sentences_bg=["Изречение едно."],
        )
        audio_path = self.paths.audio / "article-123.mp3"
        audio_path.touch()

        plan = PodcastPlan(
            article=article,
            translation=Translation(title_en="Test Title", sentences_en=["One."]),
            script_text="Bulgarian:\nТест заглавие\n\nEnglish:\nTest Title\n",
            script_path=self.paths.scripts / "article-123.txt",
            audio_path=audio_path,
            article_html_path=None,
        )

        self.mock_selector.select_article.return_value = article
        self.mock_pipeline.run.return_value = plan

        rebuild_mock = Mock()
        self.scheduler._rebuild_rss_and_push = rebuild_mock

        result = self.scheduler.check_and_generate()

        self.assertTrue(result.new_episode_created)
        rebuild_mock.assert_called_once()

    def test_check_and_generate_does_not_call_rebuild_rss_and_push_on_duplicate(self) -> None:
        """Should not call _rebuild_rss_and_push on duplicate."""
        article = Article(
            source_url="https://knigovishte.bg/article/123",
            title_bg="Тест заглавие",
            sentences_bg=["Изречение едно."],
        )
        self.mock_selector.select_article.return_value = article
        self.mock_pipeline.run.side_effect = DuplicateArticleError(article=article, audio_path=Path("dummy.mp3"))

        rebuild_mock = Mock()
        self.scheduler._rebuild_rss_and_push = rebuild_mock

        result = self.scheduler.check_and_generate()

        self.assertFalse(result.new_episode_created)
        rebuild_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
