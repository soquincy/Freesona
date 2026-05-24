# utils/rss.py: RSS/Atom parsing and feed config helpers.

from __future__ import annotations

from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import html
import re
import xml.etree.ElementTree as ET

from utils.config import load_config, save_config

RSS_FEEDS_KEY = "rss_feeds"

DEFAULT_RSS_FEEDS = {
    "afpbb": "https://feeds.afpbb.com/rss/afpbb/afpbbnews",
}


@dataclass
class FeedItem:
    title: str
    link: str
    published: str = ""
    summary: str = ""


def load_rss_feeds(config: dict | None = None) -> dict[str, str]:
    config = config or load_config()
    feeds = DEFAULT_RSS_FEEDS.copy()
    saved = config.get(RSS_FEEDS_KEY, {})
    if isinstance(saved, dict):
        for name, url in saved.items():
            if isinstance(name, str) and isinstance(url, str) and url.strip():
                feeds[name.lower().strip()] = url.strip()
    return feeds


def save_rss_feed(name: str, url: str) -> None:
    config = load_config()
    feeds = config.setdefault(RSS_FEEDS_KEY, {})
    feeds[name.lower().strip()] = url.strip()
    save_config(config)


def delete_rss_feed(name: str) -> bool:
    config = load_config()
    feeds = config.setdefault(RSS_FEEDS_KEY, {})
    key = name.lower().strip()
    if key in DEFAULT_RSS_FEEDS:
        return False
    existed = key in feeds
    feeds.pop(key, None)
    save_config(config)
    return existed


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def child_text(node: ET.Element, names: tuple[str, ...]) -> str:
    for child in list(node):
        tag = child.tag.rsplit("}", 1)[-1].lower()
        if tag in names and child.text:
            return child.text.strip()
    return ""


def child_attr(node: ET.Element, name: str, attr: str) -> str:
    for child in list(node):
        tag = child.tag.rsplit("}", 1)[-1].lower()
        if tag == name:
            value = child.attrib.get(attr)
            if value:
                return value.strip()
    return ""


def normalize_date(value: str) -> str:
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return value


def parse_feed(xml_text: str, limit: int = 5) -> list[FeedItem]:
    root = ET.fromstring(xml_text)
    root_tag = root.tag.rsplit("}", 1)[-1].lower()

    if root_tag == "rss":
        channel = next((child for child in root.iter() if child.tag.rsplit("}", 1)[-1].lower() == "channel"), root)
        nodes = [child for child in list(channel) if child.tag.rsplit("}", 1)[-1].lower() == "item"]
    else:
        nodes = [child for child in list(root) if child.tag.rsplit("}", 1)[-1].lower() == "entry"]

    items: list[FeedItem] = []
    for node in nodes[:limit]:
        title = child_text(node, ("title",)) or "(untitled)"
        link = child_text(node, ("link",)) or child_attr(node, "link", "href")
        published = child_text(node, ("pubdate", "published", "updated"))
        summary = child_text(node, ("description", "summary", "content"))
        items.append(FeedItem(
            title=strip_html(title),
            link=link,
            published=normalize_date(published),
            summary=strip_html(summary),
        ))
    return items
