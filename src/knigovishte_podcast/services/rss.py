from __future__ import annotations

import errno
import os
import re
import shutil
import socket
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

from ..config import ProjectPaths

SUPPORTED_AUDIO_EXTENSIONS = (".mp3", ".m4a", ".aac", ".wav")
RSS_IMAGE_FILENAME = "pic.png"
AUDIO_EXTENSION_PRIORITY = {
    ".mp3": 0,
    ".m4a": 1,
    ".aac": 2,
    ".wav": 3,
}
CONTENT_TYPES = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".wav": "audio/wav",
}
EPISODE_METADATA_SUFFIXES = (".translation.txt", ".txt")
ENGLISH_TITLE_LABEL = "english title"
VIJTE_PREFIX_PATTERN = re.compile(r"^vijte-\d+(?:-|$)", re.IGNORECASE)
ITUNES_NAMESPACE = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", ITUNES_NAMESPACE)
CLIENT_DISCONNECT_ERRNOS = {
    errno.EPIPE,
    errno.ECONNABORTED,
    errno.ECONNRESET,
    errno.ETIMEDOUT,
}
CLIENT_DISCONNECT_WINERRORS = {10053, 10054, 10060}


@dataclass(frozen=True)
class FeedBuildResult:
    feed_path: Path
    feed_url: str
    staged_episode_paths: tuple[Path, ...]


def _is_client_disconnect_error(error: OSError) -> bool:
    return (
        isinstance(
            error,
            (
                BrokenPipeError,
                ConnectionAbortedError,
                ConnectionResetError,
                TimeoutError,
            ),
        )
        or error.errno in CLIENT_DISCONNECT_ERRNOS
        or getattr(error, "winerror", None) in CLIENT_DISCONNECT_WINERRORS
    )


class LocalRSSRequestHandler(SimpleHTTPRequestHandler):
    def copyfile(self, source, outputfile) -> None:  # type: ignore[override]
        try:
            super().copyfile(source, outputfile)
        except OSError as exc:
            if _is_client_disconnect_error(exc):
                self.close_connection = True
                return
            raise


