from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from common import dedupe_keep_order, first_image_from_html, parse_note_key, strip_html
from http_client import get_or_raise, make_session


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


def _feed_entry_image(entry: Any) -> str | None:
    for attr in ("media_content", "media_thumbnail"):
        nodes = getattr(entry, attr, None) or entry.get(attr, [])
        for node in nodes:
            if isinstance(node, dict) and node.get("url"):
                return str(node["url"])
    for attr in ("content",):
        nodes = getattr(entry, attr, None) or entry.get(attr, [])
        for node in nodes:
            if isinstance(node, dict):
                image = first_image_from_html(node.get("value"))
                if image:
                    return image
    return first_image_from_html(entry.get("summary"))


def fetch_account(source: dict, http_config: dict) -> dict:
    session = make_session(http_config)
    timeout = int(http_config.get("timeout_seconds", 25))
    rss_url = source.get("rss_url") or source["url"].rstrip("/") + "/rss"
    response = get_or_raise(session, rss_url, timeout)
    feed = feedparser.parse(response.content)
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"note RSS解析失敗: {feed.bozo_exception}")
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
            "thumbnail_url": _feed_entry_image(entry),
            "author": strip_html(entry.get("author"), 120),
            "source_id": source["source_id"],
            "source_type": "note_account",
        })
    items = dedupe_keep_order(items)
    if not items:
        raise RuntimeError("note RSSから記事を取得できませんでした")
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
        "thumbnail_url": image,
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
    return {
        "id": note_key,
        "title": strip_html(meta("og:title") or (soup.title.string if soup.title else note_key), 300),
        "url": canonical.get("href") if canonical else article_url,
        "published_at": _iso_date(published),
        "summary": strip_html(meta("og:description"), 500),
        "thumbnail_url": meta("og:image"),
        "author": "",
        "magazine_position": position,
        "source_id": source["source_id"],
        "source_type": "note_magazine",
    }


def fetch_magazine(source: dict, http_config: dict) -> dict:
    session = make_session(http_config)
    timeout = int(http_config.get("timeout_seconds", 25))
    max_items = int(source.get("max_items", 20))
    key = source["magazine_key"]

    raw_notes = _extract_note_dicts_from_layout(session, key, timeout, max_items)
    items: list[dict] = []
    if raw_notes:
        for position, note in enumerate(raw_notes):
            item = _item_from_note_dict(note, source, position)
            if not item.get("title") or not item.get("url"):
                item = _fetch_note_detail(session, item["id"], source, position, timeout)
            items.append(item)
    else:
        keys = _extract_keys_from_html(session, source["url"], timeout, max_items)
        for position, note_key in enumerate(keys):
            items.append(_fetch_note_detail(session, note_key, source, position, timeout))

    items = dedupe_keep_order(items)[:max_items]
    if not items:
        raise RuntimeError("noteマガジンから記事を取得できませんでした")
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


def fetch_note(source: dict, http_config: dict) -> dict:
    if source.get("type") == "account":
        return fetch_account(source, http_config)
    if source.get("type") == "magazine":
        return fetch_magazine(source, http_config)
    raise ValueError(f"未対応のnote source type: {source.get('type')}")
