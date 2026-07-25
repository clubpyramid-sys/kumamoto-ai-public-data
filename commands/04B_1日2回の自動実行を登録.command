#!/bin/zsh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="jp.cosanostra.kumamoto-public-data"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
TEMPLATE="$ROOT/launchd/$LABEL.twice-daily.plist.template"
mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"
python3 - "$TEMPLATE" "$TARGET" "$ROOT" <<'PY'
from pathlib import Path
import sys
src, dst, root = map(Path, sys.argv[1:])
text = src.read_text(encoding='utf-8').replace('__ROOT__', str(root))
dst.write_text(text, encoding='utf-8')
PY
plutil -lint "$TARGET"
launchctl bootout "gui/$UID" "$TARGET" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$UID" "$TARGET"
launchctl enable "gui/$UID/$LABEL"
echo "毎日05:00と17:00の自動実行を登録しました。"
read -k 1 "?何かキーを押すと閉じます..."
