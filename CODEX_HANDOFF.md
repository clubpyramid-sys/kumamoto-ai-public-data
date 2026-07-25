# Codex引き継ぎ指示

このフォルダは、Mac Studioでnote・YouTubeの公開情報を取得し、検証済みJSONをGitHub Pagesへ配信する初期実装です。

## Codexに依頼する作業

1. このフォルダを `$HOME/Desktop/AI_Agent/kumamoto-ai-public-data` に配置する。
2. `commands/01_初期セットアップ.command` を実行し、依存関係とセルフテストを確認する。
3. `commands/02_GitHub公開リポジトリを作成.command` を実行し、`clubpyramid-sys/kumamoto-ai-public-data` を公開リポジトリとして作成する。
4. `commands/03_手動更新.command` を実行し、以下の実データ取得を確認する。
   - noteアカウントRSS
   - noteマガジン表示順
   - YouTubeチャンネル最新動画
5. `docs/` 配下にローカルパス、認証情報、メールアドレス、秘密鍵がないことを再確認する。
6. GitHub Pagesの公開URLから全JSONを取得し、HTTP 200、JSON構文、件数、URL、サムネイルを検査する。
7. 既存サイトの動画選定データを確認し、必要なIDを `config/manual_selections.json` へ移植する。既存データを上書き・削除しない。
8. `commands/07_毎日04時50分にスリープ解除.command` と `commands/04_毎日1回の自動実行を登録.command` を実行する。
9. 翌日の自動実行後、`runtime/status.json`、`logs/launchd.stdout.log`、GitHub commit、GitHub Pagesを確認する。
10. 熊本AI研究所から先に `sites/kumamoto_ai_laboratory.json` を読み込ませ、静的フォールバックを残したまま本番確認する。

## 重要な制約

- 公開ルートへ追加するCSS・JS等はサイト固有プレフィックスを付ける。
- 各サイトの既存 `index.html` 以外を不用意に上書きしない。
- 取得に失敗したソースは、前回成功JSONを維持する。
- 内容が変わらない場合はGitHubへcommit/pushしない。
- Xの取得処理は追加しない。将来の共通ダッシュボード接続だけを考慮する。
