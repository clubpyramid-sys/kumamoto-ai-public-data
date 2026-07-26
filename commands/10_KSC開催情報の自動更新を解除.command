#!/bin/zsh
set -euo pipefail
LABEL="jp.cosanostra.kumamoto-public-data.ksc-events.3-hourly"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl bootout "gui/$UID" "$TARGET" >/dev/null 2>&1 || true
rm -f "$TARGET"
echo "KSC開催情報の自動更新を解除しました。"
read -k 1 "?何かキーを押すと閉じます..."
