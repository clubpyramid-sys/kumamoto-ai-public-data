#!/bin/zsh
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "=== launchd ==="
launchctl print "gui/$UID/jp.cosanostra.kumamoto-public-data" 2>/dev/null | head -n 50 || echo "未登録"
echo
echo "=== pmset ==="
pmset -g sched
echo
echo "=== 最新実行結果 ==="
if [[ -f "$ROOT/runtime/status.json" ]]; then
  cat "$ROOT/runtime/status.json"
else
  echo "まだ実行されていません。"
fi
echo
echo "=== Git差分 ==="
if [[ -d "$ROOT/.git" ]]; then
  git -C "$ROOT" status --short
else
  echo "Git未初期化"
fi
read -k 1 "?何かキーを押すと閉じます..."
