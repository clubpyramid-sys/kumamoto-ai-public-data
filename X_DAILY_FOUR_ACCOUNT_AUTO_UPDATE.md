# 追加4アカウント X日次更新

## 対象

- `@SEA_PYRAMID`
- `@CLUB_PYRAMID`
- `@STARLIGHT_CAFE_`
- `@kumamotodeai`

## 実行時刻

毎日 05:00（Macのローカル時刻）。

既存の熊本秘密クラブ4アカウント更新（00:00・06:00・15:00・21:00）とは独立したLaunchAgentで実行する。

## 処理経路

1. `launchd/com.clubpyramid.kumamoto-ai-public-data.x-feed-daily.plist.template`
2. `bin/run_x_daily_update.sh`
3. `scripts/run_fetch_x_daily_with_hermes.py`
4. Hermes Agentの `x_search`
5. X公式oEmbedで本文と表示名を検証
6. X Snowflake IDから投稿日時を復元
7. `runtime/x/hermes_daily_latest.json` に保存
8. `scripts/publish_x_daily.py` で検証・commit・push
9. GitHub Pagesの `x/daily_latest.json` として公開

## 公開URL

`https://clubpyramid-sys.github.io/kumamoto-ai-public-data/x/daily_latest.json`

## 登録

```bash
cd "$HOME/AI_Agent_Runtime/kumamoto-ai-public-data"
zsh "commands/11_X投稿_追加4アカウント日次更新を登録.command"
```

登録時に初回更新を1回実行する。以後は毎日05:00に実行する。

## 状態確認

```bash
cat runtime/x/hermes_daily_fetch_status.json
cat runtime/x/hermes_daily_publish_status.json

tail -n 100 logs/x_feed_daily_launchd.out.log
tail -n 100 logs/x_feed_daily_launchd.err.log
```

## 安全設計

- 既存の `runtime/x/hermes_latest.json` と `docs/x/all_latest.json` は変更しない。
- 既存KSC専用4列ページへ追加4アカウントを混在させない。
- 4アカウント中3アカウント以上から投稿を取得できれば処理を継続する。
- 投稿が0件のアカウントは失敗扱いにせず、次回以降も毎日継続して確認する。
- 前回データがあるアカウントを一時的に取得できなかった場合は、前回の正常投稿を保持する。
- 2アカウント以上が同時に0件の場合は広範な検索障害の可能性があるため、安全停止する。
- Grokが返した本文や日時は信用せず、本文はX公式oEmbed、日時は投稿IDから確定する。
- 公開対象は `docs/x/daily_latest.json` だけをstage・commitする。
- 既存X更新と同じロックを使い、同時実行を防止する。
