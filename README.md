# kumamoto-ai-public-data

Mac Studioを毎日スリープ解除し、noteとYouTubeの公開情報を取得・検証して、変更がある場合だけGitHubへpushするデータ基盤です。GitHub PagesのJSONを熊本AI研究所、COSA NOSTRA JAPAN、kumamotoevent.comなどから参照します。

## 初回の実行順

1. `commands/01_初期セットアップ.command`
2. `commands/02_GitHub公開リポジトリを作成.command`
3. `commands/03_手動更新.command`
4. GitHub Pages上のJSONを確認
5. `commands/07_毎日04時50分にスリープ解除.command`
6. `commands/04_毎日1回の自動実行を登録.command`

標準時刻は、04:50スリープ解除、05:00取得開始です。夕方17:00も追加する場合は `04B_1日2回の自動実行を登録.command` を使用します。

## 公開JSON

- `docs/note/account_latest.json`
- `docs/note/magazines/m28cf0da750b4.json`
- `docs/youtube/channel_latest.json`
- `docs/sites/kumamoto_ai_laboratory.json`
- `docs/sites/cosanostra.json`
- `docs/sites/kumamotoevent.json`

公開予定URL:

`https://clubpyramid-sys.github.io/kumamoto-ai-public-data/`

## 取得方式

### note

- アカウント: RSS
- マガジン: 公開されている表示データを優先し、取得できない場合はマガジンHTMLの表示順から記事URLを抽出
- マガジンは公開日時で並べ替えず、表示・追加順を維持

noteは公式公開APIがないため、ページ構造変更時には `scripts/fetch_note.py` の修正が必要になる可能性があります。失敗時には既存JSONを残します。

### YouTube

- `YOUTUBE_API_KEY` が実行環境にある場合: YouTube Data API v3
- APIキーがない場合: `yt-dlp`

APIキーはリポジトリへ保存しません。通常はAPIキーなしで開始できます。

## 安全設計

- `runtime/staging_docs/` に候補JSONを作成
- 全JSONを検証してから `docs/` へ置換
- 0件、急激な件数減少、重複ID、不正URL、JSONエラーを検出
- 公開領域でローカルパス・代表的なトークン・秘密鍵パターンを検出
- 変更前JSONは `backups/` へローカル保存
- 取得失敗ソースは前回成功データを使用
- `generated_at` だけの変化ではcommitしない
- 日常のGit操作は `docs/` のみをcommit

## 設定

- 取得元: `config/sources.json`
- サイト別フィルター: `config/site_filters.json`
- 手動固定・除外ID: `config/manual_selections.json`

既存の動画選定を維持する場合は、動画IDを `pinned_youtube_ids` に追加するか、完全な項目を `manual_youtube_items` に移します。

## 手動コマンド

```bash
./bin/run_update.sh
./bin/run_update.sh --dry-run
./bin/run_update.sh --no-push
```

## ログ

- 最新状態: `runtime/status.json`
- 実行履歴: `logs/YYYY-MM.jsonl`
- launchd標準出力: `logs/launchd.stdout.log`
- launchdエラー: `logs/launchd.stderr.log`

`runtime/`、`logs/`、`backups/`、`private/` はGit管理外です。
