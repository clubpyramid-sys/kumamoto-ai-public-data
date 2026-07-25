from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from common import dedupe_keep_order, load_json, now_iso, strip_html


def _iso(value: str | None) -> str:
    if not value:
        return now_iso()
    text = str(value).strip()
    if text.endswith("Z"):
        return text
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except ValueError:
        return now_iso()


def _valid_x_url(value: str | None) -> bool:
    if not value:
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme == "https" and parsed.netloc.lower() in {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}


def _normalize_media(raw: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return result
    for item in raw:
        if isinstance(item, str):
            url = item.strip()
            kind = "image"
        elif isinstance(item, dict):
            url = str(item.get("url") or item.get("media_url") or "").strip()
            kind = str(item.get("type") or item.get("kind") or "image").strip().lower()
        else:
            continue
        if url.startswith("https://"):
            result.append({"type": kind or "image", "url": url})
    return result[:4]


def _normalize_item(raw: dict[str, Any], allowed: set[str]) -> dict[str, Any] | None:
    handle = str(raw.get("handle") or raw.get("account") or raw.get("username") or "").lstrip("@").strip()
    canonical = next((h for h in allowed if h.lower() == handle.lower()), None)
    if not canonical:
        return None

    post_id = str(raw.get("id") or raw.get("post_id") or raw.get("tweet_id") or "").strip()
    url = str(raw.get("url") or raw.get("post_url") or "").strip()
    if not post_id and _valid_x_url(url):
        post_id = url.rstrip("/").split("/")[-1]
    if not post_id:
        return None
    if not _valid_x_url(url):
        url = f"https://x.com/{canonical}/status/{post_id}"

    text = strip_html(str(raw.get("text") or raw.get("content") or ""), max_chars=1000)
    if not text:
        return None

    return {
        "id": post_id,
        "title": text[:80],
        "text": text,
        "url": url,
        "handle": canonical,
        "display_name": strip_html(str(raw.get("display_name") or raw.get("name") or canonical), max_chars=100),
        "published_at": _iso(str(raw.get("published_at") or raw.get("created_at") or raw.get("date") or "")),
        "is_reply": bool(raw.get("is_reply", False)),
        "is_repost": bool(raw.get("is_repost", raw.get("is_retweet", False))),
        "media": _normalize_media(raw.get("media") or raw.get("media_urls") or []),
    }


def import_hermes_x(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    input_path = root / str(config.get("input") or "runtime/x/hermes_latest.json")
    raw = load_json(input_path, {})
    records = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(records, list):
        raise RuntimeError(f"Hermes X入力が配列ではありません: {input_path}")

    allowed = {
        str(account.get("handle") or "").lstrip("@").strip()
        for account in config.get("accounts", [])
        if account.get("enabled", True) and account.get("handle")
    }
    if not allowed:
        raise RuntimeError("有効なXアカウント設定がありません")

    items: list[dict[str, Any]] = []
    for raw_item in records:
        if not isinstance(raw_item, dict):
            continue
        item = _normalize_item(raw_item, allowed)
        if not item:
            continue
        if config.get("exclude_replies", True) and item["is_reply"]:
            continue
        if config.get("exclude_reposts", True) and item["is_repost"]:
            continue
        items.append(item)

    items = dedupe_keep_order(sorted(items, key=lambda x: x["published_at"], reverse=True))
    per_account_limit = int(config.get("max_items_per_account", 20))
    counts: dict[str, int] = {}
    limited: list[dict[str, Any]] = []
    for item in items:
        handle = item["handle"]
        if counts.get(handle, 0) >= per_account_limit:
            continue
        counts[handle] = counts.get(handle, 0) + 1
        limited.append(item)
        if len(limited) >= int(config.get("max_items", 40)):
            break

    if not limited:
        raise RuntimeError("Hermes X入力から公開可能な投稿を1件も生成できませんでした")

    return {
        "schema_version": "1.0",
        "source": {
            "id": "x-hermes-grok",
            "type": "x-hermes",
            "title": "COSA NOSTRA JAPAN X posts",
            "url": "https://x.com/club_kumamoto",
        },
        "collection_method": "Hermes Agent with Grok",
        "last_source_update_at": str(raw.get("generated_at") or raw.get("updated_at") or now_iso()) if isinstance(raw, dict) else now_iso(),
        "items": limited,
    }
