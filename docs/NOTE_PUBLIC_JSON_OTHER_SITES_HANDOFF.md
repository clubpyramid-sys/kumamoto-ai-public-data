# 他サイト展開用引き継ぎ文書
## GitHub公開JSONを使ったnote新着情報の自動表示

作成日：2026年7月25日
基準実装：熊本AI研究所
対象候補：COSA NOSTRA JAPAN、kumamotoevent.com、その他の関連サイト

## 1. 完成した仕組み

熊本AI研究所では、noteの新着記事をWebサイトが直接取得するのではなく、Mac Studioで取得・検証した情報をGitHubへ公開し、各サイトがGitHub Pages上のJSONを参照する方式へ移行した。

```text
noteアカウント・noteマガジン
↓
Mac Studioの定期処理
↓
記事情報とサムネイルを取得
↓
重複・URL・JSON構文・秘密情報を検証
↓
変更がある場合だけGitHubへcommit・push
↓
GitHub Pagesで公開
↓
各サイトのJavaScriptがJSONを取得
↓
正常な場合だけ新着カードへ置換
↓
失敗時はHTML内の静的カードを維持
```

この構成により、note更新のたびに各サイトをFTPする必要がなくなった。

## 2. 公開データ基盤

GitHubリポジトリ：

```text
https://github.com/clubpyramid-sys/kumamoto-ai-public-data
```

GitHub Pages：

```text
https://clubpyramid-sys.github.io/kumamoto-ai-public-data/
```

サイト別JSON：

```text
熊本AI研究所
https://clubpyramid-sys.github.io/kumamoto-ai-public-data/sites/kumamoto_ai_laboratory.json

COSA NOSTRA JAPAN
https://clubpyramid-sys.github.io/kumamoto-ai-public-data/sites/cosanostra.json

kumamotoevent.com
https://clubpyramid-sys.github.io/kumamoto-ai-public-data/sites/kumamotoevent.json
```

各サイトは、自分専用のサイト別JSONを参照する。

## 3. 最重要原則

### データ取得と表示を分離する

```text
Mac Studio
＝取得、整形、検証、GitHub公開

GitHub
＝公開JSONの保存、履歴管理、配信

Webサイト
＝JSONを読み込み、カード表示

Codex／Antigravity
＝設計、実装、修正、検証
```

### 静的フォールバックを消さない

HTML内の既存カードを削除して、空のコンテナだけにしてはいけない。

```text
JSON取得成功
→ 動的カードへ置換

JSON取得失敗・空・不正
→ HTML内の静的カードを維持

JavaScript停止
→ 静的カードをそのまま表示
```

外部サービス障害時にも記事欄を空白にしない。

## 4. 熊本AI研究所で発生した問題

### JavaScript起動属性が生成時に消えた

直接HTMLだけを直すと、次回ビルドで元へ戻る。

対策：

- HTML生成スクリプトを正本として修正
- 動的表示領域のIDまたはdata属性を生成時に必ず付与
- JavaScript読み込みも生成処理へ含める
- 検証スクリプトで起動属性の存在を確認

### BiNDではPHPを主経路にできなかった

PHP GETがHTTP 501となったため、サーバー側RSS取得は使えなかった。

対策：

- GitHub Pagesの静的JSONを主経路にする
- PHPへ依存しない
- HTML内の静的カードを障害時の予備表示にする

### GitHub JSONの構造に旧JavaScriptが未対応だった

公開JSONの基本構造：

```json
{
  "schema_version": "1.0",
  "note_items": [],
  "youtube_items": []
}
```

対策：

- `schema_version`を確認
- `note_items`が配列か確認
- 必須項目が欠けた記事を除外
- 有効記事が1件以上ある場合だけDOMを置換

### サムネイルは「取得」と「伝播」の両方が必要だった

最初は、note記事に見出し画像があっても`thumbnail_url`が`null`だった。

その後、アカウントJSONでは画像を取得できても、マガジンJSONとサイト別JSONへ伝播していなかった。

最終対策：

1. RSS内の画像情報を優先
2. RSSに画像がない記事だけ記事ページの`og:image`等から補完
3. 記事IDまたは正規化URLでキャッシュ
4. 同じ記事をアカウントとマガジンで重複取得しない
5. マガジン側が`null`の場合だけアカウント側画像を補完
6. サイト別JSON生成時に`thumbnail_url`を維持
7. 一時的な通信失敗で正常画像を`null`へ戻さない

### ローカル修正だけでは本番へ反映されない

```text
ローカルJSON生成
≠
GitHub公開
≠
サイト表示
```

必ず次を確認する。

```text
git status
git diff
commit
push
GitHub Pages公開JSON
サイトのNetwork
```

## 5. 公開JSONの記事項目

```json
{
  "id": "記事固有ID",
  "title": "記事タイトル",
  "url": "https://note.com/...",
  "published_at": "公開日時",
  "summary": "概要",
  "thumbnail_url": "https://assets.st-note.com/...",
  "author": "著者",
  "source_id": "取得元ID",
  "source_type": "note_account または note_magazine",
  "selection_mode": "automatic / pinned / manual"
}
```

最低限必要なのは`title`と`url`。画像や概要がなくてもカード全体を失敗させない。

## 6. サイト側JavaScript

GitHub Pagesとブラウザのキャッシュ対策として、15分単位のクエリを付ける。

```javascript
const baseUrl =
  "https://clubpyramid-sys.github.io/kumamoto-ai-public-data/sites/cosanostra.json";

const bucket = Math.floor(Date.now() / (15 * 60 * 1000));
const feedUrl = `${baseUrl}?v=${bucket}`;
```

取得時：

