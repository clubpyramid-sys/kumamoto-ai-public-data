#!/bin/zsh
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/bin/run_update.sh"
RESULT=$?
echo
if [[ $RESULT -eq 0 ]]; then
  echo "更新処理は正常に完了しました。"
else
  echo "更新処理でエラーが発生しました。runtime/status.json と logs を確認してください。"
fi
read -k 1 "?何かキーを押すと閉じます..."
exit $RESULT
