from __future__ import annotations

import sys
import argparse
from pathlib import Path

from .config import ProjectPaths, TranslationConfig, episode_slug_from_url
from .models import Article, Translation
from .pipeline import pipeline as build_pipeline
from .services.article_selector import ArticleFilter, ArticleSelector
from .services.dedup import ArticleAudioManifest, DuplicateArticleError
from .services.fetcher import KnigovishteArticleFetcher
from .services.rss import LocalRSSService
from .services.scheduler import DailyEpisodeScheduler
from .services.script_builder import PodcastScriptBuilder
from .services.translator import LangblyTranslator
from .services.tts import AUDIO_FILE_EXTENSION, build_default_audio_generator

TRANSLATION_FILE_SUFFIX = ".translation.txt"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="knigovishte-podcast",
        description="Fetch, translate, script, and render Knigovishte articles to local podcast artifacts.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser(
        "plan",
        help="Create local data folders and print the planned output paths for a source URL.",
    )
    _add_url_argument(plan_parser)
    _add_filter_argument(plan_parser)

    fetch_parser = subparsers.add_parser(
        "fetch",
        help="Fetch a Knigovishte article, cache its HTML locally, and print the parsed summary.",
    )
    _add_url_argument(fetch_parser)
    _add_filter_argument(fetch_parser)
    _add_refresh_argument(fetch_parser)

    translate_parser = subparsers.add_parser(
        "translate",
        help="Fetch and translate a Knigovishte article, then save a translation text artifact.",
    )
    _add_url_argument(translate_parser)
    _add_filter_argument(translate_parser)
    _add_refresh_argument(translate_parser)

    build_script_parser = subparsers.add_parser(
        "build-script",
        help="Fetch, translate, and save the bilingual podcast script for a source URL.",
    )
    _add_url_argument(build_script_parser)
    _add_filter_argument(build_script_parser)
    _add_refresh_argument(build_script_parser)

    generate_audio_parser = subparsers.add_parser(
        "generate-audio",
        help="Fetch, translate, build the script, and generate the local podcast audio file.",
    )
    _add_url_argument(generate_audio_parser)
    _add_filter_argument(generate_audio_parser)
    _add_refresh_argument(generate_audio_parser)
    _add_voice_arguments(generate_audio_parser)

    run_parser = subparsers.add_parser(
        "run",
        help="Run the full fetch → translate → script → audio pipeline for a source URL.",
    )
    _add_url_argument(run_parser)
    _add_filter_argument(run_parser)
    _add_refresh_argument(run_parser)
    _add_voice_arguments(run_parser)

    web_parser = subparsers.add_parser(
        "web",
        help="Start a local Flask web UI for running the pipeline in a browser.",
    )
    web_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface for the local web server. Defaults to 127.0.0.1.",
    )
    web_parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port for the local web server. Defaults to 5000.",
    )

    daily_check_parser = subparsers.add_parser(
        "daily-check",
        help="Check for a new article today and generate an episode if needed. Idempotent - safe to run multiple times.",
    )
    _add_voice_arguments(daily_check_parser)

    daily_daemon_parser = subparsers.add_parser(
        "daily-daemon",
        help="Run as a background daemon, checking once per day for new articles.",
    )
    daily_daemon_parser.add_argument(
        "--interval",
        type=int,
        default=3600,
        help="How often to wake up and check if it's time for a daily check (seconds). Default: 3600 (1 hour).",
    )
    _add_voice_arguments(daily_daemon_parser)

    local_rss_parser = subparsers.add_parser(
        "local-rss-delivery",
        help="Stage a local RSS feed from existing audio artifacts and optionally serve it over the LAN.",
    )
    local_rss_parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host interface for the local RSS server. Defaults to 0.0.0.0.",
    )
    local_rss_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for the local RSS server. Defaults to 8000.",
    )
    local_rss_parser.add_argument(
        "--public-host",
        help="Reachable host name or LAN IP to embed in podcast feed URLs.",
    )
    local_rss_parser.add_argument(
        "--no-serve",
        action="store_true",
        help="Rebuild the local RSS feed without starting the HTTP server.",
    )

    return parser


def _add_url_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", help="Knigovishte article URL.")


def _add_filter_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--filter",
        type=Path,
        help="Path to JSON file with filter criteria (min_length, max_length, category).",
    )


def _add_refresh_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore any cached article HTML and fetch the page again.",
    )


