from __future__ import annotations

import hashlib
import html as html_lib
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from common import (
    atomic_write_json,
    dedupe_keep_order,
    first_image_from_html,
    load_json,
    now_iso,
    parse_note_key,
    strip_html,
)
from http_client import get_or_raise, make_session


NOTE_IMAGE_HOSTS = frozenset({"assets.st-note.com", "assets.note.com"})
IMAGE_EXTENSIONS = (".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp")
BAD_IMAGE_PATH_PARTS = ("/avatar", "/icon", "/logo", "/profile_")
DEFAULT_CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "cache" / "note_thumbnail_cache.json"


def _iso_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = date_parser.parse(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        try:
            return parsedate_to_datetime(value).isoformat()
        except Exception:
            return None


def normalize_note_thumbnail_url(
    value: Any,
    declared_width: Any = None,
    declared_height: Any = None,
) -> str | None:
    """Return a safe note image URL without discarding its legitimate query."""
    if not isinstance(value, str):
        return None
    candidate = html_lib.unescape(value).strip()
    if not candidate or len(candidate) > 4096:
        return None
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    if parsed.scheme.lower() != "https" or parsed.username or parsed.password:
        return None
    if (parsed.hostname or "").lower() not in NOTE_IMAGE_HOSTS:
        return None
    path = parsed.path.lower()
    if not path.endswith(IMAGE_EXTENSIONS) or any(part in path for part in BAD_IMAGE_PATH_PARTS):
        return None

    def positive_int(raw: Any) -> int | None:
        try:
            number = int(str(raw))
            return number if number >= 0 else None
        except (TypeError, ValueError):
            return None

    width = positive_int(declared_width)
    height = positive_int(declared_height)
    if (width is not None and width < 200) or (height is not None and height < 100):
        return None
    query = parse_qs(parsed.query)
    query_widths = [positive_int(v) for key in ("width", "w") for v in query.get(key, [])]
    if any(width is not None and width < 200 for width in query_widths):
        return None
    return candidate


def _image_from_nodes(nodes: Any, source_name: str) -> tuple[str | None, str | None]:
    if not isinstance(nodes, list):
        return None, None
    for node in nodes:
        if not isinstance(node, dict):
            continue
        candidate = normalize_note_thumbnail_url(
            node.get("url") or node.get("href"),
            node.get("width"),
            node.get("height"),
        )
        if candidate:
            return candidate, source_name
    return None, None


def _feed_entry_image_details(entry: Any) -> tuple[str | None, str | None]:
    """Extract in the documented RSS priority order."""
    candidates = (
        ("media_thumbnail", "rss_media_thumbnail"),
        ("media_content", "rss_media_content"),
    )
    for attr, source_name in candidates:
        nodes = getattr(entry, attr, None) or entry.get(attr, [])
        image, source = _image_from_nodes(nodes, source_name)
        if image:
            return image, source

    enclosure_nodes: list[dict] = []
    for node in getattr(entry, "enclosures", None) or entry.get("enclosures", []):
        if isinstance(node, dict) and str(node.get("type") or "").lower().startswith("image/"):
            enclosure_nodes.append(node)
    for node in entry.get("links", []):
        if (
            isinstance(node, dict)
            and str(node.get("rel") or "").lower() == "enclosure"
            and str(node.get("type") or "").lower().startswith("image/")
        ):
            enclosure_nodes.append(node)
    image, source = _image_from_nodes(enclosure_nodes, "rss_image_enclosure")
    if image:
        return image, source

    for node in getattr(entry, "content", None) or entry.get("content", []):
        if not isinstance(node, dict):
            continue
        image = normalize_note_thumbnail_url(first_image_from_html(node.get("value")))
        if image:
            return image, "rss_content_encoded"
    for field in ("description", "summary"):
        image = normalize_note_thumbnail_url(first_image_from_html(entry.get(field)))
        if image:
            return image, f"rss_{field}"
    return None, None


def _feed_entry_image(entry: Any) -> str | None:
    return _feed_entry_image_details(entry)[0]


def _article_page_image_details(page_html: str) -> tuple[str | None, str | None]:
    soup = BeautifulSoup(page_html or "", "html.parser")
    for meta_key, source_name in (
        ("og:image", "page_og_image"),
        ("twitter:image", "page_twitter_image"),
        ("twitter:image:src", "page_twitter_image_src"),
    ):
        node = soup.find("meta", attrs={"property": meta_key}) or soup.find("meta", attrs={"name": meta_key})
        image = normalize_note_thumbnail_url(node.get("content") if node else None)
        if image:
            return image, source_name
    node = soup.select_one('link[rel~="image_src"][href]')
    image = normalize_note_thumbnail_url(node.get("href") if node else None)
    if image:
        return image, "page_image_src"
    return None, None


class NoteThumbnailResolver:
    """Share RSS images, page fetches and last-known-good thumbnails across sources."""

    def __init__(self, cache_path: Path, http_config: dict):
        self.cache_path = cache_path
        self.http_config = http_config
        self.timeout = int(http_config.get("timeout_seconds", 25))
        self.request_interval = float(http_config.get("note_page_interval_seconds", 0.4))
        self.cache: dict[str, dict[str, Any]] = self._load_cache()
        self.rss_images: dict[str, tuple[str, str]] = {}
        self.page_results: dict[str, str | None] = {}
        self.page_fetch_count = 0
        self._last_page_fetch_at: float | None = None

    def _load_cache(self) -> dict[str, dict[str, Any]]:
        try:
            data = load_json(self.cache_path, {})
        except (OSError, ValueError):
            return {}
        raw_items = data.get("items", {}) if isinstance(data, dict) else {}
        if not isinstance(raw_items, dict):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for note_id, raw in raw_items.items():
            record = raw if isinstance(raw, dict) else {"thumbnail_url": raw}
            image = normalize_note_thumbnail_url(record.get("thumbnail_url"))
            if not image:
                continue
            result[str(note_id)] = {
                "thumbnail_url": image,
                "article_url": record.get("article_url"),
                "source": record.get("source") or "cache",
                "last_success_at": record.get("last_success_at"),
            }
        return result

    def remember(self, note_id: str, article_url: str, image: Any, source: str) -> str | None:
        candidate = normalize_note_thumbnail_url(image)
        if not note_id or not candidate:
            return None
        existing = self.cache.get(note_id)
        if existing and existing.get("thumbnail_url") == candidate:
            return candidate
        self.cache[note_id] = {
            "thumbnail_url": candidate,
            "article_url": article_url,
            "source": source,
            "last_success_at": now_iso(),
        }
        return candidate

    def seed_from_public_docs(self, docs_root: Path) -> None:
        for path in sorted((docs_root / "note").rglob("*.json")):
            try:
                payload = load_json(path, {})
            except (OSError, ValueError):
                continue
            for item in payload.get("items", []) if isinstance(payload, dict) else []:
                self.remember(
                    str(item.get("id") or ""),
                    str(item.get("url") or ""),
                    item.get("thumbnail_url"),
                    "existing_public_json",
                )

    def register_rss_entries(self, entries: list[Any]) -> None:
        for entry in entries:
            article_url = str(entry.get("link") or "").strip()
            note_id = parse_note_key(article_url)
            if not note_id:
                continue
            image, source = _feed_entry_image_details(entry)
            if image and source:
                self.rss_images[note_id] = (image, source)
                self.remember(note_id, article_url, image, source)

    def resolve(
        self,
        note_id: str,
        article_url: str,
        current_image: Any,
        session: Any,
    ) -> str | None:
        current = normalize_note_thumbnail_url(current_image)
        if current:
            return self.remember(note_id, article_url, current, "existing_thumbnail_url")

        rss = self.rss_images.get(note_id)
        if rss:
            return self.remember(note_id, article_url, rss[0], rss[1])

        cached = self.cache.get(note_id, {}).get("thumbnail_url")
        cached = normalize_note_thumbnail_url(cached)
        if cached:
            return cached

        if note_id in self.page_results:
            return self.page_results[note_id]

        if self._last_page_fetch_at is not None and self.request_interval > 0:
            elapsed = time.monotonic() - self._last_page_fetch_at
            if elapsed < self.request_interval:
                time.sleep(self.request_interval - elapsed)
        image: str | None = None
        try:
            self.page_fetch_count += 1
            response = get_or_raise(session, article_url, self.timeout)
            image, source = _article_page_image_details(response.text)
            if image and source:
                image = self.remember(note_id, article_url, image, source)
        except Exception:
            image = None
        finally:
            self._last_page_fetch_at = time.monotonic()
            self.page_results[note_id] = image
        return image

    def save(self) -> None:
        payload = {
            "schema_version": "1.0",
            "items": {note_id: self.cache[note_id] for note_id in sorted(self.cache)},
        }
        atomic_write_json(self.cache_path, payload)


def _parse_feed(content: bytes, label: str) -> Any:
    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"{label} RSS解析失敗: {feed.bozo_exception}")
    return feed


