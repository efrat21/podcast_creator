import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knigovishte_podcast.services.fetcher import (
    KnigovishteArticleFetcher,
    _normalize_knigovishte_url,
)

ARTICLE_HTML = """
<!DOCTYPE html>
<html lang="bg">
  <head>
    <title>Колко тежи една лека муха?</title>
    <link rel="canonical" href="https://www.knigovishte.bg/vijte/1532-kolko-tezhi-edna-leka-muha" />
  </head>
  <body>
    <div class="kmedia-article-title">Колко тежи една лека муха?</div>
    <div id="kmedia-article-content" class="article-edited-content">
      <div class="fixTitles">
        <h2><strong>Колко мухи има по света?</strong></h2>
        По света летят много и най-различни мухи.<br />
        <br />
        Затова да се опитаме да изчислим колко тежи една муха!
        <small>Снимка: LOGAN WEAVER от Unsplash</small>
        <h2><strong>Колко тежи една муха?</strong></h2>
        Една <strong>тежка муха</strong> e 50 до 52 килограма, а една <strong>лека муха</strong> - около 47 килограма.<br />
        <img alt="" src="/js/fileman/Uploads/Вижте бокс.png" />
        Но, приема се, че средно тежи около 0.007 грама.
      </div>
    </div>
    <div id="comments">Това не е част от статията.</div>
  </body>
</html>
"""


class KnigovishteArticleFetcherTests(unittest.TestCase):
    def test_parse_html_extracts_title_canonical_url_and_sentences(self) -> None:
        article = KnigovishteArticleFetcher().parse_html(
            "https://www.knigovishte.bg/book/1532-kolko-tezhi-edna-leka-muha",
            ARTICLE_HTML,
        )

        self.assertEqual(
            article.source_url,
            "https://www.knigovishte.bg/vijte/1532-kolko-tezhi-edna-leka-muha",
        )
        self.assertEqual(article.title_bg, "Колко тежи една лека муха?")
        self.assertEqual(
            article.sentences_bg,
            (
                "Колко мухи има по света?",
                "По света летят много и най-различни мухи.",
                "Затова да се опитаме да изчислим колко тежи една муха!",
                "Колко тежи една муха?",
                "Една тежка муха e 50 до 52 килограма, а една лека муха - около 47 килограма.",
                "Но, приема се, че средно тежи около 0.007 грама.",
            ),
        )

    def test_parse_html_rejects_pages_without_article_content(self) -> None:
        with self.assertRaises(ValueError):
            KnigovishteArticleFetcher().parse_html(
                "https://www.knigovishte.bg/vijte/1234-test",
                "<html><head><title>Test</title></head><body><p>No article here.</p></body></html>",
            )


class NormalizeKnigovishteUrlTests(unittest.TestCase):
    def test_normalize_empty_string_raises_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _normalize_knigovishte_url("")
        self.assertIn("required", str(ctx.exception).lower())

    def test_normalize_whitespace_only_raises_error(self) -> None:
        with self.assertRaises(ValueError):
            _normalize_knigovishte_url("   ")

    def test_normalize_root_path_only_raises_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _normalize_knigovishte_url("https://www.knigovishte.bg/")
        self.assertIn("specific", str(ctx.exception).lower())

    def test_normalize_non_knigovishte_domain_raises_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _normalize_knigovishte_url("https://example.com/article/123")
        self.assertIn("only knigovishte", str(ctx.exception).lower())

    def test_normalize_relative_path_becomes_absolute(self) -> None:
        result = _normalize_knigovishte_url("/vijte/1532-test")
        self.assertEqual(result, "https://www.knigovishte.bg/vijte/1532-test")

    def test_normalize_host_only_without_scheme_raises_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _normalize_knigovishte_url("www.knigovishte.bg")
        self.assertIn("specific", str(ctx.exception).lower())

    def test_normalize_full_url_with_www(self) -> None:
        url = "https://www.knigovishte.bg/vijte/1532-kolko-tezhi-edna-leka-muha"
        result = _normalize_knigovishte_url(url)
        self.assertEqual(result, url)

    def test_normalize_full_url_without_www(self) -> None:
        url = "https://knigovishte.bg/vijte/1532-kolko-tezhi-edna-leka-muha"
        result = _normalize_knigovishte_url(url)
        self.assertEqual(result, url)

    def test_normalize_upgrades_http_and_strips_tracking_bits(self) -> None:
        result = _normalize_knigovishte_url(
            "http://www.knigovishte.bg/vijte/1532-test?utm_source=portfolio#intro"
        )
        self.assertEqual(result, "https://www.knigovishte.bg/vijte/1532-test")

    def test_normalize_url_with_credentials_raises_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            _normalize_knigovishte_url("https://user:pass@www.knigovishte.bg/vijte/1532-test")
        self.assertIn("credentials", str(ctx.exception).lower())

    def test_normalize_strips_whitespace(self) -> None:
        url = "  https://www.knigovishte.bg/vijte/1532-test  "
        result = _normalize_knigovishte_url(url)
        self.assertEqual(result, "https://www.knigovishte.bg/vijte/1532-test")


