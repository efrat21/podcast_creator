import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knigovishte_podcast.models import Article
from knigovishte_podcast.services.article_selector import (
    ArticleFilter,
    ArticleListItem,
    ArticleSelector,
    KnigovishteListingParser,
)

LISTING_HTML = """
<!DOCTYPE html>
<html>
<body>
  <div class="article-list">
    <a href="/vijte/1234-first-article">First Article Title</a>
    <a href="/vijte/5678-second-article">Second Article Title</a>
    <a href="/about">About Page</a>
    <a href="/vijte/9012-third-article">Third Article</a>
  </div>
</body>
</html>
"""


class ArticleFilterTests(unittest.TestCase):
    def test_from_dict_creates_filter(self) -> None:
        data = {"min_length": 5, "max_length": 20, "category": "science"}
        article_filter = ArticleFilter.from_dict(data)

        self.assertEqual(article_filter.min_length, 5)
        self.assertEqual(article_filter.max_length, 20)
        self.assertEqual(article_filter.category, "science")

    def test_from_dict_handles_missing_fields(self) -> None:
        article_filter = ArticleFilter.from_dict({})

        self.assertIsNone(article_filter.min_length)
        self.assertIsNone(article_filter.max_length)
        self.assertIsNone(article_filter.category)

    def test_matches_accepts_article_within_length_bounds(self) -> None:
        article_filter = ArticleFilter(min_length=5, max_length=10)
        article = Article(
            source_url="https://example.com/article",
            title_bg="Title",
            sentences_bg=tuple(f"Sentence {i}" for i in range(7)),
        )

        self.assertTrue(article_filter.matches(article))

    def test_matches_rejects_article_below_min_length(self) -> None:
        article_filter = ArticleFilter(min_length=10)
        article = Article(
            source_url="https://example.com/article",
            title_bg="Title",
            sentences_bg=tuple(f"Sentence {i}" for i in range(5)),
        )

        self.assertFalse(article_filter.matches(article))

    def test_matches_rejects_article_above_max_length(self) -> None:
        article_filter = ArticleFilter(max_length=10)
        article = Article(
            source_url="https://example.com/article",
            title_bg="Title",
            sentences_bg=tuple(f"Sentence {i}" for i in range(15)),
        )

        self.assertFalse(article_filter.matches(article))

    def test_matches_accepts_article_with_no_filter(self) -> None:
        article_filter = ArticleFilter()
        article = Article(
            source_url="https://example.com/article",
            title_bg="Title",
            sentences_bg=tuple(f"Sentence {i}" for i in range(100)),
        )

        self.assertTrue(article_filter.matches(article))


class KnigovishteListingParserTests(unittest.TestCase):
    def test_parse_extracts_article_links(self) -> None:
        parser = KnigovishteListingParser()
        parser.feed(LISTING_HTML)
        parser.close()

        self.assertEqual(len(parser.articles), 3)
        self.assertEqual(
            parser.articles[0].url,
            "https://www.knigovishte.bg/vijte/1234-first-article",
        )
        self.assertEqual(parser.articles[0].title, "First Article Title")
        self.assertEqual(
            parser.articles[1].url,
            "https://www.knigovishte.bg/vijte/5678-second-article",
        )
        self.assertEqual(parser.articles[1].title, "Second Article Title")

    def test_parse_ignores_non_article_links(self) -> None:
        parser = KnigovishteListingParser()
        parser.feed(LISTING_HTML)
        parser.close()

        urls = [item.url for item in parser.articles]
        self.assertNotIn("https://www.knigovishte.bg/about", urls)