def _own_resolver(http_config: dict) -> NoteThumbnailResolver:
    return NoteThumbnailResolver(DEFAULT_CACHE_PATH, http_config)


def fetch_account(source: dict, http_config: dict, resolver: NoteThumbnailResolver | None = None) -> dict:
    owns_resolver = resolver is None
    resolver = resolver or _own_resolver(http_config)
    session = make_session(http_config)
    timeout = int(http_config.get("timeout_seconds", 25))
    rss_url = source.get("rss_url") or source["url"].rstrip("/") + "/rss"
    response = get_or_raise(session, rss_url, timeout)
    feed = _parse_feed(response.content, "noteアカウント")
    resolver.register_rss_entries(feed.entries)
    items = []
    for entry in feed.entries[: int(source.get("max_items", 20))]:
        link = str(entry.get("link") or "").strip()
        note_key = parse_note_key(link)
        stable_id = note_key or hashlib.sha256(link.encode("utf-8")).hexdigest()[:20]
        summary_html = entry.get("summary") or entry.get("description") or ""
        items.append({
            "id": stable_id,
            "title": strip_html(entry.get("title"), 300),
            "url": link,
            "published_at": _iso_date(entry.get("published") or entry.get("updated")),
            "summary": strip_html(summary_html, 500),
            "thumbnail_url": resolver.resolve(stable_id, link, None, session),
            "author": strip_html(entry.get("author"), 120),
            "source_id": source["source_id"],
            "source_type": "note_account",
        })
    items = dedupe_keep_order(items)
    if not items:
        raise RuntimeError("note RSSから記事を取得できませんでした")
    if owns_resolver:
        resolver.save()
    return {
        "schema_version": "1.0",
        "source": {
            "id": source["source_id"],
            "type": "note_account",
            "title": source.get("title", source.get("account_id", "note")),
            "url": source["url"],
            "rss_url": rss_url,
        },
        "items": items,
    }


