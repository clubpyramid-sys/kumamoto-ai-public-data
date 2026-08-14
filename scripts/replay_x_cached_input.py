from __future__ import annotations

"""Replay an already-saved Hermes X input without contacting any provider."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from common import atomic_write_json, load_json
from import_hermes_x import import_hermes_x
from validate import validate_source_payload

ROOT = Path(__file__).resolve().parents[1]


def _accounts(config: dict[str, Any]) -> list[str]:
    return [
        str(row.get("handle") or "").strip().lstrip("@")
        for row in config.get("accounts", [])
        if isinstance(row, dict) and row.get("enabled", True) and row.get("handle")
    ]


def _count_by_handle(items: list[dict[str, Any]], handle: str) -> int:
    return sum(1 for item in items if str(item.get("handle") or "").lower() == handle.lower())


def main() -> int:
    parser = argparse.ArgumentParser(description="保存済みHermes入力を再処理します（ネットワーク不使用）")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--previous", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    args = parser.parse_args()

    config = load_json(ROOT / "config" / "x_sources.json", {})
    raw = load_json(args.input, {})
    raw_items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(raw_items, list):
        raise RuntimeError("入力Hermes JSONのitemsが配列ではありません")
    previous = load_json(args.previous, {})
    previous_items = previous.get("items", []) if isinstance(previous, dict) else []
    if not isinstance(previous_items, list):
        raise RuntimeError("前回公開JSONのitemsが配列ではありません")

    # Use a temporary, local config only; no input or tracked public file is mutated.
    replay_config = dict(config)
    replay_config["input"] = str(args.input)
    audit: dict[str, Any] = {}
    payload = import_hermes_x(ROOT, replay_config, previous_items=previous_items, audit=audit)
    payload["source"] = dict(config.get("source") or payload.get("source") or {})
    errors = validate_source_payload(payload)
    if errors:
        raise RuntimeError(" / ".join(errors))

    raw_counts = Counter(
        str(item.get("handle") or item.get("account") or "").lstrip("@").lower()
        for item in raw_items if isinstance(item, dict)
    )
    parsed_counts = Counter(
        str(item.get("handle") or item.get("account") or "").lstrip("@").lower()
        for item in raw_items if isinstance(item, dict)
    )
    rejected = audit.get("rejected", [])
    rejected_ids = {
        (str(row.get("handle") or "").lower(), str(row.get("id") or ""))
        for row in rejected if isinstance(row, dict)
    }
    fresh_keys = {
        (str(item.get("handle") or item.get("account") or "").lstrip("@").lower(), str(item.get("id") or ""))
        for item in raw_items if isinstance(item, dict)
        if (str(item.get("handle") or item.get("account") or "").lstrip("@").lower(), str(item.get("id") or "")) not in rejected_ids
    }
    normalized_counts = Counter(
        handle for handle, post_id in fresh_keys if handle and post_id
    )
    output_keys = {
        (str(item.get("handle") or "").lower(), str(item.get("id") or ""))
        for item in payload["items"]
    }
    result = {
        "schema_version": "1.0",
        "network_used": False,
        "input_item_count": len(raw_items),
        "output_item_count": len(payload["items"]),
        "accounts": {
            handle: {
                "raw_count": raw_counts[handle.lower()],
                "parsed_count": parsed_counts[handle.lower()],
                "normalized_count": normalized_counts[handle.lower()],
                "deduped_count": normalized_counts[handle.lower()],
                "adopted_input_count": sum(
                    1 for key in output_keys if key[0] == handle.lower() and key in fresh_keys
                ),
                "retained_previous_count": sum(
                    1 for key in output_keys if key[0] == handle.lower() and key not in fresh_keys
                ),
                "published_count": _count_by_handle(payload["items"], handle),
                "latest_post_id": next((item["id"] for item in payload["items"] if item["handle"].lower() == handle.lower()), None),
                "latest_post_at": next((item["published_at"] for item in payload["items"] if item["handle"].lower() == handle.lower()), None),
            }
            for handle in _accounts(config)
        },
        "normalization": audit,
    }
    atomic_write_json(args.output, payload)
    atomic_write_json(args.audit, result)
    print(json.dumps({"input": len(raw_items), "output": len(payload["items"]), "network_used": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"replay failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
