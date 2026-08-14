from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from common import atomic_write_json, load_json, now_iso, prepare_payload
from import_hermes_x import import_hermes_x
from publish_git import publish_isolated
from validate import suspicious_drop, validate_source_payload

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "x_sources_daily.json"


def safe_relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"安全でない相対パスです: {value}")
    return path


def write_status(path: Path, status: str, **extra: Any) -> None:
    atomic_write_json(
        path,
        {
            "status": status,
            "finished_at": now_iso(),
            **extra,
        },
    )


def target_has_unpublished_change(root: Path, target: Path) -> bool:
    """Detect a prior interrupted write without staging or discarding it."""
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--", str(target.relative_to(root))],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("X公開対象のGit状態を確認できませんでした")
    return bool(result.stdout.strip())


def publish_x(config_path: Path, no_push: bool = False) -> int:
    """Publish one X group without staging the shared collector checkout."""
    config = load_json(config_path, {})
    if not config.get("enabled", False):
        raise RuntimeError("X日次取得設定が無効です。")

    output_rel = safe_relative_path(str(config.get("output") or "x/daily_latest.json"))
    target = ROOT / "docs" / output_rel
    status_rel = safe_relative_path(
        str(config.get("publish_status") or "runtime/x/hermes_daily_publish_status.json")
    )
    status_path = ROOT / status_rel

    existing = load_json(target, {})
    previous_items = existing.get("items", []) if isinstance(existing, dict) else []
    payload = import_hermes_x(ROOT, config, previous_items=previous_items)
    payload["source"] = dict(config.get("source") or payload.get("source") or {})
    payload["collection_method"] = str(
        config.get("collection_method") or payload.get("collection_method") or "Hermes Agent with Grok"
    )

    sources = load_json(ROOT / "config" / "sources.json", {})
    drop_error = suspicious_drop(existing, payload, sources.get("safety", {}))
    if drop_error:
        raise RuntimeError(drop_error)

    prepared, changed = prepare_payload(payload, existing)
    errors = validate_source_payload(prepared)
    if errors:
        raise RuntimeError(" / ".join(errors))

    if changed:
        if target.exists():
            timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
            backup = ROOT / "backups" / timestamp / output_rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
        atomic_write_json(target, prepared)

    git_config = dict(sources.get("git", {}))
    if no_push:
        git_config["auto_push"] = False
    publish_required = changed or target_has_unpublished_change(ROOT, target)
    git_result = (
        publish_isolated(ROOT, git_config, paths=[str(Path("docs") / output_rel)])
        if publish_required
        else {"status": "no_changes"}
    )

    write_status(
        status_path,
        "success",
        changed=changed,
        publish_required=publish_required,
        output=str(output_rel),
        item_count=len(prepared.get("items", [])),
        git=git_result,
        newest_post=prepared.get("items", [None])[0] if prepared.get("items") else None,
    )

    print("=== X公開結果 ===")
    print(f"公開先: docs/{output_rel}")
    print(f"件数: {len(prepared.get('items', []))}")
    print(f"変更: {'yes' if changed else 'no'}")
    print(f"Git: {git_result.get('status')}")
    return 0


def publish_daily(no_push: bool = False) -> int:
    return publish_x(CONFIG_PATH, no_push=no_push)


def main() -> int:
    parser = argparse.ArgumentParser(description="追加4アカウントの日次X JSONを公開")
    parser.add_argument("--no-push", action="store_true", help="commitは行うがpushしない")
    args = parser.parse_args()
    try:
        return publish_daily(no_push=args.no_push)
    except Exception as exc:
        config = load_json(CONFIG_PATH, {})
        status_rel = safe_relative_path(
            str(config.get("publish_status") or "runtime/x/hermes_daily_publish_status.json")
        )
        write_status(ROOT / status_rel, "failed", error=str(exc))
        print(f"X日次公開失敗: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
