from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knigovishte_podcast.config import DEFAULT_LANGBLY_BASE_URL, TranslationConfig
from knigovishte_podcast.models import Article, Translation
from knigovishte_podcast.services.translator import (
    LangblyTimeoutError,
    LangblyTranslator,
)


class LangblyTranslatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = TranslationConfig(
            api_key="test_key",
            base_url="https://api.langbly.com",
        )
        self.article = Article(
            source_url="https://www.knigovishte.bg/vijte/42-test",
            title_bg="Тестна статия",
            sentences_bg=("Първо изречение.", "Второ изречение."),
        )

    def _mock_response(self, translations: list[dict[str, str]]) -> Mock:
        response = Mock(spec=requests.Response)
        response.json.return_value = {"data": {"translations": translations}}
        response.raise_for_status.return_value = None
        response.text = str(response.json.return_value)
        return response

    def test_translate_returns_title_and_sentences(self) -> None:
        response = self._mock_response(
            [
                {"translatedText": "Test Article"},
                {"translatedText": "First sentence."},
                {"translatedText": "Second sentence."},
            ]
        )

        with patch(
            "knigovishte_podcast.services.translator.requests.post",
            return_value=response,
        ):
            result = LangblyTranslator(self.config).translate(self.article)

        self.assertIsInstance(result, Translation)
        self.assertEqual(result.title_en, "Test Article")
        self.assertEqual(
            result.sentences_en,
            ("First sentence.", "Second sentence."),
        )

    def test_translate_sends_expected_payload_and_headers(self) -> None:
        response = self._mock_response(
            [
                {"translatedText": "Title"},
                {"translatedText": "Sentence 1"},
                {"translatedText": "Sentence 2"},
            ]
        )

        with patch(
            "knigovishte_podcast.services.translator.requests.post",
            return_value=response,
        ) as mock_post:
            LangblyTranslator(self.config).translate(self.article)

        mock_post.assert_called_once_with(
            "https://api.langbly.com/language/translate/v2",
            json={
                "q": ["Тестна статия", "Първо изречение.", "Второ изречение."],
                "source": "bg",
                "target": "en",
                "key": "test_key",
            },
            headers={"Authorization": "Bearer test_key"},
            timeout=60.0,
        )

    def test_translate_wraps_http_errors(self) -> None:
        response = Mock(spec=requests.Response)
        response.status_code = 401
        response.text = "Invalid API key"
        http_error = requests.exceptions.HTTPError("HTTP 401", response=response)
        response.raise_for_status.side_effect = http_error

        with patch(
            "knigovishte_podcast.services.translator.requests.post",
            return_value=response,
        ):
            with self.assertRaisesRegex(RuntimeError, "Langbly API error: 401 Invalid API key"):
                LangblyTranslator(self.config).translate(self.article)

    def test_translate_wraps_request_failures(self) -> None:
        with patch(
            "knigovishte_podcast.services.translator.requests.post",
            side_effect=requests.exceptions.ConnectionError("unreachable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Failed to connect to Langbly API"):
                LangblyTranslator(self.config).translate(self.article)

    def test_translate_fails_over_to_default_base_url_after_timeout(self) -> None:
        regional_config = TranslationConfig(
            api_key="test_key",
            base_url="https://eu.langbly.com",
            fallback_base_urls=(DEFAULT_LANGBLY_BASE_URL,),
        )
        response = self._mock_response(
            [
                {"translatedText": "Test Article"},
                {"translatedText": "First sentence."},
                {"translatedText": "Second sentence."},
            ]
        )

        with patch(
            "knigovishte_podcast.services.translator.requests.post",
            side_effect=[requests.exceptions.Timeout("timed out"), response],
        ) as mock_post:
            result = LangblyTranslator(regional_config).translate(self.article)

        self.assertEqual(result.title_en, "Test Article")
        self.assertEqual(mock_post.call_count, 2)
        first_call = mock_post.call_args_list[0]
        second_call = mock_post.call_args_list[1]
        self.assertEqual(first_call.args[0], "https://eu.langbly.com/language/translate/v2")
        self.assertEqual(second_call.args[0], "https://api.langbly.com/language/translate/v2")
        self.assertEqual(first_call.kwargs["json"], second_call.kwargs["json"])
        self.assertEqual(first_call.kwargs["headers"], second_call.kwargs["headers"])
        self.assertEqual(first_call.kwargs["timeout"], 60.0)
        self.assertEqual(second_call.kwargs["timeout"], 60.0)

    def test_translate_raises_deliberate_timeout_after_all_endpoints_time_out(self) -> None:
        regional_config = TranslationConfig(
            api_key="test_key",
            base_url="https://eu.langbly.com",
            fallback_base_urls=(DEFAULT_LANGBLY_BASE_URL,),
            timeout_seconds=12,
        )

        with patch(
            "knigovishte_podcast.services.translator.requests.post",
            side_effect=[
                requests.exceptions.ReadTimeout("read timed out"),
                requests.exceptions.ReadTimeout("read timed out"),
            ],
        ):
            with self.assertRaises(LangblyTimeoutError) as context:
                LangblyTranslator(regional_config).translate(self.article)

        self.assertEqual(
            str(context.exception),
            "Langbly timed out after 12s per endpoint while trying "
            "eu.langbly.com, api.langbly.com. No translation was returned.",
        )

    def test_translate_retries_retryable_server_errors(self) -> None:
        response = Mock(spec=requests.Response)
        response.status_code = 503
        response.text = "Unavailable"
        http_error = requests.exceptions.HTTPError("HTTP 503", response=response)
        response.raise_for_status.side_effect = http_error
        config = TranslationConfig(api_key="test_key", max_retries=1, retry_backoff_seconds=0)

        with patch(
            "knigovishte_podcast.services.translator.requests.post",
            side_effect=[response, self._mock_response(
                [
                    {"translatedText": "Title"},
                    {"translatedText": "Sentence 1"},
                    {"translatedText": "Sentence 2"},
                ]
            )],
        ) as mock_post:
            result = LangblyTranslator(config).translate(self.article)

        self.assertEqual(result.title_en, "Title")
        self.assertEqual(mock_post.call_count, 2)

    def test_translate_rejects_mismatched_batch_response(self) -> None:
        response = self._mock_response([{"translatedText": "Title only"}])

        with patch(
            "knigovishte_podcast.services.translator.requests.post",
            return_value=response,
        ):
            with self.assertRaisesRegex(RuntimeError, "Failed to parse Langbly API response"):
                LangblyTranslator(self.config).translate(self.article)

    def test_translate_rejects_blank_translated_text(self) -> None:
        response = self._mock_response(
            [
                {"translatedText": "Test Article"},
                {"translatedText": "   "},
                {"translatedText": "Second sentence."},
            ]
        )

        with patch(
            "knigovishte_podcast.services.translator.requests.post",
            return_value=response,
        ):
            with self.assertRaisesRegex(RuntimeError, "Failed to parse Langbly API response"):
                LangblyTranslator(self.config).translate(self.article)

    def test_translate_splits_large_batch_into_sub_batches(self) -> None:
        """Should split large translation batches into sub-batches of 15 and merge them."""
        large_article = Article(
            source_url="https://example.com",
            title_bg="Заглавие",
            sentences_bg=tuple(f"Изречение {i}." for i in range(20)),
        )
        
        response1 = self._mock_response([{"translatedText": f"Trans {i}"} for i in range(15)])
        response2 = self._mock_response([{"translatedText": f"Trans {i}"} for i in range(15, 21)])

        with patch(
            "knigovishte_podcast.services.translator.requests.post",
            side_effect=[response1, response2],
        ) as mock_post:
            result = LangblyTranslator(self.config).translate(large_article)

        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(result.title_en, "Trans 0")
        self.assertEqual(len(result.sentences_en), 20)
        self.assertEqual(result.sentences_en[0], "Trans 1")
        self.assertEqual(result.sentences_en[19], "Trans 20")


if __name__ == "__main__":
    unittest.main()
