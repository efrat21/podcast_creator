from __future__ import annotations
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import quote
import re

ROOT = Path(__file__).resolve().parents[1]
RSS_DIR = ROOT / "data" / "rss"
EPISODES_DIR = RSS_DIR / "episodes"
SCRIPTS_DIR = ROOT / "data" / "scripts"
OUT_PATH = RSS_DIR / "podcast.xml"

SUPPORTED = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".wav": "audio/wav",
}
VIJTE_PREFIX = re.compile(r"^vijte-\d+(?:-|$)", re.IGNORECASE)


def english_title_from_metadata(stem: str) -> str | None:
    for suffix in (".translation.txt", ".txt"):
        p = SCRIPTS_DIR / f"{stem}{suffix}"
        if p.is_file():
            for line in p.read_text(encoding="utf-8").splitlines():
                label, sep, val = line.partition(":")
                if sep and label.strip().lower() == "english title":
                    title = val.strip()
                    if title:
                        return title
    return None


def title_from_filename(name: str) -> str:
    stem = Path(name).stem
    meta = english_title_from_metadata(stem)
    if meta:
        return meta
    norm = VIJTE_PREFIX.sub("", stem)
    title = norm.replace("-", " ").strip()
    return title or stem


def build_feed():
    channel_info = {
        "title": "Knigovishte Podcast Builder",
        "link": "http://192.168.100.13:8001/podcast.xml",
        "description": "Local LAN RSS feed generated from existing podcast audio artifacts.",
        "language": "en",
        "image_url": None,
    }
    if OUT_PATH.exists():
        try:
            tree = ET.parse(OUT_PATH)
            root = tree.getroot()
            ch = root.find("channel")
            if ch is not None:
                t = ch.find("title")
                if t is not None and t.text:
                    channel_info["title"] = t.text
                l = ch.find("link")
                if l is not None and l.text:
                    channel_info["link"] = l.text
                d = ch.find("description")
                if d is not None and d.text:
                    channel_info["description"] = d.text
                lang = ch.find("language")
                if lang is not None and lang.text:
                    channel_info["language"] = lang.text
                img = ch.find("image")
                if img is not None:
                    url = img.find("url")
                    if url is not None and url.text:
                        channel_info["image_url"] = url.text
        except Exception:
            pass

    if not EPISODES_DIR.exists():
        print(f"Episodes directory not found: {EPISODES_DIR}")
        return

    files = [p for p in EPISODES_DIR.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    rss = ET.Element("rss", version="2.0")
    ET.register_namespace("itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = channel_info["title"]
    ET.SubElement(channel, "link").text = channel_info["link"]
    ET.SubElement(channel, "description").text = channel_info["description"]
    ET.SubElement(channel, "language").text = channel_info["language"]
    if channel_info["image_url"]:
        image = ET.SubElement(channel, "image")
        ET.SubElement(image, "url").text = channel_info["image_url"]
        ET.SubElement(image, "title").text = channel_info["title"]
        ET.SubElement(image, "link").text = channel_info["link"]
        ET.SubElement(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}image", href=channel_info["image_url"])

    public_base = channel_info["link"].rsplit("/", 1)[0]
    for p in files:
        item = ET.SubElement(channel, "item")
        title = title_from_filename(p.name)
        ET.SubElement(item, "title").text = title
        enclosure_url = f"{public_base}/episodes/{quote(p.name)}"
        ET.SubElement(item, "guid").text = enclosure_url
        stat = p.stat()
        published_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        ET.SubElement(item, "pubDate").text = format_datetime(published_at)
        ET.SubElement(
            item,
            "enclosure",
            url=enclosure_url,
            length=str(stat.st_size),
            type=SUPPORTED[p.suffix.lower()],
        )

    xml = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
    OUT_PATH.write_bytes(xml)
    print(f"Wrote {OUT_PATH} with {len(files)} items")

if __name__ == "__main__":
    build_feed()
