# Hermes Agent＋Grok X投稿連携

## 全体構成

1. Hermes AgentがGrokで対象アカウントの公開投稿を取得
2. `runtime/x/hermes_latest.json` に保存
3. `./bin/run_update.sh` が入力を検証・正規化
4. `docs/x/all_latest.json` を生成
5. 変更がある場合だけGitHubへcommit・push
6. 各WebサイトがGitHub PagesのJSONを読み込む

公開URL:

`https://clubpyramid-sys.github.io/kumamoto-ai-public-data/x/all_latest.json`

## Hermesが保存する形式

`examples/hermes_x_output.example.json` を基準にしてください。

最低限必要な項目:

- `id`
- `handle`
- `published_at`
- `text`
- `url`

返信とリポストは初期設定では除外します。

## Hermesへの実行指示

対象アカウントの公開済みX投稿を取得し、`examples/hermes_x_output.example.json` と同じ構造のUTF-8 JSONとして `runtime/x/hermes_latest.json` に保存してください。

対象:

- `club_kumamoto`
- `kumamonsupport`
- `kumamoto_luna`
- `K_Ero_Gentleman`

条件:

- 新しい順
- 投稿IDと投稿URLを必ず含める
- 返信とリポストを除外
- 各アカウント最大20件
- DM、下書き、Cookie、認証情報、ローカルパスを含めない
- 取得失敗時は既存ファイルを上書きしない
- 一時ファイルへ保存後、JSON構文が正常な場合だけ正式ファイルへ置換

保存後に次を実行します。

```bash
./bin/run_update.sh
```

初回検証ではpushしません。

```bash
./bin/run_update.sh --dry-run
```

## Webページへの組み込み

HTMLに表示先を置きます。

```html
<div
  data-cnj-x-feed
  data-limit="6"
  data-handles="club_kumamoto,kumamoto_luna">
</div>
<script src="https://clubpyramid-sys.github.io/kumamoto-ai-public-data/x/widget.js" defer></script>
```

`data-handles` を省略すると全アカウントを表示します。

## 更新頻度

初期運用は6時間ごとを推奨します。

- 06:00
- 12:00
- 18:00
- 00:00

イベント開催日だけ1〜3時間ごとへ変更できます。

## 障害時

- Hermes取得失敗: 前回JSONを維持
- JSON異常: 公開データへ反映しない
- GitHub push失敗: Mac側に変更を保持
- Mac停止: GitHub Pages上の最後の正常データを表示