```javascript
fetch(feedUrl, {
  method: "GET",
  cache: "no-store",
  headers: { Accept: "application/json" },
  signal
});
```

実装要件：

- `AbortController`で8〜12秒のタイムアウト
- 外部データを`innerHTML`へ直接入れない
- `document.createElement`と`textContent`でDOM生成
- すべてのカードをDocumentFragmentで完成後に置換
- 外部リンクは`target="_blank" rel="noopener noreferrer"`
- 画像は`loading="lazy"`、`decoding="async"`
- 画像失敗時は画像だけ非表示
- タイトル、概要、リンクは残す
- 空配列や不正JSONでは静的表示を維持

## 7. noteサムネイル

熊本AI研究所では、noteの見出し文字を切らないため次を採用した。

```css
aspect-ratio: 2 / 1;
object-fit: contain;
```

他サイトでも原則として「2:1・切り取りなし」を推奨する。背景余白が気になる場合は、画像枠の背景色をサイトのカード色に合わせる。

## 8. サイト固有ファイル名

### COSA NOSTRA JAPAN

```text
cnj_public_feed.js
cnj_public_feed.css
cnj-public-note-feed
cnj-public-youtube-feed
```

### kumamotoevent.com

```text
ke_public_feed.js
ke_public_feed.css
ke-public-note-feed
ke-public-youtube-feed
```

公開ルートの既存`styles.css`、`script.js`、`assets`等を不用意に上書きしない。トップページの`index.html`のみ、必要な箇所を編集してよい。

## 9. COSA NOSTRA JAPANへの注意

JSON：

```text
https://clubpyramid-sys.github.io/kumamoto-ai-public-data/sites/cosanostra.json
```

- 黒〜深緑の静かな互助ネットワークという世界観を維持
- noteを単なるSNS一覧ではなく誌面・活動記録として見せる
- 固定PROJECTS、理念、歴史を自動新着で押し流さない
- YouTubeは大量iframeではなくサムネイルカード
- 既存の静的note・YouTube表示をフォールバックとして残す
- 既存JSON取得処理がある場合は二重取得を避ける

## 10. kumamotoevent.comへの注意

JSON：

```text
https://clubpyramid-sys.github.io/kumamoto-ai-public-data/sites/kumamotoevent.json
```

- ヒーロー、イベント導線、ゲーム、企画ページを壊さない
- 新着情報は主要導線を妨げない場所へ置く
- イベント告知と長文note記事を視覚的に区別
- 動画はiframe大量表示ではなく軽量カード
- 旧トップや別バージョンを誤って上書きしない
- 現在成功している表示がある場合は差分確認後に置換

## 11. 検証

### データ

- JSONがHTTP 200
- `schema_version`あり
- `note_items`が配列
- 有効記事が1件以上
- 重複URLなし
- サムネイルが元JSONからサイト別JSONまで失われていない
- 秘密情報、メールアドレス、ローカルパスなし

### 表示

- 最新記事が先頭
- 表示件数が設計どおり
- 長いタイトルで崩れない
- 画像あり・なしの両方で成立
- PCで2〜3列
- スマートフォンで1列
- 横スクロールなし
- コンソールエラーなし

### 障害時

- JSON URLを壊しても静的カードが残る
- HTTP 404でも空白にならない
- JSON不正でも空白にならない
- 空配列でも静的表示が残る
- 画像失敗でも本文が残る
- JavaScript停止時も最低限の情報が見える

### 既存機能

- ナビゲーション
- フォーム
- SEO
- OGP
- 構造化データ
- 他のJavaScript

を壊していないこと。

## 12. 公開前後の確認順序

公開前：

```text
1. バックアップ
2. 現在のHTML・CSS・JSを調査
3. サイト固有JS・CSSを作成
4. 静的フォールバックを維持
5. 実JSON取得テスト
6. 正常系・異常系テスト
7. PC・スマートフォン確認
8. SHA-256とdiff
```

公開後：

```text
1. GitHub Pagesのサイト別JSONを確認
2. 本番HTMLのJS読み込みを確認
3. NetworkでJSON HTTP 200
4. 最新記事が先頭
5. サムネイル表示
6. コンソールエラー確認
7. JSON障害時の静的フォールバック確認
```

## 13. 熊本AI研究所で確認できた完成状態

```text
GitHub Pages公開JSON：HTTP 200
note_items：10件
thumbnail_url：10/10件で非null
重複URL：0件
秘密情報：0件
トップページ：サムネイル10枚表示
note一覧ページ：サムネイル10枚表示
画像alt：設定済み
コンソールエラー：0件
固定選定記事20件：維持
YouTube・X：未変更
```

代表コミット：

```text
a294ba5e061580fc3c42ec923bc753d6e8348d6a
```

コミットメッセージ：

```text
fix: propagate note thumbnails from account to magazine and site feeds
```

## 14. 実装担当への最終指示

既存サイトを全面的に作り直さないこと。

最初に現在のファイル構成、note・YouTube表示、生成処理、公開用フォルダを調査すること。

サイト別GitHub JSONを読み込み、正常なデータを確認した後だけ新着表示を置換すること。

取得失敗時は既存の静的表示を必ず残すこと。

サムネイル画像の有無だけでカード全体を失敗させないこと。

公開ルートの既存CSS、JavaScript、assetsを不用意に上書きせず、サイト固有プレフィックス付きの新規ファイルを使用すること。

熊本AI研究所で確立した表示・検証ロジックを参考にしつつ、各サイトの世界観と既存導線へ合わせて個別実装すること。

X（Twitter）は今回追加せず、Grok／Hermes Agentを使う別系統として扱うこと。
