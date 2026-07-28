#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.clubpyramid.kumamoto-ai-public-data.x-feed-daily"
TEMPLATE="$ROOT/launchd/${LABEL}.plist.template"
TARGET="$HOME/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(id -u)"

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

echo "=== X投稿 追加4アカウント日次更新 登録 ==="
echo "ROOT: $ROOT"

if [[ ! -f "$TEMPLATE" ]]; then
  echo "テンプレートがありません: $TEMPLATE" >&2
  exit 1
fi

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "仮想環境がありません: $ROOT/.venv/bin/python" >&2
  exit 1
fi

HERMES_BIN="$(command -v hermes || true)"
if [[ -z "$HERMES_BIN" || ! -x "$HERMES_BIN" ]]; then
  echo "Hermes CLIが見つかりません。hermes -z が動く環境で実行してください。" >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs" "$ROOT/runtime/x"

python3 - "$TEMPLATE" "$TARGET" "$ROOT" "$HOME" "$HERMES_BIN" <<'PY'
from pathlib import Path
import sys

template, target, root, home, hermes = map(Path, sys.argv[1:])
text = template.read_text(encoding="utf-8")
text = text.replace("__ROOT__", str(root))
text = text.replace("__HOME__", str(home))
text = text.replace("__HERMES_BIN__", str(hermes))
target.write_text(text, encoding="utf-8")
PY

plutil -lint "$TARGET"

launchctl bootout "$DOMAIN" "$TARGET" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$TARGET"
launchctl enable "$DOMAIN/$LABEL"

echo
echo "登録完了: $TARGET"
echo "対象: @SEA_PYRAMID / @CLUB_PYRAMID / @STARLIGHT_CAFE_ / @kumamotodeai"
echo "実行時刻: 毎日 05:00"
echo "登録時の即時実行は行いません。次回05:00から実行します。"

echo
launchctl print "$DOMAIN/$LABEL" | sed -n '1,90p'
echo
echo "ログ:"
echo "  $ROOT/logs/x_feed_daily_launchd.out.log"
echo "  $ROOT/logs/x_feed_daily_launchd.err.log"
