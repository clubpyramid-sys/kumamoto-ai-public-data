#!/bin/zsh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

mkdir -p runtime logs backups private
chmod +x "$ROOT"/bin/*.sh "$ROOT"/commands/*.command

PYTHON_BIN="$(command -v python3 || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "python3が見つかりません。HomebrewまたはPython 3を導入してください。"
  read -k 1 "?何かキーを押すと終了します..."
  exit 1
fi

"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/self_test.py

echo
echo "=========================================="
echo "初期セットアップ完了"
echo "次: 02_GitHub公開リポジトリを作成.command"
echo "=========================================="
read -k 1 "?何かキーを押すと閉じます..."
