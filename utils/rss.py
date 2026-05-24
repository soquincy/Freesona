# utils/rss.py: RSS/Atom parsing and feed config helpers.
from __future__ import annotations

from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import html
import re
import xml.etree.ElementTree as ET

from utils.config import load_config, save_config

RSS_FEEDS_KEY    = "rss_feeds"
RSS_SEEN_KEY     = "rss_seen"       # set of seen article links, persisted in config.json
RSS_DISABLED_KEY = "rss_disabled"   # built-in feeds the user has explicitly removed

DEFAULT_RSS_FEEDS: dict[str, str] = {
    "bbc-world":  "https://feeds.bbci.co.uk/news/world/rss.xml",
    "bbc-tech":   "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "ap-world":   "https://rss.app/feeds/Ul6tmWMDMgxBOBmv.xml",
    "aljazeera":  "https://www.aljazeera.com/xml/rss/all.xml",
    "dw-world":   "https://rss.dw.com/rdf/rss-en-all",
}


@dataclass
class FeedItem:
    title:     str
    link:      str
    published: str = ""
    summary:   str = ""


# ---------------------------------------------------------------------------
# Feed CRUD
# ---------------------------------------------------------------------------

def load_rss_feeds(config: dict | None = None) -> dict[str, str]:
    config   = config or load_config()
    disabled = set(config.get(RSS_DISABLED_KEY, []))
    feeds    = {k: v for k, v in DEFAULT_RSS_FEEDS.items() if k not in disabled}
    saved    = config.get(RSS_FEEDS_KEY, {})
    if isinstance(saved, dict):
        for name, url in saved.items():
            if isinstance(name, str) and isinstance(url, str) and url.strip():
                feeds[name.lower().strip()] = url.strip()
    return feeds


def save_rss_feed(name: str, url: str) -> None:
    config = load_config()
    # If re-adding a previously disabled built-in, un-disable it
    disabled: list = config.setdefault(RSS_DISABLED_KEY, [])
    key = name.lower().strip()
    if key in disabled:
        disabled.remove(key)
    feeds = config.setdefault(RSS_FEEDS_KEY, {})
    feeds[key] = url.strip()
    save_config(config)


def delete_rss_feed(name: str) -> bool:
    """
    Remove a feed. Built-in feeds are added to a disabled list rather than
    truly deleted (since they live in code, not config). Custom feeds are
    removed from config entirely. Returns True if anything was removed.
    """
    config  = load_config()
    key     = name.lower().strip()
    changed = False

    # Remove from custom feeds if present
    feeds = config.setdefault(RSS_FEEDS_KEY, {})
    if key in feeds:
        del feeds[key]
        changed = True

    # Disable built-in feeds
    if key in DEFAULT_RSS_FEEDS:
        disabled: list = config.setdefault(RSS_DISABLED_KEY, [])
        if key not in disabled:
            disabled.append(key)
        changed = True

    if changed:
        save_config(config)
    return changed


# ---------------------------------------------------------------------------
# Seen-link tracking (deduplication for auto-posting)
# ---------------------------------------------------------------------------

SEEN_CAP = 500   # max links to remember; oldest are evicted


def load_seen_links(config: dict | None = None) -> set[str]:
    config = config or load_config()
    return set(config.get(RSS_SEEN_KEY, []))


def mark_links_seen(links: list[str]) -> None:
    if not links:
        return
    config = load_config()
    seen: list = config.setdefault(RSS_SEEN_KEY, [])
    for link in links:
        if link and link not in seen:
            seen.append(link)
    # Evict oldest entries beyond cap
    if len(seen) > SEEN_CAP:
        config[RSS_SEEN_KEY] = seen[-SEEN_CAP:]
    else:
        config[RSS_SEEN_KEY] = seen
    save_config(config)


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

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
    root     = ET.fromstring(xml_text)
    root_tag = root.tag.rsplit("}", 1)[-1].lower()
    if root_tag == "rss":
        channel = next(
            (c for c in root.iter() if c.tag.rsplit("}", 1)[-1].lower() == "channel"),
            root,
        )
        nodes = [c for c in list(channel) if c.tag.rsplit("}", 1)[-1].lower() == "item"]
    else:
        nodes = [c for c in list(root) if c.tag.rsplit("}", 1)[-1].lower() == "entry"]

    items: list[FeedItem] = []
    for node in nodes[:limit]:
        title     = child_text(node, ("title",)) or "(untitled)"
        link      = child_text(node, ("link",)) or child_attr(node, "link", "href")
        published = child_text(node, ("pubdate", "published", "updated"))
        summary   = child_text(node, ("description", "summary", "content"))
        items.append(FeedItem(
            title=strip_html(title),
            link=link,
            published=normalize_date(published),
            summary=strip_html(summary),
        ))
    return items