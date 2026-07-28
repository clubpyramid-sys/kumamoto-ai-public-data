from __future__ import annotations

import sys
from pathlib import Path

import fetch_x_with_hermes
import run_fetch_x_with_hermes

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "x_sources_daily.json"
INPUT_PATH = ROOT / "runtime" / "x" / "hermes_daily_latest.json"
STATUS_PATH = ROOT / "runtime" / "x" / "hermes_daily_fetch_status.json"


def configure_daily_paths() -> None:
    """Point the proven Hermes/X pipeline at the independent daily group."""

    fetch_x_with_hermes.CONFIG_PATH = CONFIG_PATH
    fetch_x_with_hermes.INPUT_PATH = INPUT_PATH
    fetch_x_with_hermes.STATUS_PATH = STATUS_PATH


def main() -> int:
    configure_daily_paths()
    return run_fetch_x_with_hermes.main()


if __name__ == "__main__":
    configure_daily_paths()
    try:
        raise SystemExit(main())
    except Exception as exc:
        fetch_x_with_hermes.write_status("failed", error=str(exc))
        print(f"X日次取得失敗: {exc}", file=sys.stderr)
        raise SystemExit(1)
