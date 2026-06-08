from __future__ import annotations

import ctypes
import subprocess
import wave
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pyttsx3

from ..config import (
    GoogleTTSConfig,
    ProjectPaths,
    google_language_code_from_voice_name,
)

AUDIO_FILE_EXTENSION = ".mp3"
_INTERMEDIATE_AUDIO_FILE_EXTENSION = ".wav"
DEFAULT_EN_GOOGLE_VOICE = "en-US-Standard-F"
DEFAULT_BG_GOOGLE_VOICE = "bg-BG-Standard-B"
_COM_ALREADY_INITIALIZED = 1
_COM_CHANGED_MODE = 0x80010106

_BG_LINE_PREFIXES = ("Bulgarian:", "Bulgarian title:")
_EN_LINE_PREFIXES = ("English:", "English title:")
_EN_CONTROL_LINES = {
    "Let's hear that again.",
    "That's the end of this story. Thanks for listening!",
}
_BG_CONTROL_LINES = {"Сега ще го повторим."}

_google_texttospeech: Any | None
try:
    from google.cloud import texttospeech as _google_texttospeech
except ImportError:
    _google_texttospeech = None

try:
    import imageio_ffmpeg as _imageio_ffmpeg
except ImportError:
    _imageio_ffmpeg = None

google_texttospeech: Any | None = _google_texttospeech
imageio_ffmpeg: Any | None = _imageio_ffmpeg


class PodcastAudioGenerator(ABC):
    @abstractmethod
    def generate(self, script_text: str, episode_slug: str) -> Path:
        raise NotImplementedError


class PlaceholderPodcastAudioGenerator(PodcastAudioGenerator):
    def generate(self, script_text: str, episode_slug: str) -> Path:
        raise NotImplementedError(
            "Audio generation is not implemented yet. Add the selected TTS engine behind this interface."
        )


