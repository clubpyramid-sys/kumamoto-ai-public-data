#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCK_DIR="$ROOT/runtime/locks/x-feed-update.lock"
LOG_DIR="$ROOT/logs"
mkdir -p "$ROOT/runtime/locks" "$ROOT/runtime/x" "$LOG_DIR"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "X自動更新はすでに実行中です: $LOCK_DIR" >&2
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
  echo "自動更新はmainブランチでのみ実行します。現在: $CURRENT_BRANCH" >&2
  exit 1
fi

DOCS_DIRTY="$(git status --porcelain -- docs)"
if [[ -n "$DOCS_DIRTY" ]]; then
  echo "docs/に未処理の変更があるため、自動更新を停止します。" >&2
  echo "$DOCS_DIRTY" >&2
  exit 1
fi

git fetch origin main --quiet
BEHIND="$(git rev-list --count HEAD..origin/main)"
if [[ "$BEHIND" -gt 0 ]]; then
  git pull --ff-only origin main
fi

"$ROOT/.venv/bin/python" "$ROOT/scripts/run_fetch_x_with_hermes.py"
"$ROOT/bin/run_update.sh"

"$ROOT/.venv/bin/python" - <<'PY'
import json
from pathlib import Path

root = Path.cwd()
status_path = root / "runtime" / "status.json"
status = json.loads(status_path.read_text(encoding="utf-8"))
x_results = [
    item for item in status.get("sources", [])
    if item.get("source_id") == "x-hermes-grok"
]
if not x_results or x_results[0].get("status") != "success":
    raise SystemExit("X公開処理が成功していません: " + json.dumps(x_results, ensure_ascii=False))
print("X公開処理: success")
print("Git:", status.get("git", {}).get("status"))
PY
