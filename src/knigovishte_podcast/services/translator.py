from __future__ import annotations

import time
from abc import ABC, abstractmethod
from urllib.parse import urlparse

import requests

from ..config import TranslationConfig
from ..models import Article, Translation

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class ArticleTranslator(ABC):
    @abstractmethod
    def translate(self, article: Article) -> Translation:
        raise NotImplementedError


class PlaceholderTranslator(ArticleTranslator):
    def translate(self, article: Article) -> Translation:
        raise NotImplementedError(
            "Translation is not implemented yet. Add the chosen provider behind this interface."
        )


class LangblyTimeoutError(RuntimeError):
    """Raised when Langbly does not respond before the configured timeout."""


class LangblyTranslator(ArticleTranslator):
    """Translate articles using Langbly's Google Translate v2 compatible API."""

    def __init__(self, config: TranslationConfig) -> None:
        self.config = config

    def translate(self, article: Article) -> Translation:
        """Translate article title and sentences from Bulgarian to English."""
        texts_to_translate = [article.title_bg] + list(article.sentences_bg)
        translated_texts = self._translate_batch(texts_to_translate)
        title_en = translated_texts[0]
        sentences_en = tuple(translated_texts[1:])

        return Translation(title_en=title_en, sentences_en=sentences_en)

    def _translate_batch(self, texts: list[str]) -> list[str]:
        """Translate a batch of texts via Langbly API."""
        if not texts:
            return []

        payload = {
            "q": texts,
            "source": self.config.source_lang,
            "target": self.config.target_lang,
            "key": self.config.api_key,
        }
        headers = {"Authorization": f"Bearer {self.config.api_key}"}
        last_request_exception: requests.exceptions.RequestException | None = None
        last_retryable_http_error: RuntimeError | None = None
        last_timeout_exception: requests.exceptions.Timeout | None = None
        base_urls = self.config.all_base_urls()

        for attempt in range(self.config.max_retries + 1):
            for base_url in base_urls:
                response: requests.Response | None = None
                url = f"{base_url.rstrip('/')}/language/translate/v2"
                try:
                    response = requests.post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=self.config.timeout_seconds,
                    )
                    response.raise_for_status()
                    return self._parse_response(response, texts)
                except requests.exceptions.HTTPError as exc:
                    error_response = exc.response or response
                    status_code = getattr(error_response, "status_code", "unknown")
                    response_text = getattr(error_response, "text", "")
                    runtime_error = RuntimeError(
                        f"Langbly API error: {status_code} {response_text}".strip()
                    )
                    if status_code not in RETRYABLE_STATUS_CODES:
                        raise runtime_error from exc
                    if status_code == 408:
                        last_retryable_http_error = self._build_timeout_error(base_urls)
                        continue
                    last_retryable_http_error = runtime_error
                except requests.exceptions.RequestException as exc:
                    last_request_exception = exc
                    if isinstance(exc, requests.exceptions.Timeout):
                        last_timeout_exception = exc

            if attempt < self.config.max_retries and self.config.retry_backoff_seconds > 0:
                time.sleep(self.config.retry_backoff_seconds * (2**attempt))

        if last_timeout_exception is not None:
            raise self._build_timeout_error(base_urls) from last_timeout_exception
        if last_request_exception is not None:
            raise RuntimeError(
                self._format_connection_error(last_request_exception, base_urls)
            ) from last_request_exception
        if last_retryable_http_error is not None:
            raise last_retryable_http_error

        raise RuntimeError("Failed to connect to Langbly API")

    def _parse_response(self, response: requests.Response, texts: list[str]) -> list[str]:
        try:
            data = response.json()
            translations = data.get("data", {}).get("translations")
            if not isinstance(translations, list) or len(translations) != len(texts):
                raise ValueError("Unexpected translation count in response")

            translated_texts: list[str] = []
            for translation in translations:
                translated_text = translation.get("translatedText")
                if not isinstance(translated_text, str) or not translated_text.strip():
                    raise ValueError("Missing translatedText in response")
                translated_texts.append(translated_text.strip())
            return translated_texts
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Failed to parse Langbly API response: {response.text}"
            ) from exc

    def _format_connection_error(
        self,
        exc: requests.exceptions.RequestException,
        base_urls: tuple[str, ...],
    ) -> str:
        if len(base_urls) <= 1:
            return f"Failed to connect to Langbly API: {exc}"

        attempted_hosts = ", ".join(
            urlparse(base_url).netloc or base_url for base_url in base_urls
        )
        return (
            "Failed to connect to Langbly API after trying "
            f"{attempted_hosts}: {exc}"
        )

    def _build_timeout_error(self, base_urls: tuple[str, ...]) -> LangblyTimeoutError:
        timeout_seconds = f"{self.config.timeout_seconds:g}"
        if len(base_urls) <= 1:
            attempted_host = urlparse(base_urls[0]).netloc or base_urls[0]
            return LangblyTimeoutError(
                f"Langbly timed out after {timeout_seconds}s while contacting "
                f"{attempted_host}. No translation was returned."
            )

        attempted_hosts = ", ".join(
            urlparse(base_url).netloc or base_url for base_url in base_urls
        )
        return LangblyTimeoutError(
            f"Langbly timed out after {timeout_seconds}s per endpoint while trying "
            f"{attempted_hosts}. No translation was returned."
        )
