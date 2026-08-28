from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import fetch_x_with_hermes
import run_fetch_x_with_hermes

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "x_sources_daily.json"
INPUT_PATH = ROOT / "runtime" / "x" / "hermes_daily_latest.json"
STATUS_PATH = ROOT / "runtime" / "x" / "hermes_daily_fetch_status.json"
RAW_COUNTS_PATH = ROOT / "runtime" / "x" / "hermes_daily_raw_counts.json"
RAW_ITEMS_PATH = ROOT / "runtime" / "x" / "hermes_daily_raw_latest.json"


def configure_daily_pipeline() -> None:
    """Point the proven Hermes/X pipeline at the independent daily group."""

    fetch_x_with_hermes.CONFIG_PATH = CONFIG_PATH
    fetch_x_with_hermes.INPUT_PATH = INPUT_PATH
    fetch_x_with_hermes.STATUS_PATH = STATUS_PATH
    fetch_x_with_hermes.RAW_COUNTS_PATH = RAW_COUNTS_PATH
    fetch_x_with_hermes.RAW_ITEMS_PATH = RAW_ITEMS_PATH

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


def fetch_accounts(
    handles: list[str],
    per_account_limit: int,
) -> tuple[list[dict[str, Any]], Counter[str], list[dict[str, Any]]]:
    """Fetch one group and reset the one-time oEmbed discovery pass."""

    allowed = {handle.lower(): handle for handle in handles}
    run_fetch_x_with_hermes._DISCOVERY_PASS_PENDING = True
    raw_output = fetch_x_with_hermes.run_hermes(
        fetch_x_with_hermes.build_prompt(handles, per_account_limit)
    )
    response = fetch_x_with_hermes.extract_json(raw_output)
    if not isinstance(response, dict):
        raise RuntimeError("Hermes出力のルートがJSONオブジェクトではありません。")
    raw_items = response.get("items")
    return (
        fetch_x_with_hermes.normalize_items(raw_items, allowed),
        Counter(fetch_x_with_hermes.raw_response_counts(raw_items, allowed)),
        fetch_x_with_hermes.sanitize_raw_items(raw_items, allowed),
    )


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

    fresh_items, raw_counts, raw_items = fetch_accounts(accounts, per_account_limit)
    first_counts = Counter(item["handle"] for item in fresh_items)
    missing_initial = [handle for handle in accounts if first_counts[handle] == 0]

    retried_accounts: list[str] = []
    retry_errors: dict[str, str] = {}
    if config.get("retry_missing_accounts_individually", True):
        for handle in missing_initial:
            retried_accounts.append(handle)
            try:
                retried_items, retried_raw_counts, retried_raw_items = fetch_accounts(
                    [handle], per_account_limit
                )
                fresh_items.extend(retried_items)
                raw_counts.update(retried_raw_counts)
                raw_items.extend(retried_raw_items)
            except Exception as exc:
                retry_errors[handle] = f"{type(exc).__name__}: {exc}"

    # Discovery is complete. All later normalization must be local-only.
    run_fetch_x_with_hermes._DISCOVERY_PASS_PENDING = False
    fresh_items = run_fetch_x_with_hermes._ORIGINAL_NORMALIZE_ITEMS(
        fresh_items,
        allowed,
    )
    fresh_counts = Counter(item["handle"] for item in fresh_items)
    missing = validate_account_coverage(accounts, fresh_counts, minimum_accounts)

    if missing and not config.get("allow_missing_accounts_after_retry", False):
        raise RuntimeError(
            "個別再検索後も取得結果が0件のアカウントがあります: "
            + ", ".join(f"@{handle}" for handle in missing)
        )

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
    if not merged:
        raise RuntimeError("日次X入力から公開可能な投稿を1件も生成できませんでした。")

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
    fetch_x_with_hermes.atomic_write_json(
        RAW_COUNTS_PATH,
        {
            "schema_version": "1.0",
            "captured_at": fetch_x_with_hermes.now_jst_iso(),
            "raw_response_item_count": sum(raw_counts.values()),
            "per_account_raw_response_count": dict(raw_counts),
        },
    )
    fetch_x_with_hermes.atomic_write_json(
        RAW_ITEMS_PATH,
        {
            "schema_version": "1.0",
            "captured_at": fetch_x_with_hermes.now_jst_iso(),
            "source": "Hermes public X search",
            "items": raw_items,
        },
    )
    fetch_x_with_hermes.write_status(
        "success",
        changed=changed,
        partial=bool(missing),
        fresh_item_count=len(fresh_items),
        merged_item_count=len(merged),
        minimum_accounts_with_items=minimum_accounts,
        missing_accounts=missing,
        retried_accounts=retried_accounts,
        retry_errors=retry_errors,
        fresh_per_account=dict(fresh_counts),
        per_account=per_account,
        newest_post=merged[0] if merged else None,
    )

    print("=== Hermes X日次取得結果 ===")
    print(f"新規取得候補: {len(fresh_items)}件")
    print(f"統合後: {len(merged)}件")
    print(f"入力JSON更新: {'yes' if changed else 'no'}")
    if retried_accounts:
        print("個別再検索: " + ", ".join(f"@{h}" for h in retried_accounts))
    for handle in accounts:
        print(f"- @{handle}: {per_account[handle]}件")
    if missing:
        print("今回0件（次回も継続確認）: " + ", ".join(f"@{h}" for h in missing))
    if retry_errors:
        print("個別再検索エラー:", file=sys.stderr)
        for handle, error in retry_errors.items():
            print(f"- @{handle}: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    configure_daily_pipeline()
    try:
        raise SystemExit(main())
    except Exception as exc:
        fetch_x_with_hermes.write_status("failed", error=str(exc))
        print(f"X日次取得失敗: {exc}", file=sys.stderr)
        raise SystemExit(1)
