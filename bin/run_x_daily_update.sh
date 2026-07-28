#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCK_DIR="$ROOT/runtime/locks/x-feed-update.lock"
LOG_DIR="$ROOT/logs"
mkdir -p "$ROOT/runtime/locks" "$ROOT/runtime/x" "$LOG_DIR"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "X更新はすでに実行中です: $LOCK_DIR" >&2
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT INT TERM

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "仮想環境がありません。初期セットアップを実行してください。" >&2
  exit 1
fi

CURRENT_BRANCH="$(git branch --show-current)"
if [[ "$CURRENT_BRANCH" != "main" ]]; then
  echo "X日次更新はmainブランチでのみ実行します。現在: $CURRENT_BRANCH" >&2
  exit 1
fi

DAILY_DOC="docs/x/daily_latest.json"
DOCS_DIRTY="$(git status --porcelain -- "$DAILY_DOC")"
if [[ -n "$DOCS_DIRTY" ]]; then
  echo "$DAILY_DOC に未処理の変更があるため、日次更新を停止します。" >&2
  echo "$DOCS_DIRTY" >&2
  exit 1
fi

git fetch origin main --quiet
BEHIND="$(git rev-list --count HEAD..origin/main)"
if [[ "$BEHIND" -gt 0 ]]; then
  git pull --ff-only origin main
fi

"$ROOT/.venv/bin/python" "$ROOT/scripts/run_fetch_x_daily_with_hermes.py"
"$ROOT/.venv/bin/python" "$ROOT/scripts/publish_x_daily.py"

"$ROOT/.venv/bin/python" - <<'PY'
import json
from pathlib import Path

root = Path.cwd()
fetch_status = json.loads(
    (root / "runtime/x/hermes_daily_fetch_status.json").read_text(encoding="utf-8")
)
publish_status = json.loads(
    (root / "runtime/x/hermes_daily_publish_status.json").read_text(encoding="utf-8")
)

if fetch_status.get("status") != "success":
    raise SystemExit("X日次取得が成功していません")
if publish_status.get("status") != "success":
    raise SystemExit("X日次公開が成功していません")

print("X日次取得: success")
print("X日次公開: success")
print("件数:", publish_status.get("item_count"))
print("Git:", (publish_status.get("git") or {}).get("status"))
PY