class Pyttsx3PodcastAudioGenerator(PodcastAudioGenerator):
    """Generate podcast audio with local or Google TTS voices."""

    def __init__(
        self,
        voice_name: str | None = None,
        rate: int | None = None,
        volume: float | None = None,
        bg_voice_name: str | None = None,
        google_tts_config: GoogleTTSConfig | None = None,
        google_client: Any | None = None,
    ) -> None:
        self.voice_name = voice_name
        self.rate = rate
        self.volume = volume
        self.bg_voice_name = bg_voice_name
        self.google_tts_config = google_tts_config or GoogleTTSConfig.from_env()
        self._google_client = google_client

    def generate(self, script_text: str, episode_slug: str) -> Path:
        if not script_text or not script_text.strip():
            raise ValueError("script_text must not be empty.")
        if not episode_slug or not episode_slug.strip():
            raise ValueError("episode_slug must not be empty.")

        normalized_slug = episode_slug.strip()

        project_paths = ProjectPaths.from_root()
        project_paths.ensure()

        audio_path = project_paths.audio / f"{normalized_slug}{AUDIO_FILE_EXTENSION}"
        intermediate_audio_path = (
            project_paths.audio / f"_{normalized_slug}{_INTERMEDIATE_AUDIO_FILE_EXTENSION}"
        )
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        if audio_path.exists():
            audio_path.unlink()
        intermediate_audio_path.unlink(missing_ok=True)

        try:
            if self.bg_voice_name is not None:
                self._generate_bilingual(script_text, intermediate_audio_path)
            else:
                self._generate_single_voice(script_text, intermediate_audio_path)
            if not intermediate_audio_path.exists():
                raise RuntimeError(
                    "Audio generation failed; intermediate WAV was not created: "
                    f"{intermediate_audio_path}"
                )
            _convert_wav_to_mp3(intermediate_audio_path, audio_path)
        finally:
            intermediate_audio_path.unlink(missing_ok=True)

        if not audio_path.exists():
            raise RuntimeError(
                f"Audio generation failed; file was not created: {audio_path}"
            )

        return audio_path

    def _generate_single_voice(self, script_text: str, audio_path: Path) -> None:
        if _should_route_google("en", self.voice_name):
            self._synthesize_google_segment(
                script_text,
                audio_path,
                voice_name=self.voice_name,
                language_code=self._google_language_code_for_voice("en", self.voice_name),
            )
            return
        self._synthesize_local_segment(script_text, audio_path, self.voice_name)

    def _synthesize_local_segment(
        self,
        text: str,
        audio_path: Path,
        voice_name: str | None,
    ) -> None:
        with _windows_com_initialized():
            engine = pyttsx3.init()
            try:
                if self.rate is not None:
                    engine.setProperty("rate", self.rate)
                if self.volume is not None:
                    engine.setProperty("volume", self.volume)
                if voice_name is not None:
                    self._set_voice(engine, voice_name)

                engine.save_to_file(text, str(audio_path))
                engine.runAndWait()
            finally:
                engine.stop()

    def _generate_bilingual(self, script_text: str, audio_path: Path) -> None:
        segments = _split_script_by_language(script_text)
        temp_files: list[Path] = []
        try:
            for i, (lang, text) in enumerate(segments):
                temp_path = (
                    audio_path.parent
                    / f"_{audio_path.stem}_part{i}{_INTERMEDIATE_AUDIO_FILE_EXTENSION}"
                )
                voice_name = self.bg_voice_name if lang == "bg" else self.voice_name
                if _should_route_google(lang, voice_name):
                    self._synthesize_google_segment(
                        text,
                        temp_path,
                        voice_name=voice_name,
                        language_code=self._google_language_code_for_voice(lang, voice_name),
                    )
                else:
                    self._synthesize_local_segment(text, temp_path, voice_name)
                temp_files.append(temp_path)
            _concatenate_wav_files(temp_files, audio_path)
        finally:
            for tf in temp_files:
                tf.unlink(missing_ok=True)

    def _set_voice(self, engine: pyttsx3.Engine, voice_name: str) -> None:
        requested_voice = voice_name.strip().lower()
        if not requested_voice:
            raise ValueError("voice_name must not be blank when provided.")

        voices = engine.getProperty("voices") or []
        for voice in voices:
            v_name = getattr(voice, "name", "") or ""
            v_id = getattr(voice, "id", "") or ""
            if requested_voice in v_name.lower() or requested_voice in v_id.lower():
                engine.setProperty("voice", v_id)
                return

        raise ValueError(f"Requested voice not available: {voice_name}")

    def _synthesize_google_segment(
        self,
        text: str,
        output_path: Path,
        *,
        voice_name: str | None,
        language_code: str,
    ) -> None:
        voice_name = (voice_name or "").strip()
        if not voice_name:
            raise ValueError("Google voice_name must not be blank when provided.")
        google_api = google_texttospeech
        if google_api is None:
            raise RuntimeError(
                "Google Cloud Text-to-Speech is unavailable. Install google-cloud-texttospeech "
                "and configure GOOGLE_APPLICATION_CREDENTIALS to render Google audio."
            )

        client = self._get_google_client()
        response = client.synthesize_speech(
            input=google_api.SynthesisInput(text=text),
            voice=google_api.VoiceSelectionParams(
                language_code=language_code,
                name=voice_name,
            ),
            audio_config=google_api.AudioConfig(
                audio_encoding=google_api.AudioEncoding.LINEAR16
            ),
        )
        audio_content = getattr(response, "audio_content", b"")
        if not audio_content:
            raise RuntimeError("Google Cloud TTS returned empty audio content.")
        output_path.write_bytes(audio_content)

    def _get_google_client(self) -> Any:
        google_api = google_texttospeech
        if google_api is None:
            raise RuntimeError(
                "Google Cloud Text-to-Speech is unavailable. Install google-cloud-texttospeech "
                "and configure GOOGLE_APPLICATION_CREDENTIALS to render Google audio."
            )
        if self._google_client is None:
            try:
                self._google_client = google_api.TextToSpeechClient()
            except Exception as exc:
                raise RuntimeError(
                    "Google Cloud Text-to-Speech is not configured. "
                    "Set GOOGLE_APPLICATION_CREDENTIALS to a service-account JSON file."
                ) from exc
        return self._google_client

    def _google_language_code(self, lang: str) -> str:
        if lang == "bg":
            return self.google_tts_config.bg_language_code
        return self.google_tts_config.en_language_code

    def _google_language_code_for_voice(self, lang: str, voice_name: str | None) -> str:
        fallback = self._google_language_code(lang)
        if not _should_route_google(lang, voice_name):
            return fallback
        return google_language_code_from_voice_name(voice_name or "", fallback=fallback)


