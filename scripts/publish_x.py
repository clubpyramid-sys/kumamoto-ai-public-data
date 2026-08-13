from __future__ import annotations

import sys
from pathlib import Path

from common import load_json
from publish_x_daily import publish_x, safe_relative_path, write_status

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "x_sources.json"


def main() -> int:
    try:
        return publish_x(CONFIG_PATH)
    except Exception as exc:
        config = load_json(CONFIG_PATH, {})
        status_rel = safe_relative_path(
            str(config.get("publish_status") or "runtime/x/hermes_publish_status.json")
        )
        write_status(ROOT / status_rel, "failed", error=str(exc))
        print(f"X公開失敗: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
