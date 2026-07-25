#!/bin/zsh
set -euo pipefail
echo "毎日04:50にMacをスリープ解除する設定を登録します。管理者パスワードが必要です。"
sudo pmset repeat wake MTWRFSU 04:50:00
pmset -g sched
echo "登録しました。Macはシャットダウンせず、ログインした状態でスリープ運用してください。"
read -k 1 "?何かキーを押すと閉じます..."