def _add_voice_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--en-voice",
        metavar="NAME",
        help="English voice to use for English lines. Defaults to Google Cloud "
        "en-US-Standard-F; other valid Google English voice names also stay on the "
        "Google path, while local pyttsx3 voice names (or substrings) still work "
        "when passed explicitly.",
    )
    parser.add_argument(
        "--bg-voice",
        metavar="NAME",
        help="Bulgarian TTS voice to use for Bulgarian lines. Defaults to the "
        "Google Cloud voice bg-BG-Standard-B; local pyttsx3 voice names still work "
        "when passed explicitly.",
    )


def _load_article(
    paths: ProjectPaths,
    url: str,
    *,
    fetcher: KnigovishteArticleFetcher | None = None,
    use_cached_html: bool = True,
) -> tuple[Article, Path, bool]:
    selected_fetcher = fetcher or KnigovishteArticleFetcher()
    requested_slug = episode_slug_from_url(url)
    requested_cache_path = paths.articles / f"{requested_slug}.html"

    if use_cached_html and requested_cache_path.exists():
        html = requested_cache_path.read_text(encoding="utf-8")
        article = selected_fetcher.parse_html(url, html)
        used_cached_html = True
    else:
        html = selected_fetcher.fetch_html(url)
        article = selected_fetcher.parse_html(url, html)
        used_cached_html = False

    article_cache_path = paths.articles / f"{episode_slug_from_url(article.source_url)}.html"
    article_cache_path.write_text(html, encoding="utf-8")
    return article, article_cache_path, used_cached_html


def _translate_article(
    paths: ProjectPaths,
    article: Article,
) -> tuple[Translation, Path]:
    translator = LangblyTranslator(TranslationConfig.from_env(paths.root))
    translation = translator.translate(article)
    translation_path = _translation_output_path(paths, article.source_url)
    translation_path.write_text(
        _render_translation_text(article, translation),
        encoding="utf-8",
    )
    return translation, translation_path


def _translation_output_path(paths: ProjectPaths, source_url: str) -> Path:
    return paths.scripts / f"{episode_slug_from_url(source_url)}{TRANSLATION_FILE_SUFFIX}"


def _script_output_path(paths: ProjectPaths, source_url: str) -> Path:
    return paths.scripts / f"{episode_slug_from_url(source_url)}.txt"


def _render_translation_text(article: Article, translation: Translation) -> str:
    lines = [
        f"Source URL: {article.source_url}",
        f"Bulgarian title: {article.title_bg}",
        f"English title: {translation.title_en}",
        "",
    ]
    for index, (english_sentence, bulgarian_sentence) in enumerate(
        zip(translation.sentences_en, article.sentences_bg),
        start=1,
    ):
        lines.append(f"{index}. EN: {english_sentence}")
        lines.append(f"   BG: {bulgarian_sentence}")
    return "\n".join(lines).strip()


def _print_plan(args: argparse.Namespace) -> int:
    paths = ProjectPaths.from_root()
    paths.ensure()

    url = _resolve_article_url(args, paths) if not args.url else args.url
    slug = episode_slug_from_url(url)

    print("Stack: Python 3.11+ stdlib-first CLI scaffold")
    print(f"Source URL: {url}")
    print(f"Episode slug: {slug}")
    print(f"Article cache: {paths.articles / f'{slug}.html'}")
    print(f"Translation output: {paths.scripts / f'{slug}{TRANSLATION_FILE_SUFFIX}'}")
    print(f"Script output: {paths.scripts / f'{slug}.txt'}")
    print(f"Audio output: {paths.audio / f'{slug}{AUDIO_FILE_EXTENSION}'}")
    return 0


def _print_article_details(article: Article, *, used_cached_html: bool, cache_path: Path) -> None:
    print(f"Article URL: {article.source_url}")
    print(f"Fetched title: {article.title_bg}")
    print(f"Sentence count: {len(article.sentences_bg)}")
    print(f"HTML source: {'cache' if used_cached_html else 'network'}")
    print(f"Cached HTML: {cache_path}")


def _run_fetch(args: argparse.Namespace) -> int:
    paths = ProjectPaths.from_root()
    paths.ensure()

    url = _resolve_article_url(args, paths) if not args.url else args.url

    article, cache_path, used_cached_html = _load_article(
        paths,
        url,
        use_cached_html=not args.refresh,
    )
    _print_article_details(article, used_cached_html=used_cached_html, cache_path=cache_path)
    if article.sentences_bg:
        print(f"First sentence: {article.sentences_bg[0]}")
    return 0