def _walk_for_note_dicts(node: Any, found: list[dict], seen: set[str]) -> None:
    if isinstance(node, dict):
        key = node.get("key") or node.get("note_key")
        title = node.get("name") or node.get("title")
        if isinstance(key, str) and key.startswith("n") and title and key not in seen:
            seen.add(key)
            found.append(node)
        for value in node.values():
            _walk_for_note_dicts(value, found, seen)
    elif isinstance(node, list):
        for value in node:
            _walk_for_note_dicts(value, found, seen)


def _extract_note_dicts_from_layout(session, key: str, timeout: int, max_items: int) -> list[dict]:
    endpoints = [
        f"https://note.com/api/v1/layout/magazine/{key}/section",
        f"https://note.com/api/v1/magazines/{key}",
    ]
    for endpoint in endpoints:
        try:
            response = get_or_raise(session, endpoint, timeout, params={"page": 1})
            data = response.json()
            found: list[dict] = []
            _walk_for_note_dicts(data, found, set())
            if found:
                return found[:max_items]
        except Exception:
            continue
    return []


def _extract_keys_from_html(session, url: str, timeout: int, max_items: int) -> list[str]:
    response = get_or_raise(session, url, timeout)
    soup = BeautifulSoup(response.text, "html.parser")
    keys: list[str] = []
    seen: set[str] = set()
    for anchor in soup.select('a[href*="/n/"]'):
        href = anchor.get("href") or ""
        absolute = urljoin(url, href)
        key = parse_note_key(absolute)
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
            if len(keys) >= max_items:
                break
    return keys


def _find_matching_note(node: Any, note_key: str) -> dict | None:
    if isinstance(node, dict):
        if node.get("key") == note_key:
            return node
        for value in node.values():
            result = _find_matching_note(value, note_key)
            if result:
                return result
    elif isinstance(node, list):
        for value in node:
            result = _find_matching_note(value, note_key)
            if result:
                return result
    return None


def _item_from_note_dict(note: dict, source: dict, position: int) -> dict:
    key = str(note.get("key") or note.get("note_key"))
    user = note.get("user") if isinstance(note.get("user"), dict) else {}
    source_account = urlparse(source.get("url", "")).path.strip("/").split("/")[0] or "club_pyramid"
    urlname = user.get("urlname") or source.get("account_id") or source_account
    url = note.get("note_url") or note.get("url") or f"https://note.com/{urlname}/n/{key}"
    image = (
        note.get("eyecatch_url")
        or note.get("eyecatchUrl")
        or note.get("image_url")
        or note.get("thumbnail_url")
    )
    description = note.get("description") or note.get("lead") or note.get("body") or ""
    return {
        "id": key,
        "title": strip_html(note.get("name") or note.get("title"), 300),
        "url": url,
        "published_at": _iso_date(note.get("publish_at") or note.get("published_at") or note.get("created_at")),
        "summary": strip_html(description, 500),
        "thumbnail_url": normalize_note_thumbnail_url(image),
        "author": strip_html(user.get("nickname") or note.get("author"), 120),
        "magazine_position": position,
        "source_id": source["source_id"],
        "source_type": "note_magazine",
    }


