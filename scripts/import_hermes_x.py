from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from common import load_json, now_iso, strip_html


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


def _normalization_failure_reason(raw: Any, allowed: set[str]) -> str | None:
    """Return a safe, record-level rejection code without persisting post text."""
    if not isinstance(raw, dict):
        return "invalid_record"

    handle = str(raw.get("handle") or raw.get("account") or raw.get("username") or "").lstrip("@").strip()
    canonical = next((h for h in allowed if h.lower() == handle.lower()), None)
    if not canonical:
        return "account_mismatch"

    post_id = str(raw.get("id") or raw.get("post_id") or raw.get("tweet_id") or "").strip()
    if not post_id.isdigit():
        return "invalid_status_id"

    url = str(raw.get("url") or raw.get("post_url") or "").strip()
    if url and (not _valid_x_url(url) or f"/status/{post_id}" not in urlparse(url).path):
        return "invalid_status_url"

    if not strip_html(str(raw.get("text") or raw.get("content") or ""), max_chars=1000):
        return "empty_text"

    value = str(raw.get("published_at") or raw.get("created_at") or raw.get("date") or "").strip()
    if not value:
        return "timestamp_parse_failed"
    try:
        datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return "timestamp_parse_failed"

    if bool(raw.get("is_reply", False)):
        return "reply"
    if bool(raw.get("is_repost", raw.get("is_retweet", False))):
        return "repost"
    return None


def normalize_hermes_records(
    records: Any,
    allowed: set[str],
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Normalize cached Hermes records and retain only safe rejection metadata.

    This is deliberately side-effect free so a saved input can be replayed
    without invoking Hermes, oEmbed, or any other network source.
    """
    if not isinstance(records, list):
        raise RuntimeError("Hermes X入力が配列ではありません")

    items: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw_item in records:
        reason = _normalization_failure_reason(raw_item, allowed)
        raw_id = str(raw_item.get("id") or raw_item.get("post_id") or "") if isinstance(raw_item, dict) else ""
        raw_handle = str(raw_item.get("handle") or raw_item.get("account") or "") if isinstance(raw_item, dict) else ""
        if reason:
            rejected.append({"id": raw_id, "handle": raw_handle.lstrip("@"), "reason": reason})
            continue
        item = _normalize_item(raw_item, allowed)
        if not item:
            rejected.append({"id": raw_id, "handle": raw_handle.lstrip("@"), "reason": "normalization_failed"})
            continue
        key = (item["handle"].lower(), item["id"])
        if key in seen:
            rejected.append({"id": item["id"], "handle": item["handle"], "reason": "duplicate"})
            continue
        seen.add(key)
        items.append(item)

    items.sort(key=lambda item: item["published_at"], reverse=True)
    return items, rejected


def merge_with_last_known_good(
    fresh_items: list[dict[str, Any]],
    previous_items: list[dict[str, Any]],
    allowed: set[str],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Merge records per post, then apply limits per account.

    A partial cached input must not replace a whole account's public history.
    Newer last-known-good records and newly imported records coexist by status
    ID, with the latest timestamps winning the configured account limit.
    """
    previous, _ = normalize_hermes_records(previous_items, allowed, config)
    # Existing public records win for an identical status ID.  A saved input
    # can contain a less complete historical rendering of the same post (for
    # example, stripped short-link text), and must not degrade last-known-good.
    combined = [*previous, *fresh_items]
    combined.sort(key=lambda item: item["published_at"], reverse=True)

    seen: set[tuple[str, str]] = set()
    counts: Counter[str] = Counter()
    result: list[dict[str, Any]] = []
    per_account_limit = int(config.get("max_items_per_account", 20))
    total_limit = int(config.get("max_items", per_account_limit * len(allowed)))
    for item in combined:
        key = (item["handle"].lower(), item["id"])
        if key in seen:
            continue
        seen.add(key)
        if counts[item["handle"]] >= per_account_limit:
            continue
        counts[item["handle"]] += 1
        result.append(item)
        if len(result) >= total_limit:
            break
    return result


def import_hermes_x(
    root: Path,
    config: dict[str, Any],
    previous_items: list[dict[str, Any]] | None = None,
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
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

    normalized, rejected = normalize_hermes_records(records, allowed, config)
    limited = merge_with_last_known_good(
        normalized,
        previous_items or [],
        allowed,
        config,
    )

    if audit is not None:
        previous_keys = {
            (str(item.get("handle") or "").lower(), str(item.get("id") or ""))
            for item in (previous_items or [])
            if isinstance(item, dict)
        }
        fresh_keys = {(item["handle"].lower(), item["id"]) for item in normalized}
        audit.update({
            "raw_count": len(records),
            "parsed_count": sum(1 for item in records if isinstance(item, dict)),
            "normalized_count": len(normalized),
            "deduped_count": len(normalized),
            "rejected": rejected,
            "adopted_count": sum(
                1 for item in limited if (item["handle"].lower(), item["id"]) in fresh_keys
            ),
            "retained_previous_count": sum(
                1 for item in limited if (item["handle"].lower(), item["id"]) not in fresh_keys
            ),
            "previous_input_count": len(previous_items or []),
            "previous_overlap_count": len(fresh_keys & previous_keys),
        })

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
