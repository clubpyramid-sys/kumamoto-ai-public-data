from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Mapping

import fetch_x_with_hermes
import run_fetch_x_with_hermes

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "x_sources_daily.json"
INPUT_PATH = ROOT / "runtime" / "x" / "hermes_daily_latest.json"
STATUS_PATH = ROOT / "runtime" / "x" / "hermes_daily_fetch_status.json"


def configure_daily_pipeline() -> None:
    """Point the proven Hermes/X pipeline at the independent daily group."""

    fetch_x_with_hermes.CONFIG_PATH = CONFIG_PATH
    fetch_x_with_hermes.INPUT_PATH = INPUT_PATH
    fetch_x_with_hermes.STATUS_PATH = STATUS_PATH

    run_fetch_x_with_hermes._DISCOVERY_PASS_PENDING = True
    fetch_x_with_hermes.extract_json = run_fetch_x_with_hermes.extract_verified_x_search_payload
    fetch_x_with_hermes.run_hermes = run_fetch_x_with_hermes.run_hermes_with_saved_config
    fetch_x_with_hermes.build_prompt = run_fetch_x_with_hermes.build_x_search_discovery_prompt
    fetch_x_with_hermes.normalize_items = (
        run_fetch_x_with_hermes.normalize_discovery_items_with_oembed
    )


def validate_account_coverage(
    accounts: list[str],
    fresh_counts: Mapping[str, int],
    minimum_accounts_with_items: int,
) -> list[str]:
    """Allow dormant accounts while still rejecting a broadly failed search."""

    required = max(1, min(int(minimum_accounts_with_items), len(accounts)))
    present = [handle for handle in accounts if int(fresh_counts.get(handle, 0)) > 0]
    missing = [handle for handle in accounts if handle not in present]

    if len(present) < required:
        raise RuntimeError(
            "取得できたアカウント数が最低数未満です: "
            f"{len(present)} < {required}; 未取得: "
            + ", ".join(f"@{handle}" for handle in missing)
        )
    return missing


def main() -> int:
    configure_daily_pipeline()

    config = fetch_x_with_hermes.load_json(CONFIG_PATH, {})
    accounts = [
        str(account.get("handle") or "").strip().lstrip("@")
        for account in config.get("accounts", [])
        if account.get("enabled", True) and account.get("handle")
    ]
    if not accounts:
        raise RuntimeError("有効なXアカウント設定がありません。")

    allowed = {handle.lower(): handle for handle in accounts}
    per_account_limit = int(config.get("max_items_per_account", 10))
    total_limit = int(config.get("max_items", per_account_limit * len(accounts)))
    minimum_accounts = int(config.get("minimum_accounts_with_items", len(accounts)))

    previous_payload = fetch_x_with_hermes.load_json(INPUT_PATH, {})
    previous_items = (
        previous_payload.get("items", []) if isinstance(previous_payload, dict) else []
    )

    raw_output = fetch_x_with_hermes.run_hermes(
        fetch_x_with_hermes.build_prompt(accounts, per_account_limit)
    )
    response = fetch_x_with_hermes.extract_json(raw_output)
    if not isinstance(response, dict):
        raise RuntimeError("Hermes出力のルートがJSONオブジェクトではありません。")

    fresh_items = fetch_x_with_hermes.normalize_items(response.get("items"), allowed)
    fresh_counts = Counter(item["handle"] for item in fresh_items)
    missing = validate_account_coverage(accounts, fresh_counts, minimum_accounts)

    merged = fetch_x_with_hermes.merge_items(
        fresh_items,
        previous_items,
        allowed,
        per_account_limit,
        total_limit,
    )
    previous_normalized = fetch_x_with_hermes.merge_items(
        [],
        previous_items,
        allowed,
        per_account_limit,
        total_limit,
    )
    changed = merged != previous_normalized

    if changed:
        fetch_x_with_hermes.atomic_write_json(
            INPUT_PATH,
            {
                "schema_version": "1.0",
                "generated_at": fetch_x_with_hermes.now_jst_iso(),
                "collection_method": "Hermes Agent with Grok",
                "items": merged,
            },
        )

    merged_counts = Counter(item["handle"] for item in merged)
    per_account = {handle: merged_counts.get(handle, 0) for handle in accounts}
    fetch_x_with_hermes.write_status(
        "success",
        changed=changed,
        fresh_item_count=len(fresh_items),
        merged_item_count=len(merged),
        minimum_accounts_with_items=minimum_accounts,
        missing_accounts=missing,
        per_account=per_account,
        newest_post=merged[0] if merged else None,
    )

    print("=== Hermes X日次取得結果 ===")
    print(f"新規取得候補: {len(fresh_items)}件")
    print(f"統合後: {len(merged)}件")
    print(f"入力JSON更新: {'yes' if changed else 'no'}")
    for handle in accounts:
        print(f"- @{handle}: {per_account[handle]}件")
    if missing:
        print("今回0件（次回も継続確認）: " + ", ".join(f"@{h}" for h in missing))
    return 0


if __name__ == "__main__":
    configure_daily_pipeline()
    try:
        raise SystemExit(main())
    except Exception as exc:
        fetch_x_with_hermes.write_status("failed", error=str(exc))
        print(f"X日次取得失敗: {exc}", file=sys.stderr)
        raise SystemExit(1)
