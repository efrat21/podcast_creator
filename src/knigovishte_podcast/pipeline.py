from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .config import ProjectPaths, TranslationConfig, episode_slug_from_url
from .models import PodcastPlan
from .services.dedup import ArticleAudioManifest, DuplicateArticleError
from .services.fetcher import ArticleFetcher, KnigovishteArticleFetcher
from .services.script_builder import PodcastScriptBuilder
from .services.translator import ArticleTranslator, LangblyTranslator
from .services.tts import PodcastAudioGenerator, build_default_audio_generator


@dataclass
class ArticleToPodcastPipeline:
    fetcher: ArticleFetcher
    translator: ArticleTranslator
    script_builder: PodcastScriptBuilder
    audio_generator: PodcastAudioGenerator
    paths: ProjectPaths
    article_manifest: ArticleAudioManifest
    use_cached_html: bool = True

    def run(self, url: str, progress_callback: Callable[[str], None] | None = None) -> PodcastPlan:
        self.paths.ensure()
        if progress_callback:
            progress_callback("fetching")
        article, article_html_path = self._load_article(url)
        existing_audio_path = self.article_manifest.find_existing_audio(article)
        if existing_audio_path is not None:
            raise DuplicateArticleError(article=article, audio_path=existing_audio_path)
        if progress_callback:
            progress_callback("translating")
        translation = self.translator.translate(article)
        if progress_callback:
            progress_callback("synthesizing")
        script_text = self.script_builder.build(article, translation)
        episode_slug = episode_slug_from_url(article.source_url)
        script_path = self.paths.scripts / f"{episode_slug}.txt"
        script_path.write_text(script_text, encoding="utf-8")
        audio_path = self.audio_generator.generate(script_text, episode_slug)
        self.article_manifest.record(article, audio_path)
        return PodcastPlan(
            article=article,
            translation=translation,
            script_text=script_text,
            script_path=script_path,
            audio_path=audio_path,
            article_html_path=article_html_path,
        )

    def _load_article(self, url: str):
        requested_slug = episode_slug_from_url(url)
        requested_cache_path = self.paths.articles / f"{requested_slug}.html"

        fetch_html = getattr(self.fetcher, "fetch_html", None)
        parse_html = getattr(self.fetcher, "parse_html", None)
        if callable(fetch_html) and callable(parse_html):
            if self.use_cached_html and requested_cache_path.exists():
                html = requested_cache_path.read_text(encoding="utf-8")
            else:
                html = fetch_html(url)
            article = parse_html(url, html)
            article_cache_path = self.paths.articles / f"{episode_slug_from_url(article.source_url)}.html"
            article_cache_path.write_text(html, encoding="utf-8")
            return article, article_cache_path

        return self.fetcher.fetch(url), None


def pipeline(
    *,
    paths: ProjectPaths | None = None,
    translation_config: TranslationConfig | None = None,
    fetcher: ArticleFetcher | None = None,
    translator: ArticleTranslator | None = None,
    script_builder: PodcastScriptBuilder | None = None,
    audio_generator: PodcastAudioGenerator | None = None,
    article_manifest: ArticleAudioManifest | None = None,
    use_cached_html: bool = True,
) -> ArticleToPodcastPipeline:
    project_paths = paths or ProjectPaths.from_root()
    configured_translator = translator or LangblyTranslator(
        translation_config or TranslationConfig.from_env(project_paths.root)
    )
    return ArticleToPodcastPipeline(
        fetcher=fetcher or KnigovishteArticleFetcher(),
        translator=configured_translator,
        script_builder=script_builder or PodcastScriptBuilder(),
        audio_generator=audio_generator or build_default_audio_generator(),
        paths=project_paths,
        article_manifest=article_manifest or ArticleAudioManifest.for_paths(project_paths),
        use_cached_html=use_cached_html,
    )
