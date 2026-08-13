#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
X_LOCK_DIR="$ROOT/runtime/locks/x-feed-update.lock"
PUBLIC_LOCK_DIR="${PUBLIC_DATA_GIT_LOCK_DIR:-$HOME/AI_Agent_Runtime/.locks/kumamoto-public-data-git.lock}"
LOG_DIR="$ROOT/logs"
mkdir -p "$ROOT/runtime/locks" "$ROOT/runtime/x" "$LOG_DIR" "$(dirname "$PUBLIC_LOCK_DIR")"

if ! mkdir "$X_LOCK_DIR" 2>/dev/null; then
  echo "X更新はすでに実行中です: $X_LOCK_DIR" >&2
  exit 0
fi

PUBLIC_LOCK_ACQUIRED=0
cleanup() {
  if [[ "$PUBLIC_LOCK_ACQUIRED" -eq 1 ]]; then
    rmdir "$PUBLIC_LOCK_DIR" 2>/dev/null || true
  fi
  rmdir "$X_LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for ATTEMPT in {1..180}; do
  if mkdir "$PUBLIC_LOCK_DIR" 2>/dev/null; then
    PUBLIC_LOCK_ACQUIRED=1
    break
  fi
  if [[ "$ATTEMPT" -eq 1 ]]; then
    echo "note・YouTube等の公開更新が実行中です。完了を待ちます。" >&2
  fi
  sleep 10
done

if [[ "$PUBLIC_LOCK_ACQUIRED" -ne 1 ]]; then
  echo "公開データ更新ロックを30分以内に取得できませんでした。" >&2
  exit 1
fi

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

"$ROOT/.venv/bin/python" "$ROOT/scripts/run_fetch_x_daily_with_hermes.py"
"$ROOT/.venv/bin/python" "$ROOT/scripts/publish_x_daily.py"
"$ROOT/.venv/bin/python" "$ROOT/scripts/write_x_pipeline_audit.py" \
  --config "$ROOT/config/x_sources_daily.json" \
  --fetch-status "$ROOT/runtime/x/hermes_daily_fetch_status.json" \
  --raw-counts "$ROOT/runtime/x/hermes_daily_raw_counts.json" \
  --input "$ROOT/runtime/x/hermes_daily_latest.json" \
  --public "$ROOT/docs/x/daily_latest.json" \
  --output "$ROOT/runtime/x/hermes_daily_pipeline_audit.json"

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