class FetchIntegrationTests(unittest.TestCase):
    def test_fetch_calls_fetch_html_and_parse_html(self) -> None:
        fetcher = KnigovishteArticleFetcher()
        fetcher.fetch_html = MagicMock(return_value=ARTICLE_HTML)

        article = fetcher.fetch(
            "https://www.knigovishte.bg/book/1532-kolko-tezhi-edna-leka-muha"
        )

        fetcher.fetch_html.assert_called_once()
        self.assertEqual(article.title_bg, "Колко тежи една лека муха?")
        self.assertGreater(len(article.sentences_bg), 0)

    def test_fetch_propagates_parse_errors(self) -> None:
        fetcher = KnigovishteArticleFetcher()
        fetcher.fetch_html = MagicMock(
            return_value="<html><body>No article content</body></html>"
        )

        with self.assertRaises(ValueError):
            fetcher.fetch("https://www.knigovishte.bg/book/123")


class ParserFallbackTests(unittest.TestCase):
    def test_parse_html_uses_page_title_when_article_title_missing(self) -> None:
        html = """
        <!DOCTYPE html>
        <html lang="bg">
          <head>
            <title>Page Title Only</title>
            <link rel="canonical" href="https://www.knigovishte.bg/vijte/123-test" />
          </head>
          <body>
            <div id="kmedia-article-content" class="article-edited-content">
              <div class="fixTitles">
                <h2>Some content heading</h2>
                Some article text here.
              </div>
            </div>
          </body>
        </html>
        """
        article = KnigovishteArticleFetcher().parse_html(
            "https://www.knigovishte.bg/vijte/123-test", html
        )
        self.assertEqual(article.title_bg, "Page Title Only")

    def test_parse_html_rejects_missing_both_titles(self) -> None:
        html = """
        <!DOCTYPE html>
        <html lang="bg">
          <head>
            <link rel="canonical" href="https://www.knigovishte.bg/vijte/123-test" />
          </head>
          <body>
            <div id="kmedia-article-content" class="article-edited-content">
              <div class="fixTitles">
                <h2>Some content</h2>
                Some text.
              </div>
            </div>
          </body>
        </html>
        """
        with self.assertRaises(ValueError) as ctx:
            KnigovishteArticleFetcher().parse_html(
                "https://www.knigovishte.bg/vijte/123-test", html
            )
        self.assertIn("title", str(ctx.exception).lower())

    def test_parse_html_uses_requested_url_when_canonical_missing(self) -> None:
        html = """
        <!DOCTYPE html>
        <html lang="bg">
          <head>
            <title>Test Article</title>
          </head>
          <body>
            <div class="kmedia-article-title">Test Article</div>
            <div id="kmedia-article-content" class="article-edited-content">
              <div class="fixTitles">
                <h2>Heading</h2>
                Article content here.
              </div>
            </div>
          </body>
        </html>
        """
        requested_url = "https://www.knigovishte.bg/vijte/456-test"
        article = KnigovishteArticleFetcher().parse_html(requested_url, html)
        self.assertEqual(article.source_url, requested_url)

    def test_parse_html_rejects_missing_article_content_div(self) -> None:
        html = """
        <!DOCTYPE html>
        <html lang="bg">
          <head>
            <title>Test Article</title>
          </head>
          <body>
            <div class="kmedia-article-title">Test Article</div>
            <p>This is not in the article content div.</p>
          </body>
        </html>
        """
        with self.assertRaises(ValueError) as ctx:
            KnigovishteArticleFetcher().parse_html(
                "https://www.knigovishte.bg/vijte/789-test", html
            )
        self.assertIn("sentences", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