class LocalRSSService:
    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths

    def build_public_base_url(
        self,
        *,
        bind_host: str,
        port: int,
        public_host: str | None = None,
    ) -> str:
        self._load_project_env()
        # Explicit --public-host flag takes highest priority.
        if public_host:
            return f"http://{public_host}:{port}"
        # PODCAST_BASE_URL env var lets operators set the full public URL
        # (e.g. "http://203.0.113.5:8000") without touching CLI flags.
        env_base_url = os.environ.get("PODCAST_BASE_URL", "").strip()
        if env_base_url:
            return env_base_url.rstrip("/")
        host = self._default_public_host(bind_host)
        return f"http://{host}:{port}"

    def rebuild_feed(self, public_base_url: str) -> FeedBuildResult:
        self.paths.ensure()
        audio_files = self._discover_audio_files()
        if not audio_files:
            raise ValueError(
                f"No supported audio files found in {self.paths.audio}. "
                "Generate audio before starting local RSS delivery."
            )

        self._clean_directory(self.paths.rss_episodes)
        staged_episode_paths = []
        for audio_path in audio_files:
            staged_path = self.paths.rss_episodes / audio_path.name
            shutil.copy2(audio_path, staged_path)
            staged_episode_paths.append(staged_path)

        feed_path = self.paths.rss / "podcast.xml"
        feed_url = f"{public_base_url.rstrip('/')}/podcast.xml"
        feed_path.write_bytes(
            self._render_feed_xml(
                public_base_url=public_base_url.rstrip("/"),
                staged_episode_paths=tuple(staged_episode_paths),
            )
        )
        return FeedBuildResult(
            feed_path=feed_path,
            feed_url=feed_url,
            staged_episode_paths=tuple(staged_episode_paths),
        )

    def create_server(self, *, host: str, port: int) -> ThreadingHTTPServer:
        handler = partial(LocalRSSRequestHandler, directory=str(self.paths.rss))
        return ThreadingHTTPServer((host, port), handler)

    def _load_project_env(self) -> None:
        env_file = self.paths.root / ".env"
        if env_file.is_file():
            load_dotenv(env_file, override=False)

    def _default_public_host(self, bind_host: str) -> str:
        if bind_host in {"0.0.0.0", "::", ""}:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.connect(("8.8.8.8", 80))
                    return sock.getsockname()[0]
            except OSError:
                return socket.gethostbyname(socket.gethostname())
        return bind_host

    def _discover_audio_files(self) -> list[Path]:
        discovered: dict[str, Path] = {}
        for path in self.paths.audio.iterdir():
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
                continue
            existing = discovered.get(path.stem)
            if existing is None:
                discovered[path.stem] = path
                continue
            if AUDIO_EXTENSION_PRIORITY[path.suffix.lower()] < AUDIO_EXTENSION_PRIORITY[
                existing.suffix.lower()
            ]:
                discovered[path.stem] = path
        return sorted(
            discovered.values(),
            key=lambda path: (-path.stat().st_mtime, path.name.lower()),
        )

    def _clean_directory(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        for child in directory.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    def _render_feed_xml(
        self,
        *,
        public_base_url: str,
        staged_episode_paths: tuple[Path, ...],
    ) -> bytes:
        rss = ET.Element("rss", version="2.0")
        channel = ET.SubElement(rss, "channel")
        ET.SubElement(channel, "title").text = "Knigovishte Podcast Builder"
        ET.SubElement(channel, "link").text = f"{public_base_url}/podcast.xml"
        ET.SubElement(
            channel,
            "description",
        ).text = "Local LAN RSS feed generated from existing podcast audio artifacts."
        ET.SubElement(channel, "language").text = "en"
        image_url = self._channel_image_url(public_base_url)
        if image_url:
            image = ET.SubElement(channel, "image")
            ET.SubElement(image, "url").text = image_url
            ET.SubElement(image, "title").text = "Knigovishte Podcast Builder"
            ET.SubElement(image, "link").text = f"{public_base_url}/podcast.xml"
            ET.SubElement(channel, f"{{{ITUNES_NAMESPACE}}}image", href=image_url)

        for staged_path in staged_episode_paths:
            item = ET.SubElement(channel, "item")
            title = self._episode_title_from_path(staged_path)
            enclosure_url = f"{public_base_url}/episodes/{quote(staged_path.name)}"
            stat = staged_path.stat()
            published_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            ET.SubElement(item, "title").text = title
            ET.SubElement(item, "guid").text = enclosure_url
            ET.SubElement(item, "pubDate").text = format_datetime(published_at)
            ET.SubElement(
                item,
                "enclosure",
                url=enclosure_url,
                length=str(stat.st_size),
                type=CONTENT_TYPES[staged_path.suffix.lower()],
            )

        return ET.tostring(rss, encoding="utf-8", xml_declaration=True)

    def _channel_image_url(self, public_base_url: str) -> str | None:
        image_path = self.paths.rss / RSS_IMAGE_FILENAME
        if not image_path.is_file():
            return None
        return f"{public_base_url}/{quote(image_path.name)}"

    def _episode_title_from_path(self, path: Path) -> str:
        metadata_title = self._episode_title_from_metadata(path.stem)
        if metadata_title:
            return metadata_title

        normalized_stem = VIJTE_PREFIX_PATTERN.sub("", path.stem)
        title = normalized_stem.replace("-", " ").strip()
        if title:
            return title
        return path.stem.replace("-", " ").strip() or path.stem

    def _episode_title_from_metadata(self, episode_stem: str) -> str | None:
        for suffix in EPISODE_METADATA_SUFFIXES:
            metadata_path = self.paths.scripts / f"{episode_stem}{suffix}"
            title = self._english_title_from_file(metadata_path)
            if title:
                return title
        return None

    def _english_title_from_file(self, path: Path) -> str | None:
        if not path.is_file():
            return None

        for line in path.read_text(encoding="utf-8").splitlines():
            label, separator, value = line.partition(":")
            if separator and label.strip().lower() == ENGLISH_TITLE_LABEL:
                title = value.strip()
                if title:
                    return title
        return None
