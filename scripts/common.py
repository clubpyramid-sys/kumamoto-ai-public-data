from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from bs4 import BeautifulSoup

JST = timezone.utc  # JSONはタイムゾーン付きISO文字列を維持。実行時刻はUTCで統一。
META_KEYS = {
    "generated_at",
    "last_success_at",
    "last_run_at",
    "content_hash",
    "item_count",
    "note_count",
    "youtube_count",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def strip_html(value: str | None, max_chars: int = 500) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    text = html.unescape(" ".join(soup.stripped_strings))
    text = re.sub(r"/Users/[^\s<>()\[\]{}\"\']+", "[local path removed]", text)
    text = re.sub(r"/Volumes/[^\s<>()\[\]{}\"\']+", "[local volume path removed]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def first_image_from_html(value: str | None) -> str | None:
    if not value:
        return None
    soup = BeautifulSoup(value, "html.parser")
    img = soup.find("img")
    if not img:
        return None
    return img.get("src") or img.get("data-src")


def valid_public_url(value: str | None, allowed_schemes: tuple[str, ...] = ("https",)) -> bool:
    if not value or not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in allowed_schemes and bool(parsed.netloc)


def dedupe_keep_order(items: Iterable[dict[str, Any]], key: str = "id") -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        value = str(item.get(key) or "")
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(item)
    return result


def without_meta(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: without_meta(v) for k, v in value.items() if k not in META_KEYS}
    if isinstance(value, list):
        return [without_meta(v) for v in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(without_meta(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def prepare_payload(candidate: dict[str, Any], existing: dict[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
    existing = existing or {}
    changed = canonical_json(candidate) != canonical_json(existing)
    result = dict(candidate)
    if "items" in result:
        result["item_count"] = len(result.get("items", []))
    if "note_items" in result:
        result["note_count"] = len(result.get("note_items", []))
    if "youtube_items" in result:
        result["youtube_count"] = len(result.get("youtube_items", []))
    result["content_hash"] = content_hash(result)
    if changed:
        result["generated_at"] = now_iso()
    else:
        result["generated_at"] = existing.get("generated_at") or now_iso()
        # 同一内容なら既存のハッシュと件数表現も安定させる。
        result["content_hash"] = existing.get("content_hash") or result["content_hash"]
    return result, changed


def copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=False) + "\n")


def parse_note_key(url: str) -> str | None:
    m = re.search(r"/n/(n[0-9a-zA-Z]+)", url)
    return m.group(1) if m else None


def best_thumbnail(thumbnails: dict[str, Any] | None) -> str | None:
    if not thumbnails:
        return None
    order = ("maxres", "standard", "high", "medium", "default")
    for name in order:
        node = thumbnails.get(name)
        if isinstance(node, dict) and node.get("url"):
            return str(node["url"])
    for node in thumbnails.values():
        if isinstance(node, dict) and node.get("url"):
            return str(node["url"])
    return None


def safe_relative(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))
