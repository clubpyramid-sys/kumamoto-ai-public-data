#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "仮想環境がありません。commands/01_初期セットアップ.command を先に実行してください。" >&2
  exit 1
fi

mkdir -p "$ROOT/logs" "$ROOT/runtime"
exec /usr/bin/caffeinate -dimsu "$ROOT/.venv/bin/python" "$ROOT/scripts/update_kumamoto_secret_club_events.py" "$@"
