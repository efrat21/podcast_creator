from __future__ import annotations

import io
import os
import shutil
import sys
import threading
import unittest
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knigovishte_podcast.config import ProjectPaths
from knigovishte_podcast.services.rss import LocalRSSRequestHandler, LocalRSSService


class _FailingWriteStream:
    def __init__(self, error: OSError) -> None:
        self.error = error

    def write(self, data: bytes) -> int:
        raise self.error


class LocalRSSServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workdir = Path(__file__).resolve().parent / "_artifacts" / self._testMethodName
        if self.workdir.exists():
            shutil.rmtree(self.workdir)
        self.paths = ProjectPaths.from_root(self.workdir)
        self.paths.ensure()
        self.service = LocalRSSService(self.paths)

    def tearDown(self) -> None:
        if self.workdir.exists():
            shutil.rmtree(self.workdir)

    def _write_translation_metadata(self, episode_stem: str, english_title: str) -> None:
        metadata_path = self.paths.scripts / f"{episode_stem}.translation.txt"
        metadata_path.write_text(
            f"Source URL: https://www.knigovishte.bg/vijte/7549\n"
            f"Bulgarian title: Българско заглавие\n"
            f"English title: {english_title}\n",
            encoding="utf-8",
        )

    def _write_script_metadata(self, episode_stem: str, english_title: str) -> None:
        metadata_path = self.paths.scripts / f"{episode_stem}.txt"
        metadata_path.write_text(
            f"Welcome to today's bilingual Knigovishte story.\n"
            f"English title: {english_title}\n"
            "Bulgarian title: Българско заглавие\n",
            encoding="utf-8",
        )

    def _parse_feed_channel(self, feed_path: Path) -> ET.Element:
        root = ET.fromstring(feed_path.read_text(encoding="utf-8"))
        channel = root.find("channel")
        self.assertIsNotNone(channel)
        return channel

    def test_rebuild_feed_stages_supported_audio_and_cleans_stale_files(self) -> None:
        older_audio = self.paths.audio / "older.mp3"
        older_audio.write_bytes(b"older-audio")
        newest_audio = self.paths.audio / "newest.wav"
        newest_audio.write_bytes(b"newest-audio")
        os.utime(older_audio, (1_700_000_000, 1_700_000_000))
        os.utime(newest_audio, (1_600_000_000, 1_600_000_000))
        unsupported = self.paths.audio / "ignore.txt"
        unsupported.write_text("ignore", encoding="utf-8")
        stale_file = self.paths.rss_episodes / "stale.wav"
        stale_file.write_bytes(b"stale")

        result = self.service.rebuild_feed("http://127.0.0.1:8000")

        self.assertFalse(stale_file.exists())
        self.assertEqual([path.name for path in result.staged_episode_paths], ["older.mp3", "newest.wav"])
        self.assertEqual((self.paths.rss / "podcast.xml").read_text(encoding="utf-8").count("<item>"), 2)
        feed_text = result.feed_path.read_text(encoding="utf-8")
        self.assertIn('url="http://127.0.0.1:8000/episodes/older.mp3"', feed_text)
        self.assertIn('type="audio/mpeg"', feed_text)
        self.assertIn('url="http://127.0.0.1:8000/episodes/newest.wav"', feed_text)
        self.assertIn('type="audio/wav"', feed_text)

    def test_rebuild_feed_prefers_mp3_when_same_episode_has_multiple_formats(self) -> None:
        wav_audio = self.paths.audio / "episode.wav"
        mp3_audio = self.paths.audio / "episode.mp3"
        wav_audio.write_bytes(b"wav-audio")
        mp3_audio.write_bytes(b"mp3-audio")

        result = self.service.rebuild_feed("http://127.0.0.1:8000")

        self.assertEqual([path.name for path in result.staged_episode_paths], ["episode.mp3"])
        feed_text = result.feed_path.read_text(encoding="utf-8")
        self.assertIn('url="http://127.0.0.1:8000/episodes/episode.mp3"', feed_text)
        self.assertNotIn("episode.wav", feed_text)

    def test_rebuild_feed_includes_channel_image_metadata_when_pic_exists(self) -> None:
        audio_path = self.paths.audio / "episode.mp3"
        audio_path.write_bytes(b"episode")
        image_path = self.paths.rss / "pic.png"
        image_path.write_bytes(b"png-bytes")

        result = self.service.rebuild_feed("http://127.0.0.1:8000")

        channel = self._parse_feed_channel(result.feed_path)
        image = channel.find("image")
        self.assertIsNotNone(image)
        self.assertEqual(image.findtext("url"), "http://127.0.0.1:8000/pic.png")
        self.assertEqual(image.findtext("title"), "Knigovishte Podcast Builder")
        self.assertEqual(image.findtext("link"), "http://127.0.0.1:8000/podcast.xml")
        itunes_image = channel.find(
            "{http://www.itunes.com/dtds/podcast-1.0.dtd}image"
        )
        self.assertIsNotNone(itunes_image)
        self.assertEqual(itunes_image.get("href"), "http://127.0.0.1:8000/pic.png")

    def test_rebuild_feed_raises_when_no_audio_exists(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.service.rebuild_feed("http://127.0.0.1:8000")

        self.assertIn("Generate audio before starting local RSS delivery", str(ctx.exception))

    def test_rebuild_feed_uses_english_title_without_vijte_prefix(self) -> None:
        audio_path = self.paths.audio / "vijte-7549-the-little-prince.wav"
        audio_path.write_bytes(b"episode")

        result = self.service.rebuild_feed("http://127.0.0.1:8000")

        feed_text = result.feed_path.read_text(encoding="utf-8")
        self.assertIn("<title>the little prince</title>", feed_text)
        self.assertNotIn("<title>vijte 7549 the little prince</title>", feed_text)

    def test_rebuild_feed_uses_translation_metadata_when_filename_is_only_vijte_slug(self) -> None:
        audio_path = self.paths.audio / "vijte-7549.wav"
        audio_path.write_bytes(b"episode")
        self._write_translation_metadata(audio_path.stem, "The Little Prince")

        result = self.service.rebuild_feed("http://127.0.0.1:8000")

        feed_text = result.feed_path.read_text(encoding="utf-8")
        self.assertIn("<title>The Little Prince</title>", feed_text)
        self.assertNotIn("<title>vijte 7549</title>", feed_text)

    def test_rebuild_feed_prefers_script_english_title_metadata_over_filename_slug(self) -> None:
        audio_path = self.paths.audio / "vijte-7549-leftover-slug.wav"
        audio_path.write_bytes(b"episode")
        self._write_script_metadata(audio_path.stem, "A Real English Title")

        result = self.service.rebuild_feed("http://127.0.0.1:8000")

        feed_text = result.feed_path.read_text(encoding="utf-8")
        self.assertIn("<title>A Real English Title</title>", feed_text)
        self.assertNotIn("<title>leftover slug</title>", feed_text)

    def test_build_public_base_url_uses_public_host_flag(self) -> None:
        url = self.service.build_public_base_url(bind_host="0.0.0.0", port=8000, public_host="1.2.3.4")
        self.assertEqual(url, "http://1.2.3.4:8000")

    def test_build_public_base_url_uses_env_var(self) -> None:
        os.environ["PODCAST_BASE_URL"] = "http://203.0.113.5:8000"
        try:
            url = self.service.build_public_base_url(bind_host="0.0.0.0", port=9000)
        finally:
            del os.environ["PODCAST_BASE_URL"]
        self.assertEqual(url, "http://203.0.113.5:8000")

    def test_build_public_base_url_loads_env_var_from_project_dotenv(self) -> None:
        env_file = self.paths.root / ".env"
        env_file.write_text("PODCAST_BASE_URL=http://198.51.100.7:8000\n", encoding="utf-8")
        original = os.environ.pop("PODCAST_BASE_URL", None)
        try:
            url = self.service.build_public_base_url(bind_host="0.0.0.0", port=9000)
        finally:
            os.environ.pop("PODCAST_BASE_URL", None)
            if original is not None:
                os.environ["PODCAST_BASE_URL"] = original
        self.assertEqual(url, "http://198.51.100.7:8000")

    def test_build_public_base_url_env_var_strips_trailing_slash(self) -> None:
        os.environ["PODCAST_BASE_URL"] = "http://203.0.113.5:8000/"
        try:
            url = self.service.build_public_base_url(bind_host="0.0.0.0", port=9000)
        finally:
            del os.environ["PODCAST_BASE_URL"]
        self.assertEqual(url, "http://203.0.113.5:8000")

    def test_build_public_base_url_public_host_overrides_env_var(self) -> None:
        os.environ["PODCAST_BASE_URL"] = "http://203.0.113.5:8000"
        try:
            url = self.service.build_public_base_url(bind_host="0.0.0.0", port=9000, public_host="5.6.7.8")
        finally:
            del os.environ["PODCAST_BASE_URL"]
        self.assertEqual(url, "http://5.6.7.8:9000")

    def test_build_public_base_url_falls_back_to_hostname(self) -> None:
        os.environ.pop("PODCAST_BASE_URL", None)
        url = self.service.build_public_base_url(bind_host="127.0.0.1", port=8000)
        self.assertEqual(url, "http://127.0.0.1:8000")

    def test_create_server_serves_feed_and_episode(self) -> None:
        audio_path = self.paths.audio / "episode.wav"
        audio_path.write_bytes(b"episode-bytes")
        image_path = self.paths.rss / "pic.png"
        image_path.write_bytes(b"png-bytes")
        server = self.service.create_server(host="127.0.0.1", port=0)
        port = int(server.server_address[1])
        result = self.service.rebuild_feed(f"http://127.0.0.1:{port}")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            with urllib.request.urlopen(result.feed_url) as response:
                feed_body = response.read().decode("utf-8")
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/episodes/episode.wav") as response:
                episode_body = response.read()
                content_type = response.headers.get_content_type()
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/pic.png") as response:
                image_body = response.read()
                image_content_type = response.headers.get_content_type()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        channel = ET.fromstring(feed_body).find("channel")
        self.assertIsNotNone(channel)
        image = channel.find("image")
        self.assertIsNotNone(image)
        self.assertEqual(image.findtext("url"), f"http://127.0.0.1:{port}/pic.png")
        itunes_image = channel.find("{http://www.itunes.com/dtds/podcast-1.0.dtd}image")
        self.assertIsNotNone(itunes_image)
        self.assertEqual(
            itunes_image.get("href"),
            f"http://127.0.0.1:{port}/pic.png",
        )
        self.assertEqual(episode_body, b"episode-bytes")
        self.assertIn(content_type, {"audio/wav", "audio/x-wav"})
        self.assertEqual(image_body, b"png-bytes")
        self.assertEqual(image_content_type, "image/png")

    def test_create_server_uses_resilient_request_handler(self) -> None:
        server = self.service.create_server(host="127.0.0.1", port=0)
        try:
            self.assertIs(server.RequestHandlerClass.func, LocalRSSRequestHandler)
        finally:
            server.server_close()

    def test_request_handler_ignores_client_disconnect_during_copy(self) -> None:
        handler = object.__new__(LocalRSSRequestHandler)
        handler.close_connection = False

        handler.copyfile(
            io.BytesIO(b"episode"),
            _FailingWriteStream(ConnectionResetError(10054, "reset by peer")),
        )

        self.assertTrue(handler.close_connection)

    def test_request_handler_reraises_non_disconnect_write_errors(self) -> None:
        handler = object.__new__(LocalRSSRequestHandler)
        handler.close_connection = False

        with self.assertRaises(OSError):
            handler.copyfile(
                io.BytesIO(b"episode"),
                _FailingWriteStream(OSError(22, "invalid argument")),
            )

        self.assertFalse(handler.close_connection)

    def test_rebuild_feed_includes_spotify_itunes_tags(self) -> None:
        audio = self.paths.audio / "episode.mp3"
        audio.write_bytes(b"audio")

        # 1. Test defaults
        self.service.rebuild_feed("http://127.0.0.1:8000")
        feed_xml = (self.paths.rss / "podcast.xml").read_text(encoding="utf-8")
        
        self.assertIn("<!-- 1. THE AUTHOR TAG -->", feed_xml)
        self.assertIn("<itunes:author>Efrat Miyara</itunes:author>", feed_xml)
        self.assertIn("<!-- 2. THE EMAIL TAG -->", feed_xml)
        self.assertIn("<itunes:name>Efrat Miyara</itunes:name>", feed_xml)
        self.assertIn("<itunes:email>Efrat.baker@gmail.com</itunes:email>", feed_xml)
        self.assertIn("<itunes:explicit>no</itunes:explicit>", feed_xml)

        # 2. Test overrides from environment
        os.environ["PODCAST_AUTHOR"] = "My Custom Author"
        os.environ["PODCAST_OWNER_NAME"] = "My Custom Owner"
        os.environ["PODCAST_OWNER_EMAIL"] = "custom-owner@example.com"
        os.environ["PODCAST_EXPLICIT"] = "yes"
        try:
            self.service.rebuild_feed("http://127.0.0.1:8000")
            feed_xml_override = (self.paths.rss / "podcast.xml").read_text(encoding="utf-8")
            
            self.assertIn("<itunes:author>My Custom Author</itunes:author>", feed_xml_override)
            self.assertIn("<itunes:name>My Custom Owner</itunes:name>", feed_xml_override)
            self.assertIn("<itunes:email>custom-owner@example.com</itunes:email>", feed_xml_override)
            self.assertIn("<itunes:explicit>yes</itunes:explicit>", feed_xml_override)
        finally:
            os.environ.pop("PODCAST_AUTHOR", None)
            os.environ.pop("PODCAST_OWNER_NAME", None)
            os.environ.pop("PODCAST_OWNER_EMAIL", None)
            os.environ.pop("PODCAST_EXPLICIT", None)
