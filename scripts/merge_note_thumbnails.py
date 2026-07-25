from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse

from common import parse_note_key
from fetch_note import normalize_note_thumbnail_url


def normalize_note_article_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or parsed.hostname != "note.com":
        return None
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(("https", "note.com", path, "", "", ""))


def _article_keys(item: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    item_id = str(item.get("id") or "").strip()
    url = normalize_note_article_url(item.get("url"))
    url_note_id = parse_note_key(url or "")
    for key in (item_id, url_note_id):
        if key and f"id:{key}" not in keys:
            keys.append(f"id:{key}")
    if url:
        keys.append(f"url:{url}")
    return keys


def build_account_article_index(account_payloads: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index account articles by stable ID and canonical URL without changing them."""
    index: dict[str, dict[str, Any]] = {}
    for payload in account_payloads:
        if not isinstance(payload, dict):
            continue
        for item in payload.get("items", []):
            if not isinstance(item, dict):
                continue
            thumbnail = normalize_note_thumbnail_url(item.get("thumbnail_url"))
            if not thumbnail:
                continue
            indexed = dict(item)
            indexed["thumbnail_url"] = thumbnail
            for key in _article_keys(item):
                index.setdefault(key, indexed)
    return index


def backfill_magazine_thumbnails(
    magazine_payload: dict[str, Any],
    account_index: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """Fill only missing magazine thumbnails while preserving order and article metadata."""
    result = deepcopy(magazine_payload)
    filled_ids: list[str] = []
    for item in result.get("items", []):
        if not isinstance(item, dict) or normalize_note_thumbnail_url(item.get("thumbnail_url")):
            continue
        account_item = next((account_index[key] for key in _article_keys(item) if key in account_index), None)
        if not account_item:
            continue
        thumbnail = normalize_note_thumbnail_url(account_item.get("thumbnail_url"))
        if not thumbnail:
            continue
        item["thumbnail_url"] = thumbnail
        filled_ids.append(str(item.get("id") or normalize_note_article_url(item.get("url")) or ""))
    return result, filled_ids
