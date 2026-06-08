import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knigovishte_podcast.models import Article, Translation
from knigovishte_podcast.services.script_builder import PodcastScriptBuilder


class PodcastScriptBuilderTests(unittest.TestCase):
    def test_builds_bilingual_script_with_repeated_pairs(self) -> None:
        article = Article(
            source_url="https://www.knigovishte.bg/example",
            title_bg="Българско заглавие",
            sentences_bg=("Първо изречение.", "Второ изречение."),
        )
        translation = Translation(
            title_en="English Title",
            sentences_en=("First sentence.", "Second sentence."),
        )

        script = PodcastScriptBuilder().build(article, translation)

        expected = "\n".join(
            [
                "Welcome to today's bilingual Knigovishte story.",
                "English title: English Title",
                "Bulgarian title: Българско заглавие",
                "",
                "First sentence.",
                "Първо изречение.",
                "Second sentence.",
                "Второ изречение.",
                "",
                "Let's hear that again.",
                "Сега ще го повторим.",
                "",
                "First sentence.",
                "Първо изречение.",
                "Second sentence.",
                "Второ изречение.",
                "",
                "That's the end of this story. Thanks for listening!",
            ]
        )

        self.assertEqual(script, expected)

    def test_rejects_mismatched_sentence_counts(self) -> None:
        article = Article(
            source_url="https://www.knigovishte.bg/example",
            title_bg="Българско заглавие",
            sentences_bg=("Едно изречение.",),
        )
        translation = Translation(
            title_en="English Title",
            sentences_en=("One sentence.", "Extra sentence."),
        )

        with self.assertRaises(ValueError):
            PodcastScriptBuilder().build(article, translation)


if __name__ == "__main__":
    unittest.main()