def _fetch_note_detail(session, note_key: str, source: dict, position: int, timeout: int) -> dict:
    api_url = f"https://note.com/api/v3/notes/{note_key}"
    try:
        response = get_or_raise(session, api_url, timeout)
        data = response.json()
        note = _find_matching_note(data, note_key)
        if note:
            return _item_from_note_dict(note, source, position)
    except Exception:
        pass

    source_account = urlparse(source.get("url", "")).path.strip("/").split("/")[0] or "club_pyramid"
    article_url = f"https://note.com/{source_account}/n/{note_key}"
    response = get_or_raise(session, article_url, timeout)
    soup = BeautifulSoup(response.text, "html.parser")

    def meta(prop: str) -> str | None:
        node = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        return node.get("content") if node else None

    published = meta("article:published_time")
    canonical = soup.find("link", rel="canonical")
    page_image = _article_page_image_details(response.text)[0]
    return {
        "id": note_key,
        "title": strip_html(meta("og:title") or (soup.title.string if soup.title else note_key), 300),
        "url": canonical.get("href") if canonical else article_url,
        "published_at": _iso_date(published),
        "summary": strip_html(meta("og:description"), 500),
        "thumbnail_url": page_image,
        "author": "",
        "magazine_position": position,
        "source_id": source["source_id"],
        "source_type": "note_magazine",
    }


def _register_magazine_rss(session: Any, source: dict, timeout: int, resolver: NoteThumbnailResolver) -> None:
    rss_url = source.get("rss_url") or source["url"].rstrip("/") + "/rss"
    try:
        response = get_or_raise(session, rss_url, timeout)
        feed = _parse_feed(response.content, "noteマガジン")
        resolver.register_rss_entries(feed.entries)
    except Exception:
        # Magazine order extraction remains usable when RSS is temporarily unavailable.
        return


def fetch_magazine(source: dict, http_config: dict, resolver: NoteThumbnailResolver | None = None) -> dict:
    owns_resolver = resolver is None
    resolver = resolver or _own_resolver(http_config)
    session = make_session(http_config)
    timeout = int(http_config.get("timeout_seconds", 25))
    max_items = int(source.get("max_items", 20))
    key = source["magazine_key"]
    _register_magazine_rss(session, source, timeout, resolver)

    raw_notes = _extract_note_dicts_from_layout(session, key, timeout, max_items)
    items: list[dict] = []
    if raw_notes:
        for position, note in enumerate(raw_notes):
            item = _item_from_note_dict(note, source, position)
            if not item.get("title") or not item.get("url"):
                item = _fetch_note_detail(session, item["id"], source, position, timeout)
            item["thumbnail_url"] = resolver.resolve(
                item["id"], item["url"], item.get("thumbnail_url"), session
            )
            items.append(item)
    else:
        keys = _extract_keys_from_html(session, source["url"], timeout, max_items)
        for position, note_key in enumerate(keys):
            item = _fetch_note_detail(session, note_key, source, position, timeout)
            item["thumbnail_url"] = resolver.resolve(
                item["id"], item["url"], item.get("thumbnail_url"), session
            )
            items.append(item)

    items = dedupe_keep_order(items)[:max_items]
    if not items:
        raise RuntimeError("noteマガジンから記事を取得できませんでした")
    if owns_resolver:
        resolver.save()
    return {
        "schema_version": "1.0",
        "source": {
            "id": source["source_id"],
            "type": "note_magazine",
            "title": source.get("title", key),
            "url": source["url"],
            "magazine_key": key,
            "ordering": "magazine_display_order",
        },
        "items": items,
    }


def fetch_note(
    source: dict,
    http_config: dict,
    resolver: NoteThumbnailResolver | None = None,
) -> dict:
    if source.get("type") == "account":
        return fetch_account(source, http_config, resolver)
    if source.get("type") == "magazine":
        return fetch_magazine(source, http_config, resolver)
    raise ValueError(f"未対応のnote source type: {source.get('type')}")