def _run_translate(args: argparse.Namespace) -> int:
    paths = ProjectPaths.from_root()
    paths.ensure()

    url = _resolve_article_url(args, paths) if not args.url else args.url

    article, cache_path, used_cached_html = _load_article(
        paths,
        url,
        use_cached_html=not args.refresh,
    )
    translation, translation_path = _translate_article(paths, article)

    _print_article_details(article, used_cached_html=used_cached_html, cache_path=cache_path)
    print(f"Translated title: {translation.title_en}")
    print(f"Translated sentence count: {len(translation.sentences_en)}")
    print(f"Translation output: {translation_path}")
    if translation.sentences_en:
        print(f"First translated sentence: {translation.sentences_en[0]}")
    return 0


def _run_build_script(args: argparse.Namespace) -> int:
    paths = ProjectPaths.from_root()
    paths.ensure()

    url = _resolve_article_url(args, paths) if not args.url else args.url

    article, cache_path, used_cached_html = _load_article(
        paths,
        url,
        use_cached_html=not args.refresh,
    )
    translation, translation_path = _translate_article(paths, article)
    script_text = PodcastScriptBuilder().build(article, translation)
    script_path = _script_output_path(paths, article.source_url)
    script_path.write_text(script_text, encoding="utf-8")

    _print_article_details(article, used_cached_html=used_cached_html, cache_path=cache_path)
    print(f"Translated title: {translation.title_en}")
    print(f"Translation output: {translation_path}")
    print(f"Script output: {script_path}")
    return 0


def _run_generate_audio(args: argparse.Namespace) -> int:
    paths = ProjectPaths.from_root()
    paths.ensure()
    article_manifest = ArticleAudioManifest.for_paths(paths)

    url = _resolve_article_url(args, paths) if not args.url else args.url

    article, cache_path, used_cached_html = _load_article(
        paths,
        url,
        use_cached_html=not args.refresh,
    )
    existing_audio_path = article_manifest.find_existing_audio(article)
    if existing_audio_path is not None:
        _print_article_details(article, used_cached_html=used_cached_html, cache_path=cache_path)
        _print_duplicate_audio(article, existing_audio_path)
        return 0
    translation, translation_path = _translate_article(paths, article)
    script_text = PodcastScriptBuilder().build(article, translation)
    script_path = _script_output_path(paths, article.source_url)
    script_path.write_text(script_text, encoding="utf-8")
    audio_path = build_default_audio_generator(
        voice_name=args.en_voice or None,
        bg_voice_name=args.bg_voice or None,
    ).generate(
        script_text,
        episode_slug_from_url(article.source_url),
    )
    article_manifest.record(article, audio_path)

    _print_article_details(article, used_cached_html=used_cached_html, cache_path=cache_path)
    print(f"Translated title: {translation.title_en}")
    print(f"Translation output: {translation_path}")
    print(f"Script output: {script_path}")
    print(f"Audio output: {audio_path}")
    return 0


def _run_pipeline(args: argparse.Namespace) -> int:
    paths = ProjectPaths.from_root()
    paths.ensure()

    # Determine the article URL: explicit --url or select by filter
    article_url = _resolve_article_url(args, paths)
    try:
        plan = build_pipeline(
            paths=paths,
            use_cached_html=not args.refresh,
            audio_generator=build_default_audio_generator(
                voice_name=args.en_voice or None,
                bg_voice_name=args.bg_voice or None,
            ),
        ).run(article_url)
    except DuplicateArticleError as exc:
        _print_duplicate_audio(exc.article, exc.audio_path)
        return 0

    print(f"Article URL: {plan.article.source_url}")
    print(f"Fetched title: {plan.article.title_bg}")
    print(f"Translated title: {plan.translation.title_en}")
    print(f"Sentence count: {len(plan.article.sentences_bg)}")
    if plan.article_html_path is not None:
        print(f"Cached HTML: {plan.article_html_path}")
    print(f"Script output: {plan.script_path}")
    print(f"Audio output: {plan.audio_path}")
    return 0


def _run_web(args: argparse.Namespace) -> int:
    from .web import create_app

    paths = ProjectPaths.from_root()
    paths.ensure()
    app = create_app(paths)
    print(f"Starting local web UI at http://{args.host}:{args.port}")
    print(f"Output folder: {paths.data}")
    app.run(host=args.host, port=args.port, debug=False)
    return 0


