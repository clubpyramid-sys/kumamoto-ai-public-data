from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from common import dedupe_keep_order, load_json


def _all_source_payloads(staging_docs: Path, category: str) -> list[dict]:
    base = staging_docs / category
    if not base.exists():
        return []
    payloads = []
    for path in sorted(base.rglob("*.json")):
        data = load_json(path, {})
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            payloads.append(data)
    return payloads


def _text(item: dict) -> str:
    return " ".join([
        str(item.get("title") or ""),
        str(item.get("summary") or ""),
        str(item.get("description") or ""),
    ]).lower()


def _filter_items(
    payloads: list[dict],
    source_ids: list[str],
    keywords: list[str],
    excludes: list[str],
    excluded_ids: list[str],
) -> list[dict]:
    source_set = set(source_ids)
    source_rank = {source_id: index for index, source_id in enumerate(source_ids)}
    if source_ids:
        payloads = sorted(payloads, key=lambda payload: source_rank.get(payload.get("source", {}).get("id"), len(source_rank)))
    excluded_set = set(excluded_ids)
    lowered_keywords = [k.lower() for k in keywords if k]
    lowered_excludes = [k.lower() for k in excludes if k]
    result: list[dict] = []
    for payload in payloads:
        sid = payload.get("source", {}).get("id")
        if source_set and sid not in source_set:
            continue
        for original in payload.get("items", []):
            item = deepcopy(original)
            if item.get("id") in excluded_set:
                continue
            text = _text(item)
            if lowered_keywords and not any(k in text for k in lowered_keywords):
                continue
            if lowered_excludes and any(k in text for k in lowered_excludes):
                continue
            item["source_id"] = item.get("source_id") or sid
            item["selection_mode"] = item.get("selection_mode") or "automatic"
            result.append(item)
    return dedupe_keep_order(result)


def _pin_and_limit(items: list[dict], pinned_ids: list[str], manual_items: list[dict], limit: int) -> list[dict]:
    mapping = {str(i.get("id")): i for i in items if i.get("id")}
    result: list[dict] = []
    for item in manual_items:
        copy = deepcopy(item)
        copy["selection_mode"] = "manual"
        result.append(copy)
    for item_id in pinned_ids:
        if item_id in mapping:
            pinned = deepcopy(mapping[item_id])
            pinned["selection_mode"] = "pinned"
            result.append(pinned)
    result.extend(items)
    return dedupe_keep_order(result)[:limit]


def build_site_payloads(staging_docs: Path, filters: dict, manual: dict) -> dict[str, dict]:
    note_payloads = _all_source_payloads(staging_docs, "note")
    youtube_payloads = _all_source_payloads(staging_docs, "youtube")
    outputs: dict[str, dict] = {}
    for site_id, site in filters.get("sites", {}).items():
        selections = manual.get("sites", {}).get(site_id, {})
        note_items = _filter_items(
            note_payloads,
            site.get("note_source_ids", []),
            site.get("note_keywords", []),
            site.get("exclude_keywords", []),
            selections.get("excluded_note_ids", []),
        )
        youtube_items = _filter_items(
            youtube_payloads,
            site.get("youtube_source_ids", []),
            site.get("youtube_keywords", []),
            site.get("exclude_keywords", []),
            selections.get("excluded_youtube_ids", []),
        )
        note_items = _pin_and_limit(
            note_items,
            selections.get("pinned_note_ids", []),
            selections.get("manual_note_items", []),
            int(site.get("note_limit", 10)),
        )
        youtube_items = _pin_and_limit(
            youtube_items,
            selections.get("pinned_youtube_ids", []),
            selections.get("manual_youtube_items", []),
            int(site.get("youtube_limit", 10)),
        )
        outputs[site_id] = {
            "schema_version": "1.0",
            "site": {"id": site_id, "title": site.get("title", site_id)},
            "note_items": note_items,
            "youtube_items": youtube_items,
        }
    return outputs
