from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

DEFAULT_LANGBLY_BASE_URL = "https://api.langbly.com"


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    data: Path
    articles: Path
    scripts: Path
    audio: Path
    rss: Path = field(init=False)
    rss_episodes: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "rss", self.data / "rss")
        object.__setattr__(self, "rss_episodes", self.data / "rss" / "episodes")

    @classmethod
    def from_root(cls, root: Path | None = None) -> "ProjectPaths":
        project_root = root or Path(__file__).resolve().parents[2]
        data = project_root / "data"
        return cls(
            root=project_root,
            data=data,
            articles=data / "articles",
            scripts=data / "scripts",
            audio=data / "audio",
        )

    def ensure(self) -> None:
        for directory in (
            self.data,
            self.articles,
            self.scripts,
            self.audio,
            self.rss,
            self.rss_episodes,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def episode_slug_from_url(url: str) -> str:
    parsed = urlparse(url)
    raw = parsed.path.strip("/") or parsed.netloc or "episode"
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return slug or "episode"


@dataclass(frozen=True)
class TranslationConfig:
    api_key: str
    base_url: str = DEFAULT_LANGBLY_BASE_URL
    source_lang: str = "bg"
    target_lang: str = "en"
    timeout_seconds: float = 60.0
    max_retries: int = 0
    retry_backoff_seconds: float = 1.0
    fallback_base_urls: tuple[str, ...] = ()

    def all_base_urls(self) -> tuple[str, ...]:
        seen: set[str] = set()
        urls: list[str] = []
        for base_url in (self.base_url, *self.fallback_base_urls):
            normalized_url = base_url.rstrip("/")
            if normalized_url and normalized_url not in seen:
                seen.add(normalized_url)
                urls.append(normalized_url)
        return tuple(urls)

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> "TranslationConfig":
        """Load translation config from .env file in project root."""
        if project_root is None:
            project_root = Path(__file__).resolve().parents[2]
        env_file = project_root / ".env"
        if env_file.exists():
            load_dotenv(env_file)
        
        api_key = os.getenv("LANGBLY_API_KEY")
        if not api_key:
            raise ValueError(
                "LANGBLY_API_KEY not found in .env file or environment. "
                "Create .env with LANGBLY_API_KEY=your_key"
            )
        
        base_url = os.getenv("LANGBLY_BASE_URL", DEFAULT_LANGBLY_BASE_URL).strip()
        if not base_url:
            base_url = DEFAULT_LANGBLY_BASE_URL

        fallback_base_urls = tuple(
            value.strip()
            for value in os.getenv("LANGBLY_FALLBACK_BASE_URLS", "").split(",")
            if value.strip()
        )
        if base_url.rstrip("/") != DEFAULT_LANGBLY_BASE_URL:
            fallback_base_urls = (DEFAULT_LANGBLY_BASE_URL, *fallback_base_urls)

        return cls(
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=_read_positive_float_env("LANGBLY_TIMEOUT_SECONDS", default=60.0),
            max_retries=_read_non_negative_int_env("LANGBLY_MAX_RETRIES", default=0),
            retry_backoff_seconds=_read_non_negative_float_env(
                "LANGBLY_RETRY_BACKOFF_SECONDS",
                default=1.0,
            ),
            fallback_base_urls=fallback_base_urls,
        )


@dataclass(frozen=True)
class GoogleTTSConfig:
    en_voice_name: str = "en-US-Standard-F"
    en_language_code: str = "en-US"
    bg_voice_name: str = "bg-BG-Standard-B"
    bg_language_code: str = "bg-BG"
    bg_speaking_rate: float = 1.0
    credentials_path: Path | None = None

    @classmethod
    def from_env(cls) -> "GoogleTTSConfig":
        en_voice_name = os.getenv("GOOGLE_TTS_EN_VOICE_NAME", "en-US-Standard-F")
        en_language_code = os.getenv(
            "GOOGLE_TTS_EN_LANGUAGE_CODE",
            google_language_code_from_voice_name(en_voice_name, fallback="en-US"),
        )
        voice_name = os.getenv("GOOGLE_TTS_BG_VOICE_NAME", "bg-BG-Standard-B")
        language_code = os.getenv(
            "GOOGLE_TTS_BG_LANGUAGE_CODE",
            google_language_code_from_voice_name(voice_name, fallback="bg-BG"),
        )
        bg_speaking_rate_val = os.getenv("GOOGLE_TTS_BG_SPEAKING_RATE", "1.0")
        try:
            bg_speaking_rate = float(bg_speaking_rate_val)
        except ValueError:
            bg_speaking_rate = 1.0

        credentials_value = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        credentials_path = Path(credentials_value) if credentials_value else None
        return cls(
            en_voice_name=en_voice_name,
            en_language_code=en_language_code,
            bg_voice_name=voice_name,
            bg_language_code=language_code,
            bg_speaking_rate=bg_speaking_rate,
            credentials_path=credentials_path,
        )


def google_language_code_from_voice_name(voice_name: str, *, fallback: str) -> str:
    parts = voice_name.strip().split("-")
    if len(parts) >= 2 and parts[0] and parts[1]:
        return f"{parts[0]}-{parts[1]}"
    return fallback


def _read_positive_float_env(name: str, *, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    parsed_value = float(value)
    if parsed_value <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return parsed_value


def _read_non_negative_float_env(name: str, *, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    parsed_value = float(value)
    if parsed_value < 0:
        raise ValueError(f"{name} must be 0 or greater")
    return parsed_value


def _read_non_negative_int_env(name: str, *, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    parsed_value = int(value)
    if parsed_value < 0:
        raise ValueError(f"{name} must be 0 or greater")
    return parsed_value
