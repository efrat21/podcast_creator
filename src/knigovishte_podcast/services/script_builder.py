from __future__ import annotations

from ..models import Article, Translation


class PodcastScriptBuilder:
    def build(self, article: Article, translation: Translation) -> str:
        if len(article.sentences_bg) != len(translation.sentences_en):
            raise ValueError("Source and translated sentence counts must match.")

        lines = [
            "Welcome to today's bilingual Knigovishte story.",
            f"English title: {translation.title_en}",
            f"Bulgarian title: {article.title_bg}",
            "",
        ]

        for repeat_index in range(2):
            for english_sentence, bulgarian_sentence in zip(
                translation.sentences_en, article.sentences_bg
            ):
                lines.append(english_sentence)
                lines.append(bulgarian_sentence)
            if repeat_index == 0:
                lines.append("")
                lines.append("Let's hear that again.")
                lines.append("Сега ще го повторим.")
                lines.append("")

        lines.append("")
        lines.append("That's the end of this story. Thanks for listening!")
        return "\n".join(lines).strip()
