from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import ProjectPaths
from ..models import Article


@dataclass(frozen=True)
class DuplicateArticleError(RuntimeError):
    article: Article
    audio_path: Path

    def __post_init__(self) -> None:
        super().__init__(
            f"Article was already used for audio generation: {self.article.source_url}"
        )


class ArticleAudioManifest:
    def __init__(self, *, project_root: Path, manifest_path: Path) -> None:
        self.project_root = project_root
        self.manifest_path = manifest_path

    @classmethod
    def for_paths(cls, paths: ProjectPaths) -> "ArticleAudioManifest":
        return cls(
            project_root=paths.root,
            manifest_path=paths.audio / "manifest.json",
        )

    def find_existing_audio(self, article: Article) -> Path | None:
        entry = self._load_entries().get(self.article_hash(article))
        if entry is None:
            return None

        audio_path = self.project_root / entry["audio_path"]
        if audio_path.exists():
            return audio_path
        return None

    def record(self, article: Article, audio_path: Path) -> None:
        relative_audio_path = audio_path.relative_to(self.project_root)
        payload = self._load_manifest()
        payload["articles"][self.article_hash(article)] = {
            "audio_path": str(relative_audio_path),
            "sentence_count": len(article.sentences_bg),
            "source_url": article.source_url,
            "title_bg": article.title_bg,
        }
        self._write_manifest(payload)

    @staticmethod
    def article_hash(article: Article) -> str:
        normalized_article = {
            "title_bg": _normalize_text(article.title_bg),
            "sentences_bg": [_normalize_text(sentence) for sentence in article.sentences_bg],
        }
        encoded = json.dumps(
            normalized_article,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _load_entries(self) -> dict[str, dict[str, Any]]:
        payload = self._load_manifest()
        return payload["articles"]

    def _load_manifest(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return {"version": 1, "articles": {}}

        with self.manifest_path.open(encoding="utf-8") as manifest_file:
            payload = json.load(manifest_file)
        payload.setdefault("version", 1)
        payload.setdefault("articles", {})
        return payload

    def _write_manifest(self, payload: dict[str, object]) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.manifest_path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self.manifest_path)


def _normalize_text(text: str) -> str:
    return " ".join(text.split())
