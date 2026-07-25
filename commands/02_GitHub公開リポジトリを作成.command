#!/bin/zsh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
REPO="clubpyramid-sys/kumamoto-ai-public-data"

if ! command -v gh >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    echo "GitHub CLIをインストールします。"
    brew install gh
  else
    echo "GitHub CLIがありません。次のページで公開リポジトリ kumamoto-ai-public-data を作成してください。"
    open "https://github.com/new?name=kumamoto-ai-public-data&visibility=public"
    read -k 1 "?何かキーを押すと終了します..."
    exit 1
  fi
fi

gh auth status >/dev/null 2>&1 || gh auth login
gh auth setup-git

if [[ ! -d .git ]]; then
  git init -b main
  git config user.name "clubpyramid-sys"
  git config user.email "282072234+clubpyramid-sys@users.noreply.github.com"
  git add .
  git commit -m "feat: initialize note and YouTube public data pipeline"
fi

if gh repo view "$REPO" >/dev/null 2>&1; then
  echo "既存リポジトリを使用します: $REPO"
  git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$REPO.git"
  git push -u origin main
else
  gh repo create "$REPO" --public --source=. --remote=origin --push \
    --description "Public JSON feeds for note and YouTube updates used by Kumamoto web sites"
fi

if ! gh api "repos/$REPO/pages" >/dev/null 2>&1; then
  printf '%s' '{"source":{"branch":"main","path":"/docs"}}' | gh api --method POST "repos/$REPO/pages" --input - || true
fi

echo
echo "公開リポジトリ: https://github.com/$REPO"
echo "GitHub Pages: https://clubpyramid-sys.github.io/kumamoto-ai-public-data/"
echo "次: 03_手動更新.command"
read -k 1 "?何かキーを押すと閉じます..."
