#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCK_DIR="$ROOT/runtime/locks/public-data-update.lock"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "仮想環境がありません。commands/01_初期セットアップ.command を先に実行してください。" >&2
  exit 1
fi

mkdir -p "$ROOT/logs" "$ROOT/runtime/locks" "$ROOT/backups"

ACQUIRED=0
for ATTEMPT in {1..180}; do
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    ACQUIRED=1
    break
  fi
  if [[ "$ATTEMPT" -eq 1 ]]; then
    echo "別の公開データ更新が実行中です。完了を待ちます: $LOCK_DIR" >&2
  fi
  sleep 10
done

if [[ "$ACQUIRED" -ne 1 ]]; then
  echo "公開データ更新ロックを30分以内に取得できませんでした。" >&2
  exit 1
fi

trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT INT TERM

/usr/bin/caffeinate -dimsu "$ROOT/.venv/bin/python" "$ROOT/scripts/run_all.py" "$@"