def build_default_audio_generator(
    *,
    voice_name: str | None = None,
    bg_voice_name: str | None = None,
    rate: int | None = None,
    volume: float | None = None,
) -> Pyttsx3PodcastAudioGenerator:
    google_tts_config = GoogleTTSConfig.from_env()
    return Pyttsx3PodcastAudioGenerator(
        voice_name=voice_name or google_tts_config.en_voice_name,
        rate=rate,
        volume=volume,
        bg_voice_name=bg_voice_name or google_tts_config.bg_voice_name,
        google_tts_config=google_tts_config,
    )


def _split_script_by_language(script_text: str) -> list[tuple[str, str]]:
    """Split a podcast script into (language, text) segments.

    Title lines still use explicit language prefixes. Inside the repeated
    bilingual body, unprefixed sentence lines alternate English/Bulgarian.
    Consecutive lines with the same tag are merged into a single segment.
    """
    segments: list[tuple[str, str]] = []
    current_lang: str = "en"
    current_lines: list[str] = []
    in_bilingual_body = False
    next_body_lang = "en"

    for line in script_text.splitlines():
        stripped_line = line.strip()
        if not stripped_line:
            lang = current_lang
        elif any(line.startswith(p) for p in _EN_LINE_PREFIXES):
            lang = "en"
            in_bilingual_body = line.startswith("English:")
            if in_bilingual_body:
                next_body_lang = "bg"
        elif any(line.startswith(p) for p in _BG_LINE_PREFIXES):
            lang = "bg"
            in_bilingual_body = True
            next_body_lang = "en"
        elif line in _EN_CONTROL_LINES:
            lang = "en"
            in_bilingual_body = False
        elif line in _BG_CONTROL_LINES:
            lang = "bg"
            in_bilingual_body = True
            next_body_lang = "en"
        elif in_bilingual_body:
            lang = next_body_lang
            next_body_lang = "bg" if lang == "en" else "en"
        else:
            lang = "en"

        if lang != current_lang:
            if current_lines:
                segments.append((current_lang, "\n".join(current_lines)))
            current_lang = lang
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        segments.append((current_lang, "\n".join(current_lines)))

    return segments


def _is_google_voice(
    voice_name: str | None,
    *,
    language_code_prefix: str | None = None,
) -> bool:
    normalized_voice = (voice_name or "").strip().lower()
    if not normalized_voice:
        return False
    if language_code_prefix is not None:
        normalized_prefix = language_code_prefix.lower().rstrip("-")
        return normalized_voice.startswith(f"{normalized_prefix}-")
    return normalized_voice.startswith(("bg-bg-", "en-"))


def _should_route_google(lang: str, voice_name: str | None) -> bool:
    if lang == "bg":
        return _is_google_voice(voice_name, language_code_prefix="bg-bg")
    return _is_google_voice(voice_name, language_code_prefix="en")


@contextmanager
def _windows_com_initialized():
    """Initialize COM on the current thread before local Windows TTS usage."""
    ole32 = _ole32()
    if ole32 is None:
        yield
        return

    hr = ole32.CoInitialize(None)
    hr_code = hr & 0xFFFFFFFF
    should_uninitialize = hr in (0, _COM_ALREADY_INITIALIZED)
    if hr_code == _COM_CHANGED_MODE:
        should_uninitialize = False
    elif not should_uninitialize:
        raise OSError(f"Failed to initialize Windows COM for local TTS (HRESULT 0x{hr_code:08X}).")

    try:
        yield
    finally:
        if should_uninitialize:
            ole32.CoUninitialize()


def _ole32():
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return None
    return windll.ole32


def _concatenate_wav_files(input_paths: list[Path], output_path: Path) -> None:
    """Concatenate multiple WAV files into a single output WAV file."""
    existing = [p for p in input_paths if p.exists()]
    if not existing:
        return

    with wave.open(str(output_path), "wb") as out_wav:
        for i, path in enumerate(existing):
            with wave.open(str(path), "rb") as in_wav:
                if i == 0:
                    out_wav.setparams(in_wav.getparams())
                out_wav.writeframes(in_wav.readframes(in_wav.getnframes()))


def _convert_wav_to_mp3(input_path: Path, output_path: Path) -> None:
    ffmpeg_api = imageio_ffmpeg
    if ffmpeg_api is None:
        raise RuntimeError(
            "MP3 export is unavailable. Install imageio-ffmpeg to convert rendered WAV audio."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    try:
        ffmpeg_path = ffmpeg_api.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError("MP3 export is unavailable because FFmpeg could not be resolved.") from exc

    try:
        subprocess.run(
            [
                ffmpeg_path,
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
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise RuntimeError(f"MP3 export failed: {message}") from exc
