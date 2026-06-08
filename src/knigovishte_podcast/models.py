from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Article:
    source_url: str
    title_bg: str
    sentences_bg: tuple[str, ...]


@dataclass(frozen=True)
class Translation:
    title_en: str
    sentences_en: tuple[str, ...]


@dataclass(frozen=True)
class PodcastPlan:
    article: Article
    translation: Translation
    script_text: str
    script_path: Path
    audio_path: Path
    article_html_path: Path | None = None
