from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from common import load_json, valid_public_url

FORBIDDEN_PUBLIC_PATTERNS = [
    re.compile(r"/Users/", re.I),
    re.compile(r"/Volumes/", re.I),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"),
]


def validate_item(item: dict, kind: str) -> list[str]:
    errors: list[str] = []
    prefix = f"{kind}:{item.get('id', '?')}"
    if not item.get("id"):
        errors.append(f"{prefix} idがありません")
    if not str(item.get("title") or "").strip():
        errors.append(f"{prefix} titleがありません")
    if not valid_public_url(item.get("url")):
        errors.append(f"{prefix} URLが不正です: {item.get('url')}")
    thumbnail = item.get("thumbnail_url")
    if thumbnail and not valid_public_url(thumbnail):
        errors.append(f"{prefix} thumbnail_urlが不正です")
    if kind == "youtube" and item.get("duration_seconds") is not None:
        try:
            if int(item["duration_seconds"]) < 0:
                errors.append(f"{prefix} duration_secondsが負数です")
        except Exception:
            errors.append(f"{prefix} duration_secondsが整数ではありません")
    return errors


def validate_source_payload(payload: dict) -> list[str]:
    errors: list[str] = []
    source = payload.get("source") or {}
    if payload.get("schema_version") != "1.0":
        errors.append("schema_versionが1.0ではありません")
    if not source.get("id") or not source.get("type"):
        errors.append("source.id/typeがありません")
    items = payload.get("items")
    if not isinstance(items, list):
        return errors + ["itemsが配列ではありません"]
    if payload.get("item_count") is not None and payload.get("item_count") != len(items):
        errors.append("item_countが実件数と一致しません")
    ids = [str(item.get("id")) for item in items if item.get("id")]
    if len(ids) != len(set(ids)):
        errors.append("重複IDがあります")
    kind = "youtube" if str(source.get("type", "")).startswith("youtube") else "note"
    for item in items:
        errors.extend(validate_item(item, kind))
    return errors


def validate_site_payload(payload: dict) -> list[str]:
    errors: list[str] = []
    if not payload.get("site", {}).get("id"):
        errors.append("site.idがありません")
    for item in payload.get("note_items", []):
        errors.extend(validate_item(item, "note"))
    for item in payload.get("youtube_items", []):
        errors.extend(validate_item(item, "youtube"))
    return errors


def suspicious_drop(existing: dict | None, candidate: dict, safety: dict) -> str | None:
    existing = existing or {}
    old_count = len(existing.get("items", []))
    new_count = len(candidate.get("items", []))
    minimum = int(safety.get("minimum_items", 1))
    max_drop = float(safety.get("maximum_drop_ratio", 0.60))
    if new_count < minimum:
        return f"取得件数が最低件数未満です: {new_count} < {minimum}"
    if old_count >= 5 and new_count < old_count:
        ratio = (old_count - new_count) / old_count
        if ratio > max_drop:
            return f"件数が急減しました: {old_count} -> {new_count} ({ratio:.0%})"
    return None


def validate_public_tree(docs_root: Path) -> list[str]:
    errors: list[str] = []
    for path in sorted(docs_root.rglob("*.json")):
        try:
            data = load_json(path)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}: JSON構文エラー: {exc}")
            continue
        if path.parts[-2] == "sites":
            errors.extend(f"{path}: {e}" for e in validate_site_payload(data))
        elif isinstance(data, dict) and "items" in data:
            errors.extend(f"{path}: {e}" for e in validate_source_payload(data))
        raw = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_PUBLIC_PATTERNS:
            if pattern.search(raw):
                errors.append(f"{path}: 公開禁止情報らしき文字列を検出: {pattern.pattern}")
    return errors
