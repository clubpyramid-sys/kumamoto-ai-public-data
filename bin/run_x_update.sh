#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCK_DIR="$ROOT/runtime/locks/x-feed-update.lock"
PUBLIC_LOCK_DIR="${PUBLIC_DATA_GIT_LOCK_DIR:-$HOME/AI_Agent_Runtime/.locks/kumamoto-public-data-git.lock}"
LOG_DIR="$ROOT/logs"
mkdir -p "$ROOT/runtime/locks" "$ROOT/runtime/x" "$LOG_DIR"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "X自動更新はすでに実行中です: $LOCK_DIR" >&2
  exit 0
fi
PUBLIC_LOCK_ACQUIRED=0
cleanup() {
  if [[ "$PUBLIC_LOCK_ACQUIRED" -eq 1 ]]; then
    rmdir "$PUBLIC_LOCK_DIR" 2>/dev/null || true
  fi
  rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

mkdir -p "$(dirname "$PUBLIC_LOCK_DIR")"
for ATTEMPT in {1..180}; do
  if mkdir "$PUBLIC_LOCK_DIR" 2>/dev/null; then
    PUBLIC_LOCK_ACQUIRED=1
    break
  fi
  if [[ "$ATTEMPT" -eq 1 ]]; then
    echo "他の公開データ更新が実行中です。完了を待ちます。" >&2
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
  echo "自動更新はmainブランチでのみ実行します。現在: $CURRENT_BRANCH" >&2
  exit 1
fi

"$ROOT/.venv/bin/python" "$ROOT/scripts/public_git_sync.py" "$ROOT"

"$ROOT/.venv/bin/python" "$ROOT/scripts/run_fetch_x_with_hermes.py"
"$ROOT/.venv/bin/python" "$ROOT/scripts/publish_x.py"
"$ROOT/.venv/bin/python" "$ROOT/scripts/public_git_sync.py" "$ROOT"
"$ROOT/.venv/bin/python" "$ROOT/scripts/write_x_pipeline_audit.py" \
  --config "$ROOT/config/x_sources.json" \
  --fetch-status "$ROOT/runtime/x/hermes_fetch_status.json" \
  --raw-counts "$ROOT/runtime/x/hermes_raw_counts.json" \
  --input "$ROOT/runtime/x/hermes_latest.json" \
  --public "$ROOT/docs/x/all_latest.json" \
  --output "$ROOT/runtime/x/hermes_pipeline_audit.json"
python3 "${X_STATUS_SYNC_SCRIPT:-$HOME/AI_Agent_Runtime/chat-state-recorder/sync_x_pipeline_status.py}"

"$ROOT/.venv/bin/python" - <<'PY'
import json
from pathlib import Path

root = Path.cwd()
status_path = root / "runtime" / "x" / "hermes_publish_status.json"
status = json.loads(status_path.read_text(encoding="utf-8"))
if status.get("status") != "success":
    raise SystemExit("X公開処理が成功していません: " + json.dumps(status, ensure_ascii=False))
print("X公開処理: success")
print("Git:", (status.get("git") or {}).get("status"))
PY
