from __future__ import annotations

"""Write safe, per-account X pipeline counts after a completed local run.

Only aggregate counts and timestamps are retained.  Hermes response text,
credentials, URLs outside the already-public source JSON, and absolute paths
are intentionally excluded.
"""

import argparse
from collections import Counter
from pathlib import Path
from typing import Any

from common import atomic_write_json, load_json
from fetch_x_with_hermes import now_jst_iso


def _items(payload: Any) -> list[dict[str, Any]]:
    return [item for item in (payload or {}).get("items", []) if isinstance(item, dict)] if isinstance(payload, dict) else []


def _counts(items: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str(item.get("handle") or "") for item in items if item.get("handle"))


def build_audit(
    config: dict[str, Any],
    fetch_status: dict[str, Any],
    raw_counts: dict[str, Any],
    cached: dict[str, Any],
    published: dict[str, Any],
) -> dict[str, Any]:
    accounts = [
        str(item.get("handle") or "").lstrip("@").strip()
        for item in config.get("accounts", [])
        if isinstance(item, dict) and item.get("enabled", True) and item.get("handle")
    ]
    fresh = dict(fetch_status.get("per_account_results") or {})
    fresh_counts = Counter(dict(fetch_status.get("fresh_per_account") or {}))
    cached_counts = _counts(_items(cached))
    published_counts = _counts(_items(published))
    raw_by_account = dict(raw_counts.get("per_account_raw_response_count") or {})
    missing = set(fetch_status.get("missing_accounts") or [])
    retained = set(fetch_status.get("retained_accounts") or [])
    per_account: dict[str, dict[str, Any]] = {}
    for handle in accounts:
        item_status = fresh.get(handle) if isinstance(fresh.get(handle), dict) else {}
        normalize_count = int(item_status.get("fresh_count", fresh_counts.get(handle, 0)) or 0)
        public_count = int(published_counts.get(handle, 0))
        retained_count = max(0, public_count - normalize_count) if handle in retained else 0
        state = str(item_status.get("state") or (
            "retained_last_known_good" if handle in retained else "updated" if normalize_count else "unavailable"
        ))
        per_account[handle] = {
            "request_count": 1,
            "raw_response_count": int(raw_by_account.get(handle, 0)),
            "normalize_success_count": normalize_count,
            "dedupe_after_count": normalize_count,
            "adopted_count": normalize_count,
            "reject_count": max(0, int(raw_by_account.get(handle, 0)) - normalize_count),
            "retained_previous_count": retained_count,
            "cached_count": int(cached_counts.get(handle, 0)),
            "published_count": public_count,
            "state": state,
        }
    return {
        "schema_version": "1.0",
        "generated_at": now_jst_iso(),
        "fetch_status": str(fetch_status.get("status") or "unknown"),
        "raw_response_item_count": int(raw_counts.get("raw_response_item_count", 0) or 0),
        "unclassified_raw_response_count": int(raw_by_account.get("_unclassified", 0) or 0),
        "per_account": per_account,
        "notes": [
            "raw_response_count is aggregated before oEmbed enrichment; provider response text is not retained.",
            "normalize_success_count is the safe post-normalisation count used by the feed.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--fetch-status", required=True)
    parser.add_argument("--raw-counts", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--public", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    config = load_json(Path(args.config), {})
    audit = build_audit(
        config,
        load_json(Path(args.fetch_status), {}),
        load_json(Path(args.raw_counts), {}),
        load_json(Path(args.input), {}),
        load_json(Path(args.public), {}),
    )
    atomic_write_json(Path(args.output), audit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
