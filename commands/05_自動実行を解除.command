#!/bin/zsh
set -euo pipefail
LABEL="jp.cosanostra.kumamoto-public-data"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl bootout "gui/$UID" "$TARGET" >/dev/null 2>&1 || true
rm -f "$TARGET"
echo "自動実行を解除しました。"
read -k 1 "?何かキーを押すと閉じます..."
