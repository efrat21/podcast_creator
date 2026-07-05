from __future__ import annotations

import io
import subprocess
import sys
import unittest
import wave
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knigovishte_podcast.config import GoogleTTSConfig
from knigovishte_podcast.services.tts import (
    AUDIO_FILE_EXTENSION,
    DEFAULT_BG_GOOGLE_VOICE,
    DEFAULT_EN_GOOGLE_VOICE,
    Pyttsx3PodcastAudioGenerator,
    _concatenate_wav_files,
    _convert_wav_to_mp3,
    _split_script_by_language,
    _windows_com_initialized,
    build_default_audio_generator,
)


class PodcastAudioGeneratorTests(unittest.TestCase):
    @contextmanager
    def _noop_com_context(self):
        yield

    def _fake_mp3_export(self, input_path: Path, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(input_path.read_bytes() or b"dummy mp3")

    def test_generate_returns_expected_path_and_invokes_engine(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            class DummyPaths:
                root = project_root
                audio = project_root / "audio"

                def ensure(self) -> None:
                    self.audio.mkdir(parents=True, exist_ok=True)

            mock_engine = Mock()
            intermediate_audio_path = project_root / "audio" / "_episode-slug.wav"
            audio_path = project_root / "audio" / f"episode-slug{AUDIO_FILE_EXTENSION}"

            def run_and_wait_side_effect() -> None:
                intermediate_audio_path.parent.mkdir(parents=True, exist_ok=True)
                intermediate_audio_path.write_bytes(b"dummy audio")

            mock_engine.runAndWait.side_effect = run_and_wait_side_effect

            with patch(
                "knigovishte_podcast.services.tts.ProjectPaths.from_root",
                return_value=DummyPaths(),
            ):
                with patch(
                    "knigovishte_podcast.services.tts._windows_com_initialized",
                    self._noop_com_context,
                ):
                    with patch("knigovishte_podcast.services.tts.pyttsx3.init", return_value=mock_engine) as mock_init:
                        with patch(
                            "knigovishte_podcast.services.tts._convert_wav_to_mp3",
                            side_effect=self._fake_mp3_export,
                        ):
                            generator = Pyttsx3PodcastAudioGenerator(rate=150, volume=0.8)
                            result_path = generator.generate("Hello world", "episode-slug")

            self.assertEqual(result_path, audio_path)
            mock_init.assert_called_once()
            mock_engine.save_to_file.assert_called_once_with("Hello world", str(intermediate_audio_path))
            mock_engine.runAndWait.assert_called_once()

    def test_generate_raises_on_empty_script_text(self) -> None:
        generator = Pyttsx3PodcastAudioGenerator()
        with self.assertRaises(ValueError):
            generator.generate("   ", "episode-slug")

    def test_generate_raises_on_empty_episode_slug(self) -> None:
        generator = Pyttsx3PodcastAudioGenerator()
        with self.assertRaises(ValueError):
            generator.generate("Hello world", "  ")

    def test_generate_sets_requested_voice_when_available(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            class DummyPaths:
                root = project_root
                audio = project_root / "audio"

                def ensure(self) -> None:
                    self.audio.mkdir(parents=True, exist_ok=True)

            mock_engine = Mock()
            mock_engine.getProperty.return_value = [
                SimpleNamespace(id="voice-1", name="English Voice"),
            ]
            intermediate_audio_path = project_root / "audio" / "_episode-slug.wav"

            def run_and_wait_side_effect() -> None:
                intermediate_audio_path.parent.mkdir(parents=True, exist_ok=True)
                intermediate_audio_path.write_bytes(b"dummy audio")

            mock_engine.runAndWait.side_effect = run_and_wait_side_effect

            with patch(
                "knigovishte_podcast.services.tts.ProjectPaths.from_root",
                return_value=DummyPaths(),
            ):
                with patch(
                    "knigovishte_podcast.services.tts._windows_com_initialized",
                    self._noop_com_context,
                ):
                    with patch("knigovishte_podcast.services.tts.pyttsx3.init", return_value=mock_engine):
                        with patch(
                            "knigovishte_podcast.services.tts._convert_wav_to_mp3",
                            side_effect=self._fake_mp3_export,
                        ):
                            generator = Pyttsx3PodcastAudioGenerator(voice_name="english")
                            generator.generate("Hello world", "episode-slug")

            mock_engine.setProperty.assert_any_call("voice", "voice-1")

    def test_generate_raises_when_requested_voice_is_missing(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            class DummyPaths:
                root = project_root
                audio = project_root / "audio"

                def ensure(self) -> None:
                    self.audio.mkdir(parents=True, exist_ok=True)

            mock_engine = Mock()
            mock_engine.getProperty.return_value = [
                SimpleNamespace(id="voice-1", name="English Voice"),
            ]

            with patch(
                "knigovishte_podcast.services.tts.ProjectPaths.from_root",
                return_value=DummyPaths(),
            ):
                with patch(
                    "knigovishte_podcast.services.tts._windows_com_initialized",
                    self._noop_com_context,
                ):
                    with patch("knigovishte_podcast.services.tts.pyttsx3.init", return_value=mock_engine):
                        generator = Pyttsx3PodcastAudioGenerator(voice_name="bulgarian")
                        with self.assertRaisesRegex(ValueError, "Requested voice not available"):
                            generator.generate("Hello world", "episode-slug")

    def test_generate_raises_when_voice_name_is_blank(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            class DummyPaths:
                root = project_root
                audio = project_root / "audio"

                def ensure(self) -> None:
                    self.audio.mkdir(parents=True, exist_ok=True)

            mock_engine = Mock()

            with patch(
                "knigovishte_podcast.services.tts.ProjectPaths.from_root",
                return_value=DummyPaths(),
            ):
                with patch(
                    "knigovishte_podcast.services.tts._windows_com_initialized",
                    self._noop_com_context,
                ):
                    with patch("knigovishte_podcast.services.tts.pyttsx3.init", return_value=mock_engine):
                        generator = Pyttsx3PodcastAudioGenerator(voice_name="   ")
                        with self.assertRaisesRegex(ValueError, "voice_name must not be blank"):
                            generator.generate("Hello world", "episode-slug")

    def test_generate_raises_when_audio_file_is_not_created(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            class DummyPaths:
                root = project_root
                audio = project_root / "audio"

                def ensure(self) -> None:
                    self.audio.mkdir(parents=True, exist_ok=True)

            mock_engine = Mock()
            audio_path = project_root / "audio" / f"episode-slug{AUDIO_FILE_EXTENSION}"
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            audio_path.write_bytes(b"stale audio")

            with patch(
                "knigovishte_podcast.services.tts.ProjectPaths.from_root",
                return_value=DummyPaths(),
            ):
                with patch(
                    "knigovishte_podcast.services.tts._windows_com_initialized",
                    self._noop_com_context,
                ):
                    with patch("knigovishte_podcast.services.tts.pyttsx3.init", return_value=mock_engine):
                        generator = Pyttsx3PodcastAudioGenerator()
                        with self.assertRaisesRegex(RuntimeError, "Audio generation failed"):
                            generator.generate("Hello world", "episode-slug")

            self.assertFalse(audio_path.exists())

    def test_generate_initializes_com_for_local_tts(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            class DummyPaths:
                root = project_root
                audio = project_root / "audio"

                def ensure(self) -> None:
                    self.audio.mkdir(parents=True, exist_ok=True)

            mock_engine = Mock()
            intermediate_audio_path = project_root / "audio" / "_episode-slug.wav"

            def run_and_wait_side_effect() -> None:
                intermediate_audio_path.parent.mkdir(parents=True, exist_ok=True)
                intermediate_audio_path.write_bytes(b"dummy audio")

            mock_engine.runAndWait.side_effect = run_and_wait_side_effect
            com_context = MagicMock()

            with patch(
                "knigovishte_podcast.services.tts.ProjectPaths.from_root",
                return_value=DummyPaths(),
            ):
                with patch(
                    "knigovishte_podcast.services.tts._windows_com_initialized",
                    return_value=com_context,
                ) as com_init:
                    with patch("knigovishte_podcast.services.tts.pyttsx3.init", return_value=mock_engine):
                        with patch(
                            "knigovishte_podcast.services.tts._convert_wav_to_mp3",
                            side_effect=self._fake_mp3_export,
                        ):
                            generator = Pyttsx3PodcastAudioGenerator()
                            generator.generate("Hello world", "episode-slug")

            com_init.assert_called_once_with()
            com_context.__enter__.assert_called_once_with()
            com_context.__exit__.assert_called_once()


class WindowsComInitializationTests(unittest.TestCase):
    def test_context_initializes_and_uninitializes_com(self) -> None:
        ole32 = Mock()
        ole32.CoInitialize.return_value = 0

        with patch("knigovishte_podcast.services.tts._ole32", return_value=ole32):
            with _windows_com_initialized():
                pass

        ole32.CoInitialize.assert_called_once_with(None)
        ole32.CoUninitialize.assert_called_once_with()

    def test_context_skips_uninitialize_when_com_mode_already_set(self) -> None:
        ole32 = Mock()
        ole32.CoInitialize.return_value = -2147417850

        with patch("knigovishte_podcast.services.tts._ole32", return_value=ole32):
            with _windows_com_initialized():
                pass

        ole32.CoInitialize.assert_called_once_with(None)
        ole32.CoUninitialize.assert_not_called()


class SplitScriptByLanguageTests(unittest.TestCase):
    def test_empty_script_returns_empty_list(self) -> None:
        self.assertEqual(_split_script_by_language(""), [])

    def test_all_english_lines_produce_single_en_segment(self) -> None:
        script = "Welcome.\nEnglish title: Foo\nEnglish: Hello."
        segments = _split_script_by_language(script)
        self.assertEqual(len(segments), 1)
        lang, text = segments[0]
        self.assertEqual(lang, "en")
        self.assertIn("Welcome.", text)

    def test_bulgarian_line_creates_bg_segment(self) -> None:
        script = "English title: Foo\nBulgarian title: Бар\n\nHello.\nЗдравей."
        segments = _split_script_by_language(script)
        self.assertEqual(len(segments), 4)
        self.assertEqual(segments[0][0], "en")
        self.assertEqual(segments[1][0], "bg")
        self.assertEqual(segments[2], ("en", "Hello."))
        self.assertEqual(segments[3], ("bg", "Здравей."))

    def test_bulgarian_title_line_creates_bg_segment(self) -> None:
        script = "English title: Foo\nBulgarian title: Бар\nEnglish: Hi."
        segments = _split_script_by_language(script)
        self.assertEqual(segments[0][0], "en")
        self.assertEqual(segments[1][0], "bg")
        self.assertEqual(segments[2][0], "en")

    def test_consecutive_lines_same_lang_are_merged(self) -> None:
        script = "English: Hello.\nEnglish title: Foo\nBulgarian: Здравей.\nBulgarian title: Бар"
        segments = _split_script_by_language(script)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0][0], "en")
        self.assertEqual(segments[1][0], "bg")


class ConcatenateWavFilesTests(unittest.TestCase):
    def _make_wav(self, path: Path, num_frames: int = 4) -> None:
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(b"\x00\x00" * num_frames)

    def test_concatenation_produces_combined_frames(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            part0 = root / "part0.wav"
            part1 = root / "part1.wav"
            output = root / "out.wav"

            self._make_wav(part0, num_frames=4)
            self._make_wav(part1, num_frames=6)

            _concatenate_wav_files([part0, part1], output)

            self.assertTrue(output.exists())
            with wave.open(str(output), "rb") as w:
                self.assertEqual(w.getnframes(), 10)

    def test_missing_input_files_are_skipped(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            present = root / "present.wav"
            missing = root / "missing.wav"
            output = root / "out.wav"

            self._make_wav(present, num_frames=3)

            _concatenate_wav_files([missing, present], output)

            self.assertTrue(output.exists())
            with wave.open(str(output), "rb") as w:
                self.assertEqual(w.getnframes(), 3)

    def test_no_existing_files_produces_no_output(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output = root / "out.wav"
            _concatenate_wav_files([root / "ghost.wav"], output)
            self.assertFalse(output.exists())


class BilingualAudioGeneratorTests(unittest.TestCase):
    def _fake_mp3_export(self, input_path: Path, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(input_path.read_bytes() or b"dummy mp3")

    def _make_dummy_engine(self, audio_path: Path) -> Mock:
        """Return a mock pyttsx3 engine whose runAndWait writes a minimal WAV."""

        def _run_and_wait() -> None:
            # save_to_file(text, path) → positional args[1] is the destination path
            dest = Path(mock_engine.save_to_file.call_args.args[1])
            dest.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(dest), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(22050)
                w.writeframes(b"\x00\x00" * 4)

        mock_engine = Mock()
        mock_engine.getProperty.return_value = [
            SimpleNamespace(id="en-voice-id", name="English Voice"),
            SimpleNamespace(id="bg-voice-id", name="Bulgarian Voice"),
        ]
        mock_engine.runAndWait.side_effect = _run_and_wait
        return mock_engine

    def _make_wav_bytes(self, num_frames: int = 4) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(b"\x00\x00" * num_frames)
        return buffer.getvalue()

    def test_bilingual_generate_uses_bg_voice_for_bulgarian_lines(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            class DummyPaths:
                root = project_root
                audio = project_root / "audio"

                def ensure(self) -> None:
                    self.audio.mkdir(parents=True, exist_ok=True)

            audio_path = project_root / "audio" / f"ep{AUDIO_FILE_EXTENSION}"
            mock_engine = self._make_dummy_engine(audio_path)

            script = "English title: Foo\nBulgarian title: Бар\n\nHello.\nЗдравей."

            with patch(
                "knigovishte_podcast.services.tts.ProjectPaths.from_root",
                return_value=DummyPaths(),
            ):
                with patch(
                    "knigovishte_podcast.services.tts.pyttsx3.init",
                    return_value=mock_engine,
                ):
                    with patch(
                        "knigovishte_podcast.services.tts._convert_wav_to_mp3",
                        side_effect=self._fake_mp3_export,
                    ):
                        generator = Pyttsx3PodcastAudioGenerator(
                            voice_name="english",
                            bg_voice_name="bulgarian",
                        )
                        result = generator.generate(script, "ep")

            self.assertTrue(result.exists())
            set_voice_calls = [
                c for c in mock_engine.setProperty.call_args_list if c[0][0] == "voice"
            ]
            voice_ids_used = [c[0][1] for c in set_voice_calls]
            self.assertIn("en-voice-id", voice_ids_used)
            self.assertIn("bg-voice-id", voice_ids_used)

    def test_bilingual_generate_temp_files_are_cleaned_up(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            class DummyPaths:
                root = project_root
                audio = project_root / "audio"

                def ensure(self) -> None:
                    self.audio.mkdir(parents=True, exist_ok=True)

            audio_path = project_root / "audio" / f"ep{AUDIO_FILE_EXTENSION}"
            mock_engine = self._make_dummy_engine(audio_path)

            script = "English title: Foo\nBulgarian title: Бар\n\nHello.\nЗдравей."

            with patch(
                "knigovishte_podcast.services.tts.ProjectPaths.from_root",
                return_value=DummyPaths(),
            ):
                with patch(
                    "knigovishte_podcast.services.tts.pyttsx3.init",
                    return_value=mock_engine,
                ):
                    with patch(
                        "knigovishte_podcast.services.tts._convert_wav_to_mp3",
                        side_effect=self._fake_mp3_export,
                    ):
                        generator = Pyttsx3PodcastAudioGenerator(
                            voice_name="english",
                            bg_voice_name="bulgarian",
                        )
                        generator.generate(script, "ep")

            # Temporary part files must be removed after generation.
            temp_files = list((project_root / "audio").glob("_ep_part*.wav"))
            self.assertEqual(temp_files, [])

    def test_bilingual_raises_when_bg_voice_not_found(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            class DummyPaths:
                root = project_root
                audio = project_root / "audio"

                def ensure(self) -> None:
                    self.audio.mkdir(parents=True, exist_ok=True)

            mock_engine = Mock()
            mock_engine.getProperty.return_value = [
                SimpleNamespace(id="en-voice-id", name="English Voice"),
            ]

            script = "English title: Foo\nBulgarian title: Бар\n\nHello.\nЗдравей."

            with patch(
                "knigovishte_podcast.services.tts.ProjectPaths.from_root",
                return_value=DummyPaths(),
            ):
                with patch(
                    "knigovishte_podcast.services.tts.pyttsx3.init",
                    return_value=mock_engine,
                ):
                    generator = Pyttsx3PodcastAudioGenerator(
                        voice_name="english",
                        bg_voice_name="bulgarian",
                    )
                    with self.assertRaisesRegex(ValueError, "Requested voice not available"):
                        generator.generate(script, "ep")

    def test_bilingual_google_bg_voice_uses_google_client(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            class DummyPaths:
                root = project_root
                audio = project_root / "audio"

                def ensure(self) -> None:
                    self.audio.mkdir(parents=True, exist_ok=True)

            audio_path = project_root / "audio" / f"ep{AUDIO_FILE_EXTENSION}"
            mock_engine = self._make_dummy_engine(audio_path)
            google_client = Mock()
            google_client.synthesize_speech.return_value = SimpleNamespace(
                audio_content=self._make_wav_bytes()
            )
            fake_google = SimpleNamespace(
                SynthesisInput=lambda *, text: {"text": text},
                VoiceSelectionParams=lambda **kwargs: kwargs,
                AudioConfig=lambda **kwargs: kwargs,
                AudioEncoding=SimpleNamespace(LINEAR16="LINEAR16"),
            )

            script = "English title: Foo\nBulgarian title: Бар\n\nHello.\nЗдравей."

            with patch(
                "knigovishte_podcast.services.tts.ProjectPaths.from_root",
                return_value=DummyPaths(),
            ):
                with patch(
                    "knigovishte_podcast.services.tts.pyttsx3.init",
                    return_value=mock_engine,
                ):
                    with patch(
                        "knigovishte_podcast.services.tts.google_texttospeech",
                        fake_google,
                    ):
                        with patch(
                            "knigovishte_podcast.services.tts._convert_wav_to_mp3",
                            side_effect=self._fake_mp3_export,
                        ):
                            generator = Pyttsx3PodcastAudioGenerator(
                                voice_name="english",
                                bg_voice_name=DEFAULT_BG_GOOGLE_VOICE,
                                google_tts_config=GoogleTTSConfig(
                                    en_voice_name=DEFAULT_EN_GOOGLE_VOICE,
                                    en_language_code="en-US",
                                    bg_voice_name=DEFAULT_BG_GOOGLE_VOICE,
                                    bg_language_code="bg-BG",
                                ),
                                google_client=google_client,
                            )
                            result = generator.generate(script, "ep")

            self.assertTrue(result.exists())
            self.assertEqual(google_client.synthesize_speech.call_count, 2)
            set_voice_calls = [
                c for c in mock_engine.setProperty.call_args_list if c[0][0] == "voice"
            ]
            voice_ids_used = [c[0][1] for c in set_voice_calls]
            self.assertIn("en-voice-id", voice_ids_used)
            self.assertNotIn("bg-voice-id", voice_ids_used)

    def test_single_voice_google_english_uses_google_client(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            class DummyPaths:
                root = project_root
                audio = project_root / "audio"

                def ensure(self) -> None:
                    self.audio.mkdir(parents=True, exist_ok=True)

            google_client = Mock()
            google_client.synthesize_speech.return_value = SimpleNamespace(
                audio_content=self._make_wav_bytes()
            )
            fake_google = SimpleNamespace(
                SynthesisInput=lambda *, text: {"text": text},
                VoiceSelectionParams=lambda **kwargs: kwargs,
                AudioConfig=lambda **kwargs: kwargs,
                AudioEncoding=SimpleNamespace(LINEAR16="LINEAR16"),
            )

            with patch(
                "knigovishte_podcast.services.tts.ProjectPaths.from_root",
                return_value=DummyPaths(),
            ):
                with patch("knigovishte_podcast.services.tts.pyttsx3.init") as init_local:
                    with patch(
                        "knigovishte_podcast.services.tts.google_texttospeech",
                        fake_google,
                    ):
                        with patch(
                            "knigovishte_podcast.services.tts._convert_wav_to_mp3",
                            side_effect=self._fake_mp3_export,
                        ):
                            generator = Pyttsx3PodcastAudioGenerator(
                                voice_name=DEFAULT_EN_GOOGLE_VOICE,
                                google_tts_config=GoogleTTSConfig(
                                    en_voice_name=DEFAULT_EN_GOOGLE_VOICE,
                                    en_language_code="en-US",
                                    bg_voice_name=DEFAULT_BG_GOOGLE_VOICE,
                                    bg_language_code="bg-BG",
                                ),
                                google_client=google_client,
                            )
                            result = generator.generate("Hello world", "ep")

            self.assertTrue(result.exists())
            init_local.assert_not_called()
            google_client.synthesize_speech.assert_called_once_with(
                input={"text": "Hello world"},
                voice={"language_code": "en-US", "name": DEFAULT_EN_GOOGLE_VOICE},
                audio_config={"audio_encoding": "LINEAR16"},
            )

    def test_single_voice_google_english_override_keeps_google_path(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            class DummyPaths:
                root = project_root
                audio = project_root / "audio"

                def ensure(self) -> None:
                    self.audio.mkdir(parents=True, exist_ok=True)

            google_client = Mock()
            google_client.synthesize_speech.return_value = SimpleNamespace(
                audio_content=self._make_wav_bytes()
            )
            fake_google = SimpleNamespace(
                SynthesisInput=lambda *, text: {"text": text},
                VoiceSelectionParams=lambda **kwargs: kwargs,
                AudioConfig=lambda **kwargs: kwargs,
                AudioEncoding=SimpleNamespace(LINEAR16="LINEAR16"),
            )
            english_override = "en-GB-Standard-A"

            with patch(
                "knigovishte_podcast.services.tts.ProjectPaths.from_root",
                return_value=DummyPaths(),
            ):
                with patch("knigovishte_podcast.services.tts.pyttsx3.init") as init_local:
                    with patch(
                        "knigovishte_podcast.services.tts.google_texttospeech",
                        fake_google,
                    ):
                        with patch(
                            "knigovishte_podcast.services.tts._convert_wav_to_mp3",
                            side_effect=self._fake_mp3_export,
                        ):
                            generator = Pyttsx3PodcastAudioGenerator(
                                voice_name=english_override,
                                google_tts_config=GoogleTTSConfig(
                                    en_voice_name=DEFAULT_EN_GOOGLE_VOICE,
                                    en_language_code="en-US",
                                    bg_voice_name=DEFAULT_BG_GOOGLE_VOICE,
                                    bg_language_code="bg-BG",
                                ),
                                google_client=google_client,
                            )
                            result = generator.generate("Hello world", "ep")

            self.assertTrue(result.exists())
            init_local.assert_not_called()
            google_client.synthesize_speech.assert_called_once_with(
                input={"text": "Hello world"},
                voice={"language_code": "en-GB", "name": english_override},
                audio_config={"audio_encoding": "LINEAR16"},
            )

    def test_bilingual_google_english_override_keeps_google_path(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            class DummyPaths:
                root = project_root
                audio = project_root / "audio"

                def ensure(self) -> None:
                    self.audio.mkdir(parents=True, exist_ok=True)

            audio_path = project_root / "audio" / f"ep{AUDIO_FILE_EXTENSION}"
            mock_engine = self._make_dummy_engine(audio_path)
            google_client = Mock()
            google_client.synthesize_speech.return_value = SimpleNamespace(
                audio_content=self._make_wav_bytes()
            )
            fake_google = SimpleNamespace(
                SynthesisInput=lambda *, text: {"text": text},
                VoiceSelectionParams=lambda **kwargs: kwargs,
                AudioConfig=lambda **kwargs: kwargs,
                AudioEncoding=SimpleNamespace(LINEAR16="LINEAR16"),
            )
            english_override = "en-GB-Standard-A"
            script = "English title: Foo\nBulgarian title: Бар\n\nHello.\nЗдравей."

            with patch(
                "knigovishte_podcast.services.tts.ProjectPaths.from_root",
                return_value=DummyPaths(),
            ):
                with patch(
                    "knigovishte_podcast.services.tts.pyttsx3.init",
                    return_value=mock_engine,
                ):
                    with patch(
                        "knigovishte_podcast.services.tts.google_texttospeech",
                        fake_google,
                    ):
                        with patch(
                            "knigovishte_podcast.services.tts._convert_wav_to_mp3",
                            side_effect=self._fake_mp3_export,
                        ):
                            generator = Pyttsx3PodcastAudioGenerator(
                                voice_name=english_override,
                                bg_voice_name="bulgarian",
                                google_tts_config=GoogleTTSConfig(
                                    en_voice_name=DEFAULT_EN_GOOGLE_VOICE,
                                    en_language_code="en-US",
                                    bg_voice_name=DEFAULT_BG_GOOGLE_VOICE,
                                    bg_language_code="bg-BG",
                                ),
                                google_client=google_client,
                            )
                            result = generator.generate(script, "ep")

            self.assertTrue(result.exists())
            synthesize_calls = google_client.synthesize_speech.call_args_list
            self.assertEqual(len(synthesize_calls), 2)
            self.assertEqual(
                [call.kwargs["input"] for call in synthesize_calls],
                [{"text": "English title: Foo"}, {"text": "Hello."}],
            )
            self.assertEqual(
                [call.kwargs["voice"] for call in synthesize_calls],
                [
                    {"language_code": "en-GB", "name": english_override},
                    {"language_code": "en-GB", "name": english_override},
                ],
            )
            set_voice_calls = [
                c for c in mock_engine.setProperty.call_args_list if c[0][0] == "voice"
            ]
            voice_ids_used = [c[0][1] for c in set_voice_calls]
            self.assertIn("bg-voice-id", voice_ids_used)
            self.assertNotIn("en-voice-id", voice_ids_used)

    def test_speaking_rate_google(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            class DummyPaths:
                root = project_root
                audio = project_root / "audio"
                def ensure(self) -> None:
                    self.audio.mkdir(parents=True, exist_ok=True)

            google_client = MagicMock()
            google_client.synthesize_speech.return_value = SimpleNamespace(
                audio_content=self._make_wav_bytes()
            )

            en_voice = "en-US-Standard-F"
            bg_voice = "bg-BG-Standard-B"

            with patch(
                "knigovishte_podcast.services.tts.ProjectPaths.from_root",
                return_value=DummyPaths(),
            ):
                with patch(
                    "knigovishte_podcast.services.tts._convert_wav_to_mp3",
                    side_effect=self._fake_mp3_export,
                ):
                    generator = Pyttsx3PodcastAudioGenerator(
                        voice_name=en_voice,
                        bg_voice_name=bg_voice,
                        google_client=google_client,
                        bg_speaking_rate=0.8,
                    )
                    
                    script = "English title: Intro\nBulgarian title: Заглавие"
                    generator.generate(script, "ep")

            calls = google_client.synthesize_speech.call_args_list
            self.assertEqual(len(calls), 2)
            
            en_audio_config = calls[0].kwargs["audio_config"]
            self.assertNotIn("speaking_rate", en_audio_config)
            
            bg_audio_config = calls[1].kwargs["audio_config"]
            self.assertEqual(bg_audio_config.speaking_rate, 0.8)

    def test_speaking_rate_local(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)

            class DummyPaths:
                root = project_root
                audio = project_root / "audio"
                def ensure(self) -> None:
                    self.audio.mkdir(parents=True, exist_ok=True)

            audio_path = project_root / "audio" / f"ep{AUDIO_FILE_EXTENSION}"
            mock_engine = self._make_dummy_engine(audio_path)
            
            mock_engine.getProperty.return_value = [
                SimpleNamespace(id="local_en", name="English Local"),
                SimpleNamespace(id="local_bg", name="Bulgarian Local"),
            ]

            en_voice = "local_en"
            bg_voice = "local_bg"

            with patch(
                "knigovishte_podcast.services.tts.ProjectPaths.from_root",
                return_value=DummyPaths(),
            ):
                with patch("knigovishte_podcast.services.tts.pyttsx3.init", return_value=mock_engine):
                    with patch(
                        "knigovishte_podcast.services.tts._convert_wav_to_mp3",
                        side_effect=self._fake_mp3_export,
                    ):
                        generator = Pyttsx3PodcastAudioGenerator(
                            voice_name=en_voice,
                            bg_voice_name=bg_voice,
                            rate=150,
                            bg_speaking_rate=0.8,
                        )
                        generator.generate("English title: Intro\nBulgarian title: Заглавие", "ep")

            set_rate_calls = [
                call for call in mock_engine.setProperty.call_args_list if call[0][0] == "rate"
            ]
            self.assertEqual(len(set_rate_calls), 2)
            self.assertEqual(set_rate_calls[0][0][1], 150)
            self.assertEqual(set_rate_calls[1][0][1], 120)


class BuildDefaultAudioGeneratorTests(unittest.TestCase):
    def test_default_factory_uses_google_english_and_bulgarian_voices(self) -> None:
        config = GoogleTTSConfig(
            en_voice_name=DEFAULT_EN_GOOGLE_VOICE,
            en_language_code="en-US",
            bg_voice_name=DEFAULT_BG_GOOGLE_VOICE,
            bg_language_code="bg-BG",
        )
        with patch(
            "knigovishte_podcast.services.tts.GoogleTTSConfig.from_env",
            return_value=config,
        ):
            generator = build_default_audio_generator()

        self.assertEqual(generator.voice_name, DEFAULT_EN_GOOGLE_VOICE)
        self.assertEqual(generator.bg_voice_name, DEFAULT_BG_GOOGLE_VOICE)
        self.assertEqual(generator.google_tts_config, config)


class ConvertWavToMp3Tests(unittest.TestCase):
    def test_convert_wav_to_mp3_invokes_ffmpeg(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "episode.wav"
            output_path = root / "episode.mp3"
            input_path.write_bytes(b"wav")

            with patch(
                "knigovishte_podcast.services.tts.imageio_ffmpeg",
                SimpleNamespace(get_ffmpeg_exe=lambda: "ffmpeg.exe"),
            ):
                with patch("knigovishte_podcast.services.tts.subprocess.run") as run_mock:
                    _convert_wav_to_mp3(input_path, output_path)

        run_mock.assert_called_once_with(
            [
                "ffmpeg.exe",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(input_path),
                "-vn",
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "128k",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_convert_wav_to_mp3_surfaces_ffmpeg_errors(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            input_path = root / "episode.wav"
            output_path = root / "episode.mp3"
            input_path.write_bytes(b"wav")

            with patch(
                "knigovishte_podcast.services.tts.imageio_ffmpeg",
                SimpleNamespace(get_ffmpeg_exe=lambda: "ffmpeg.exe"),
            ):
                with patch(
                    "knigovishte_podcast.services.tts.subprocess.run",
                    side_effect=subprocess.CalledProcessError(
                        returncode=1,
                        cmd=["ffmpeg.exe"],
                        stderr="encoder failed",
                    ),
                ):
                    with self.assertRaisesRegex(RuntimeError, "MP3 export failed: encoder failed"):
                        _convert_wav_to_mp3(input_path, output_path)


if __name__ == "__main__":
    unittest.main()
