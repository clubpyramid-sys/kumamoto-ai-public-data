# Hermes＋Grok X投稿 自動更新

## 根本原因

従来の `./bin/run_update.sh` は、Hermes Agentを起動してXを検索する処理を含んでいません。

処理内容は次のとおりでした。

```text
runtime/x/hermes_latest.json を読み込む
↓
検証・正規化
↓
docs/x/all_latest.json を生成
↓
変更時のみcommit・push
```

そのため、2026年7月25日に手動で保存した `runtime/x/hermes_latest.json` が更新されない限り、note・YouTubeなどの定期処理が動いてもX公開JSONは変化しません。

今回、次の自動取得経路を追加しました。

```text
launchd（00:00／06:00／12:00／18:00）
↓
Hermes CLI one-shotモード
↓
Hermes Desktop／CLIで保存済みのprovider・model設定
↓
Xライブ検索
↓
JSON抽出・アカウント検証・投稿ID検証
↓
前回正常データとの安全な統合
↓
runtime/x/hermes_latest.json を原子的に更新
↓
既存の run_update.sh
↓
GitHub mainへ変更時のみpush
↓
GitHub Pages
```

## 安全設計

- 4アカウントすべてから1件以上取得できない場合は更新しない
- 返信・リポストを除外
- 許可アカウント以外を除外
- 投稿IDが数字でないデータを除外
- X以外の投稿URLを除外
- 未来日時など不正な日時を除外
- メディアURLはX公式配信ドメインだけを許可
- 前回正常データと統合して、取得件数が一時的に少ない場合も古い正常投稿を維持
- JSONは一時ファイルへ書き、検証後に原子的に置換
- 取得失敗時は既存JSONを上書きしない
- `docs/` に未処理のローカル変更がある場合は、自動commitを行わず停止
- 二重起動をロックディレクトリで防止
- `main` ブランチ以外では自動実行しない
- provider側エラーは認証情報を伏せてコードとメッセージを記録

## 使用するHermes設定

通常は、Hermes Desktopまたは次のコマンドで選択済みのprovider・modelをそのまま利用します。

```bash
hermes model
```

自動更新側では、通常の実行時に `--provider` と `--model` を強制しません。

これにより、Hermes Desktopで実際に動作確認済みのGrok設定、OAuth状態、モデル選択をlaunchdからも利用します。

診断時だけ一時的に強制する場合は、次の環境変数を使えます。

```text
HERMES_PROVIDER_OVERRIDE
HERMES_MODEL_OVERRIDE
```

旧設定の次の環境変数は使用しません。

```text
GROK_PROVIDER
GROK_MODEL
```

## 登録

```bash
cd "$HOME/AI_Agent_Runtime/kumamoto-ai-public-data"
git switch main
git pull --ff-only
zsh commands/10_X投稿自動更新を登録.command
```

登録時に次を行います。

1. Hermes CLIの実体パスを自動検出
2. launchd用plistを生成
3. plist構文を検証
4. LaunchAgentを登録
5. 初回更新を即時実行

既に登録済みの場合でも、テンプレートの環境変数を更新するため、修正版取得後に登録コマンドを再実行して構いません。

## 実行時刻

```text
00:00
06:00
12:00
18:00
```

イベント開催日に更新頻度を上げる場合は、launchdテンプレートの `StartCalendarInterval` を変更して再登録してください。

## 状態確認

```bash
cd "$HOME/AI_Agent_Runtime/kumamoto-ai-public-data"
zsh commands/11_X投稿自動更新状態を確認.command
```

確認できる内容：

- launchdの登録状態
- Hermes取得の成功・失敗
- provider側エラーコードと安全なエラーメッセージ
- 取得件数とアカウント別件数
- 最新投稿ID
- 公開処理の結果
- Git commit・push状態
- 標準出力・標準エラーログ

## Hermesの認証・モデル確認

```bash
hermes doctor
hermes model
```

`hermes doctor` で認証状態を確認し、`hermes model` でHermes Desktopと同じprovider・modelを選択します。

## ログ

```text
logs/x_feed_launchd.out.log
logs/x_feed_launchd.err.log
runtime/x/hermes_fetch_status.json
runtime/status.json
```

## 手動実行

launchdを待たずに実行する場合：

```bash
cd "$HOME/AI_Agent_Runtime/kumamoto-ai-public-data"
/bin/zsh bin/run_x_update.sh
```

## 公開確認

```bash
curl -fsSL \
  "https://clubpyramid-sys.github.io/kumamoto-ai-public-data/x/all_latest.json" \
  | python3 -c '
import json, sys
value = json.load(sys.stdin)
print("件数:", len(value.get("items", [])))
print("生成日時:", value.get("generated_at"))
print("取得日時:", value.get("last_source_update_at"))
latest = value.get("items", [{}])[0]
print("最新投稿:", latest.get("handle"), latest.get("id"), latest.get("published_at"))
'
```

## テスト

```bash
python3 -m unittest tests/test_fetch_x_with_hermes.py -v
python3 -m unittest tests/test_hermes_response_parser.py -v
python3 -m py_compile scripts/fetch_x_with_hermes.py
python3 -m py_compile scripts/run_fetch_x_with_hermes.py
python3 -m py_compile scripts/hermes_response_parser.py
```
