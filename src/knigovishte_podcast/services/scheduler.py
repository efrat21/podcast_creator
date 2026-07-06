from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import ProjectPaths
from ..pipeline import ArticleToPodcastPipeline
from ..services.article_selector import ArticleSelector
from ..services.dedup import DuplicateArticleError


@dataclass(frozen=True)
class SchedulerState:
    """Persistent state for the daily scheduler."""

    last_check_time: str
    last_article_url: str | None = None
    last_episode_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_check_time": self.last_check_time,
            "last_article_url": self.last_article_url,
            "last_episode_path": self.last_episode_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SchedulerState":
        return cls(
            last_check_time=data["last_check_time"],
            last_article_url=data.get("last_article_url"),
            last_episode_path=data.get("last_episode_path"),
        )


@dataclass(frozen=True)
class DailyCheckResult:
    """Result of a daily check operation."""

    checked_at: str
    new_episode_created: bool
    article_url: str | None = None
    episode_path: Path | None = None
    skip_reason: str | None = None


class DailyEpisodeScheduler:
    """
    Scheduler for daily episode automation.

    Checks for new articles and generates episodes when content changes.
    Uses the existing pipeline and deduplication to ensure idempotency.
    """

    def __init__(
        self,
        pipeline: ArticleToPodcastPipeline,
        article_selector: ArticleSelector,
        paths: ProjectPaths,
    ) -> None:
        self.pipeline = pipeline
        self.article_selector = article_selector
        self.paths = paths
        self.state_path = paths.data / "scheduler_state.json"

    def check_and_generate(self) -> DailyCheckResult:
        """
        Check for a new article and generate an episode if needed.

        Returns a result indicating what happened during this check.
        This method is idempotent - safe to run multiple times per day.
        """
        check_time = datetime.now().isoformat()
        state = self._load_state()

        try:
            latest_article = self.article_selector.select_article(article_filter=None)
        except Exception as e:
            # Blocker fix #2: Save state even on fetch failure to avoid same-day retry spam
            new_state = SchedulerState(
                last_check_time=check_time,
                last_article_url=state.last_article_url if state else None,
                last_episode_path=state.last_episode_path if state else None,
            )
            self._save_state(new_state)
            return DailyCheckResult(
                checked_at=check_time,
                new_episode_created=False,
                skip_reason=f"Failed to fetch latest article: {e}",
            )

        # Check if this is the same article we processed before
        if state and state.last_article_url == latest_article.source_url:
            print(f"last_article_url: {state.last_article_url}")
            print(f"last_episode_path: {state.last_episode_path}")
            return DailyCheckResult(
                checked_at=check_time,
                new_episode_created=False,
                article_url=latest_article.source_url,
                skip_reason="Latest article already processed",
            )

        # Try to generate the episode
        try:
            plan = self.pipeline.run(latest_article.source_url)
            new_state = SchedulerState(
                last_check_time=check_time,
                last_article_url=latest_article.source_url,
                last_episode_path=str(plan.audio_path.relative_to(self.paths.root)),
            )
            self._save_state(new_state)

            self._rebuild_rss_and_push()

            return DailyCheckResult(
                checked_at=check_time,
                new_episode_created=True,
                article_url=latest_article.source_url,
                episode_path=plan.audio_path,
            )

        except DuplicateArticleError as e:
            # Article content matches something we already have
            new_state = SchedulerState(
                last_check_time=check_time,
                last_article_url=latest_article.source_url,
                last_episode_path=(
                    str(e.audio_path.relative_to(self.paths.root))
                    if e.audio_path.is_absolute()
                    else str(e.audio_path)
                ),
            )
            self._save_state(new_state)

            return DailyCheckResult(
                checked_at=check_time,
                new_episode_created=False,
                article_url=latest_article.source_url,
                episode_path=e.audio_path,
                skip_reason="Article content already exists (duplicate)",
            )

        except Exception as e:
            # Blocker fix #1: Catch all pipeline exceptions to keep daemon alive
            # Save state to mark today's check as attempted even on failure
            new_state = SchedulerState(
                last_check_time=check_time,
                last_article_url=latest_article.source_url,
                last_episode_path=state.last_episode_path if state else None,
            )
            self._save_state(new_state)

            return DailyCheckResult(
                checked_at=check_time,
                new_episode_created=False,
                article_url=latest_article.source_url,
                skip_reason=f"Pipeline error: {e}",
            )

    def should_check_today(self) -> bool:
        """
        Determine if we should check for a new article today.

        Returns True if we haven't checked yet today, False otherwise.
        """
        state = self._load_state()
        if state is None:
            return True

        try:
            last_check = datetime.fromisoformat(state.last_check_time)
            today = datetime.now().date()
            return last_check.date() < today
        except (ValueError, AttributeError):
            return True

    def run_daemon(self, check_interval_seconds: int = 86400) -> None:
        """
        Run as a daemon, checking daily for new episodes.

        Args:
            check_interval_seconds: How often to wake up and check if it's time.
                                   Default is 86400 (1 day).

        This runs indefinitely. Use Ctrl+C to stop.
        """
        print("Daily episode scheduler started.")
        print("Will check once per day for new articles. Press Ctrl+C to stop.")
        print()

        try:
            while True:
                if self.should_check_today():
                    print(f"Checking for new article at {datetime.now().isoformat()}")
                    result = self.check_and_generate()
                    self._print_result(result)
                    print()
                    
                    if result.skip_reason and ("Failed to fetch" in result.skip_reason or "Pipeline error" in result.skip_reason):
                        self._notify_failure(f"Daily check failed: {result.skip_reason}")

                    if result.skip_reason and "Pipeline error" in result.skip_reason:
                        print("Encountered pipeline error, will retry in 5 minutes.")
                        time.sleep(300)  # Wait 5 minutes before next check on error
                    else:
                        time.sleep(check_interval_seconds)

        except KeyboardInterrupt:
            print("\nScheduler stopped by user.")

    @staticmethod
    def _notify_failure(message: str) -> None:
        """Show a Windows GUI message box if running on Windows and interactive."""
        try:
            import ctypes
            # MB_OK = 0x00000000, MB_ICONERROR = 0x00000010, MB_SYSTEMMODAL = 0x00001000
            ctypes.windll.user32.MessageBoxW(0, message, "Podcast Creator Alert", 0x10 | 0x1000)
        except Exception:
            pass

    def _load_state(self) -> SchedulerState | None:

        """Load scheduler state from disk."""
        if not self.state_path.exists():
            return None

        try:
            with self.state_path.open(encoding="utf-8") as f:
                data = json.load(f)
            return SchedulerState.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def _save_state(self, state: SchedulerState) -> None:
        """Save scheduler state to disk."""
        self.paths.data.mkdir(parents=True, exist_ok=True)
        temp_path = self.state_path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(state.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self.state_path)

    @staticmethod
    def _print_result(result: DailyCheckResult) -> None:
        """Print a human-readable result."""
        if result.new_episode_created:
            try:
                print("✓ New episode created!")
            except UnicodeEncodeError:
                print("[OK] New episode created!")
            print(f"  Article: {result.article_url}")
            print(f"  Audio: {result.episode_path}")
        else:
            try:
                print("○ No new episode")
            except UnicodeEncodeError:
                print("No new episode")
            if result.skip_reason:
                print(f"  Reason: {result.skip_reason}")
            if result.article_url:
                print(f"  Article checked: {result.article_url}")

    def _rebuild_rss_and_push(self) -> None:
        import subprocess
        from .rss import LocalRSSService

        # 1. Rebuild RSS feed
        try:
            rss_service = LocalRSSService(self.paths)
            public_base_url = rss_service.build_public_base_url(
                bind_host="0.0.0.0",
                port=8000,
            )
            rss_service.rebuild_feed(public_base_url)
            print("✓ RSS feed rebuilt successfully.")
        except Exception as e:
            print(f"Error rebuilding RSS feed: {e}")

        # 2. Git add, commit, and push
        root_str = str(self.paths.root)
        try:
            subprocess.run(["git", "add", "data/rss/"], check=True, cwd=root_str)
            subprocess.run(["git", "commit", "-m", "Add new podcast episode (automated daily check)"], check=False, cwd=root_str)
            subprocess.run(["git", "push"], check=True, cwd=root_str)
            print("✓ Pushed updated RSS feed to GitHub.")
        except Exception as git_exc:
            print(f"Git operations failed: {git_exc}")