class ArticleSelectorTests(unittest.TestCase):
    def test_select_article_returns_latest_when_no_filter(self) -> None:
        mock_fetcher = MagicMock()
        expected_article = Article(
            source_url="https://www.knigovishte.bg/vijte/1234-first-article",
            title_bg="First Article",
            sentences_bg=("Sentence 1.", "Sentence 2."),
        )
        mock_fetcher.fetch.return_value = expected_article

        selector = ArticleSelector(fetcher=mock_fetcher)

        with patch.object(selector, "_fetch_article_list") as mock_list:
            mock_list.return_value = [
                ArticleListItem(
                    url="https://www.knigovishte.bg/vijte/1234-first-article",
                    title="First",
                ),
                ArticleListItem(
                    url="https://www.knigovishte.bg/vijte/5678-second-article",
                    title="Second",
                ),
            ]

            result = selector.select_article(article_filter=None)

            self.assertEqual(result, expected_article)
            mock_fetcher.fetch.assert_called_once_with(
                "https://www.knigovishte.bg/vijte/1234-first-article"
            )

    def test_select_article_returns_first_matching_article(self) -> None:
        mock_fetcher = MagicMock()
        first_article = Article(
            source_url="https://www.knigovishte.bg/vijte/1234-first-article",
            title_bg="First",
            sentences_bg=("S1.", "S2.", "S3."),
        )
        second_article = Article(
            source_url="https://www.knigovishte.bg/vijte/5678-second-article",
            title_bg="Second",
            sentences_bg=tuple(f"S{i}." for i in range(10)),
        )
        mock_fetcher.fetch.side_effect = [first_article, second_article]

        selector = ArticleSelector(fetcher=mock_fetcher)
        article_filter = ArticleFilter(min_length=5)

        with patch.object(selector, "_fetch_article_list") as mock_list:
            mock_list.return_value = [
                ArticleListItem(
                    url="https://www.knigovishte.bg/vijte/1234-first-article",
                    title="First",
                ),
                ArticleListItem(
                    url="https://www.knigovishte.bg/vijte/5678-second-article",
                    title="Second",
                ),
            ]

            result = selector.select_article(article_filter=article_filter)

            self.assertEqual(result, second_article)
            self.assertEqual(mock_fetcher.fetch.call_count, 2)

    def test_select_article_uses_category_listing_when_requested(self) -> None:
        mock_fetcher = MagicMock()
        expected_article = Article(
            source_url="https://www.knigovishte.bg/vijte/5678-category-article",
            title_bg="Category Article",
            sentences_bg=("Sentence 1.", "Sentence 2."),
        )
        mock_fetcher.fetch.return_value = expected_article

        selector = ArticleSelector(fetcher=mock_fetcher)
        article_filter = ArticleFilter(category="nauka")

        with patch.object(selector, "_fetch_article_list") as mock_list:
            mock_list.return_value = [
                ArticleListItem(
                    url="https://www.knigovishte.bg/vijte/5678-category-article",
                    title="Category Article",
                ),
            ]

            result = selector.select_article(article_filter=article_filter)

            self.assertEqual(result, expected_article)
            mock_list.assert_called_once_with("https://www.knigovishte.bg/vijte/category/nauka")
            mock_fetcher.fetch.assert_called_once_with(expected_article.source_url)

    def test_select_article_raises_when_no_match_found(self) -> None:
        mock_fetcher = MagicMock()
        short_article = Article(
            source_url="https://www.knigovishte.bg/vijte/1234-first-article",
            title_bg="Short",
            sentences_bg=("S1.",),
        )
        mock_fetcher.fetch.return_value = short_article

        selector = ArticleSelector(fetcher=mock_fetcher)
        article_filter = ArticleFilter(min_length=100)

        with patch.object(selector, "_fetch_article_list") as mock_list:
            mock_list.return_value = [
                ArticleListItem(
                    url="https://www.knigovishte.bg/vijte/1234-first-article",
                    title="Short",
                ),
            ]

            with self.assertRaises(ValueError) as ctx:
                selector.select_article(article_filter=article_filter, max_scan=5)

            self.assertIn("No article matching", str(ctx.exception))

    def test_select_article_rejects_unknown_category(self) -> None:
        selector = ArticleSelector(fetcher=MagicMock())

        with self.assertRaises(ValueError) as ctx:
            selector.select_article(article_filter=ArticleFilter(category="unknown-category"))

        self.assertIn("Unsupported category", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
