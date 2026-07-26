from __future__ import annotations

import argparse
import fcntl
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from common import append_jsonl, load_json, now_iso  # noqa: E402
from fetch_kumamoto_secret_club_events import (  # noqa: E402
    DEFAULT_LOG_DIR,
    DEFAULT_OUTPUT,
    DEFAULT_SCHEMA,
    RSS_URL,
    run as fetch_events,
)
from publish_git import publish  # noqa: E402

PUBLIC_PATH = "docs/events/kumamoto_secret_club_current.json"
LOCK_PATH = ROOT / "runtime" / "kumamoto_secret_club_events.lock"


def update(no_push: bool = False, fetcher: Any = fetch_events, publisher: Any = publish) -> dict[str, Any]:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another KSC event update is already running") from exc

        changed, fetch_record = fetcher(
            RSS_URL,
            DEFAULT_OUTPUT,
            DEFAULT_SCHEMA,
            DEFAULT_LOG_DIR,
            15,
        )
        if not DEFAULT_OUTPUT.is_file():
            raise RuntimeError("公開JSONが存在しないため、Git処理を停止します。")
        sources = load_json(ROOT / "config" / "sources.json", {})
        git_config = dict(sources.get("git", {}))
        if no_push:
            git_config["auto_push"] = False
        git_result = publisher(ROOT, git_config, paths=[PUBLIC_PATH])
        result = {
            "executed_at": now_iso(),
            "operation": "publish_kumamoto_secret_club_events",
            "fetch_changed": changed,
            "fetch_result": fetch_record.get("fetch_result"),
            "github_push": git_result,
        }
        log_path = DEFAULT_LOG_DIR / f"{datetime.now().astimezone():%Y-%m}.jsonl"
        append_jsonl(log_path, result)
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="開催情報を取得し、対象JSONだけを変更時に公開します。")
    parser.add_argument("--no-push", action="store_true", help="対象JSONをcommitするがpushしない")
    args = parser.parse_args(argv)
    try:
        result = update(no_push=args.no_push)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
