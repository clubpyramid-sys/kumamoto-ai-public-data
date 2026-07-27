#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.clubpyramid.kumamoto-ai-public-data.x-feed"
DOMAIN="gui/$(id -u)"

echo "=== launchd状態 ==="
launchctl print "$DOMAIN/$LABEL" 2>&1 | sed -n '1,120p' || true

echo
echo "=== Hermes取得状態 ==="
if [[ -f "$ROOT/runtime/x/hermes_fetch_status.json" ]]; then
  cat "$ROOT/runtime/x/hermes_fetch_status.json"
else
  echo "まだ取得状態ファイルがありません。"
fi

echo
echo "=== 公開更新状態 ==="
if [[ -f "$ROOT/runtime/status.json" ]]; then
  cat "$ROOT/runtime/status.json"
else
  echo "まだ公開状態ファイルがありません。"
fi

echo
echo "=== 最新ログ ==="
tail -n 80 "$ROOT/logs/x_feed_launchd.out.log" 2>/dev/null || true
tail -n 80 "$ROOT/logs/x_feed_launchd.err.log" 2>/dev/null || true