def _run_daily_check(args: argparse.Namespace) -> int:
    """Run a single daily check for new articles."""
    paths = ProjectPaths.from_root()
    paths.ensure()

    pipeline = build_pipeline(
        paths=paths,
        audio_generator=build_default_audio_generator(
            voice_name=args.en_voice or None,
            bg_voice_name=args.bg_voice or None,
        ),
    )
    selector = ArticleSelector()
    scheduler = DailyEpisodeScheduler(pipeline, selector, paths)

    print("Running daily episode check...")
    result = scheduler.check_and_generate()
    scheduler._print_result(result)
    return 0


def _run_daily_daemon(args: argparse.Namespace) -> int:
    """Run as a daemon, checking daily for new articles."""
    paths = ProjectPaths.from_root()
    paths.ensure()

    pipeline = build_pipeline(
        paths=paths,
        audio_generator=build_default_audio_generator(
            voice_name=args.en_voice or None,
            bg_voice_name=args.bg_voice or None,
        ),
    )
    selector = ArticleSelector()
    scheduler = DailyEpisodeScheduler(pipeline, selector, paths)

    scheduler.run_daemon(check_interval_seconds=args.interval)
    return 0


def _run_local_rss_delivery(args: argparse.Namespace) -> int:
    paths = ProjectPaths.from_root()
    paths.ensure()
    rss_service = LocalRSSService(paths)

    if args.no_serve:
        feed_plan = rss_service.rebuild_feed(
            rss_service.build_public_base_url(
                bind_host=args.host,
                port=args.port,
                public_host=args.public_host or None,
            )
        )
        print(f"Staged RSS feed: {feed_plan.feed_path}")
        print(f"Staged episodes: {len(feed_plan.staged_episode_paths)}")
        print(f"Feed URL: {feed_plan.feed_url}")
        print("RSS staging complete. Re-run without --no-serve to keep the local feed online.")
        return 0

    server = rss_service.create_server(host=args.host, port=args.port)
    try:
        actual_port = int(server.server_address[1])
        feed_plan = rss_service.rebuild_feed(
            rss_service.build_public_base_url(
                bind_host=args.host,
                port=actual_port,
                public_host=args.public_host or None,
            )
        )
        print(f"Staged RSS feed: {feed_plan.feed_path}")
        print(f"Staged episodes: {len(feed_plan.staged_episode_paths)}")
        print(f"Feed URL: {feed_plan.feed_url}")
        print("Keep this command running while your podcast app connects.")
        server.serve_forever()
    except KeyboardInterrupt:
        print("Local RSS server stopped.")
    finally:
        server.server_close()
    return 0


def _resolve_article_url(args: argparse.Namespace, paths: ProjectPaths) -> str:
    """
    Resolve the article URL from command line arguments.

    Priority:
    1. Explicit --url if provided
    2. Filter-based selection if --filter is provided
    3. Latest article if neither is provided
    """
    if args.url:
        return args.url

    # Load filter if provided, otherwise use None (latest article)
    article_filter = None
    if hasattr(args, "filter") and args.filter:
        article_filter = ArticleFilter.from_json(args.filter)
        print(f"Selecting article with filter: {args.filter}")
    else:
        print("Selecting latest article from Knigovishte...")

    selector = ArticleSelector()
    article = selector.select_article(article_filter)
    print(f"Selected article: {article.source_url}")
    return article.source_url


def _print_duplicate_audio(article: Article, audio_path: Path) -> None:
    print(f"Article URL: {article.source_url}")
    print(f"Fetched title: {article.title_bg}")
    print(f"Audio output: {audio_path}")
    print("Skipping audio generation because this article was already used.")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Ensure stdout/stderr can handle Unicode on Windows terminals
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    try:
        if args.command == "plan":
            return _print_plan(args)
        if args.command == "fetch":
            return _run_fetch(args)
        if args.command == "translate":
            return _run_translate(args)
        if args.command == "build-script":
            return _run_build_script(args)
        if args.command == "generate-audio":
            return _run_generate_audio(args)
        if args.command == "run":
            return _run_pipeline(args)
        if args.command == "web":
            return _run_web(args)
        if args.command == "daily-check":
            return _run_daily_check(args)
        if args.command == "daily-daemon":
            return _run_daily_daemon(args)
        if args.command == "local-rss-delivery":
            return _run_local_rss_delivery(args)
    except Exception as exc:
        if args.command == "run":
            print(f"Pipeline failed: {exc}")
        elif args.command == "web":
            print(f"Web failed: {exc}")
        else:
            print(f"{args.command.replace('-', ' ').title()} failed: {exc}")
        return 1

    parser.error(f"Unsupported command: {args.command}")
    return 2
