from __future__ import annotations

import re
from abc import ABC, abstractmethod
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from ..models import Article


class ArticleFetcher(ABC):
    @abstractmethod
    def fetch(self, url: str) -> Article:
        raise NotImplementedError


class KnigovishteArticleFetcher(ArticleFetcher):
    def __init__(self, *, timeout: float = 20.0) -> None:
        self.timeout = timeout

    def fetch(self, url: str) -> Article:
        html = self.fetch_html(url)
        return self.parse_html(url, html)

    def fetch_html(self, url: str) -> str:
        normalized_url = _normalize_knigovishte_url(url)
        request = Request(
            normalized_url,
            headers={
                "User-Agent": "knigovishte-podcast/0.1",
                "Accept-Language": "bg,en;q=0.8",
            },
        )
        with urlopen(request, timeout=self.timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")

    def parse_html(self, url: str, html: str) -> Article:
        normalized_url = _normalize_knigovishte_url(url)
        parser = _KnigovishteArticleParser()
        parser.feed(html)
        parser.close()

        title_bg = _clean_text(parser.article_title or parser.page_title)
        if not title_bg:
            raise ValueError("Could not find a Knigovishte article title in the page.")

        sentences_bg = _extract_sentences(parser.content_parts)
        if not sentences_bg:
            raise ValueError("Could not extract article sentences from the page content.")

        return Article(
            source_url=_canonical_source_url(normalized_url, parser.canonical_url),
            title_bg=title_bg,
            sentences_bg=sentences_bg,
        )


_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source"}
_BLOCK_TAGS = {
    "article",
    "blockquote",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "ol",
    "p",
    "section",
    "table",
    "tr",
    "ul",
}
_IGNORED_TAGS = {"script", "style", "small"}


class _KnigovishteArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.page_title_parts: list[str] = []
        self.article_title_parts: list[str] = []
        self.content_parts: list[str] = []
        self.canonical_url = ""
        self._inside_page_title = False
        self._article_title_depth = 0
        self._content_depth = 0
        self._ignored_depth = 0

    @property
    def page_title(self) -> str:
        return "".join(self.page_title_parts)

    @property
    def article_title(self) -> str:
        return "".join(self.article_title_parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name: value or "" for name, value in attrs}

        if tag == "title":
            self._inside_page_title = True
            return

        if tag == "link" and "canonical" in attr_map.get("rel", "").lower():
            self.canonical_url = attr_map.get("href", "").strip()

        if (
            tag == "meta"
            and attr_map.get("property", "").strip().lower() == "og:url"
            and not self.canonical_url
        ):
            self.canonical_url = attr_map.get("content", "").strip()

        if self._content_depth and tag not in _VOID_TAGS:
            self._content_depth += 1

        if self._article_title_depth and tag not in _VOID_TAGS:
            self._article_title_depth += 1

        if _has_class(attr_map, "kmedia-article-title"):
            self._article_title_depth = 1

        if attr_map.get("id") == "kmedia-article-content":
            self._content_depth = 1

        if self._content_depth and tag in _IGNORED_TAGS:
            self._ignored_depth += 1
            return

        if self._content_depth and self._ignored_depth == 0 and (tag in _BLOCK_TAGS or tag == "br"):
            self.content_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._inside_page_title = False
            return

        if self._ignored_depth and tag in _IGNORED_TAGS:
            self._ignored_depth -= 1

        if self._content_depth:
            if self._ignored_depth == 0 and tag in _BLOCK_TAGS:
                self.content_parts.append("\n")
            if tag not in _VOID_TAGS:
                self._content_depth -= 1

        if self._article_title_depth and tag not in _VOID_TAGS:
            self._article_title_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._inside_page_title:
            self.page_title_parts.append(data)
        if self._article_title_depth:
            self.article_title_parts.append(data)
        if self._content_depth and self._ignored_depth == 0:
            self.content_parts.append(data)


def _has_class(attr_map: dict[str, str], expected_class: str) -> bool:
    return expected_class in attr_map.get("class", "").split()


def _normalize_knigovishte_url(url: str) -> str:
    candidate = url.strip()
    if not candidate:
        raise ValueError("Knigovishte URL is required.")
    if candidate.startswith("/"):
        candidate = urljoin("https://www.knigovishte.bg", candidate)
    elif "://" not in candidate:
        candidate = f"https://{candidate.lstrip('/')}"

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only HTTP(S) Knigovishte article URLs are supported.")
    if parsed.username or parsed.password:
        raise ValueError("Article URLs must not include credentials.")
    if parsed.netloc not in {"knigovishte.bg", "www.knigovishte.bg"}:
        raise ValueError("Only knigovishte.bg/vijte article URLs are supported.")
    path_segments = [segment for segment in parsed.path.split("/") if segment]
    if len(path_segments) < 2:
        raise ValueError("A specific Knigovishte article URL is required.")
    return urlunparse(
        parsed._replace(
            scheme="https",
            query="",
            fragment="",
        )
    )


def _canonical_source_url(requested_url: str, canonical_url: str) -> str:
    if not canonical_url:
        return requested_url
    parsed = urlparse(canonical_url)
    if parsed.netloc not in {"knigovishte.bg", "www.knigovishte.bg"}:
        return requested_url
    return canonical_url


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _extract_sentences(content_parts: list[str]) -> tuple[str, ...]:
    raw_text = "".join(content_parts).replace("\r", "").replace("\xa0", " ")
    blocks = [_clean_text(block) for block in raw_text.split("\n") if _clean_text(block)]
    sentences: list[str] = []
    for block in blocks:
        pieces = re.split(r"(?<=[.!?…])\s+", block)
        for piece in pieces:
            cleaned = _clean_text(piece)
            if cleaned:
                sentences.append(cleaned)
    return tuple(sentences)
