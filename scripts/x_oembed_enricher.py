from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

X_SNOWFLAKE_EPOCH_MS = 1288834974657
OEMBED_ENDPOINT = "https://publish.x.com/oembed"
ALLOWED_X_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}


class _PostParagraphParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._inside_post = False
        self._depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "p" and not self._inside_post:
            self._inside_post = True
            self._depth = 1
            return
        if self._inside_post:
            self._depth += 1
            if tag.lower() == "br":
                self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._inside_post and tag.lower() == "br":
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self._inside_post:
            return
        self._depth -= 1
        if tag.lower() == "p" or self._depth <= 0:
            self._inside_post = False
            self._depth = 0

    def handle_data(self, data: str) -> None:
        if self._inside_post:
            self._parts.append(data)

    def text(self) -> str:
        text = "".join(self._parts)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        return text.strip()


def extract_post_text(embed_html: str) -> str:
    parser = _PostParagraphParser()
    parser.feed(embed_html)
    parser.close()
    return parser.text()


def post_id_from_value(raw: dict[str, Any]) -> str:
    post_id = str(raw.get("id") or raw.get("post_id") or raw.get("tweet_id") or "").strip()
    if post_id.isdigit():
        return post_id

    url = str(raw.get("url") or raw.get("post_url") or "").strip()
    match = re.search(r"/status/(\d+)", url)
    return match.group(1) if match else ""


def canonical_post_url(handle: str, post_id: str) -> str:
    return f"https://x.com/{handle}/status/{post_id}"


def handle_from_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in ALLOWED_X_HOSTS:
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 3 or parts[1].lower() != "status" or not parts[2].isdigit():
        return ""
    return parts[0].lstrip("@")


def timestamp_from_snowflake(post_id: str) -> str:
    if not post_id.isdigit():
        raise ValueError("X投稿IDが数字ではありません。")
    milliseconds = (int(post_id) >> 22) + X_SNOWFLAKE_EPOCH_MS
    parsed = datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)
    if parsed > datetime.now(timezone.utc) + timedelta(minutes=15):
        raise ValueError("X投稿IDから復元した日時が未来です。")
    return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_oembed(post_url: str, timeout: int = 30) -> dict[str, Any]:
    query = urlencode(
        {
            "url": post_url,
            "omit_script": "1",
            "hide_thread": "1",
            "dnt": "true",
        }
    )
    request = Request(
        f"{OEMBED_ENDPOINT}?{query}",
        headers={
            "Accept": "application/json",
            "User-Agent": "kumamoto-ai-public-data/1.0",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("X oEmbed応答がJSONオブジェクトではありません。")
    return payload


def enrich_discovered_item(
    raw: Any,
    allowed: dict[str, str],
    fetcher: Callable[[str], dict[str, Any]] = fetch_oembed,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    # Already-normalized records are previous good data. Reuse them without
    # another network request during merge/retention processing.
    if str(raw.get("text") or "").strip() and str(raw.get("published_at") or "").strip():
        return dict(raw)

    post_id = post_id_from_value(raw)
    if not post_id:
        return None

    raw_url = str(raw.get("url") or raw.get("post_url") or "").strip()
    url_handle = handle_from_url(raw_url) if raw_url else ""
    requested_handle = str(
        raw.get("handle") or raw.get("account") or raw.get("username") or url_handle
    ).strip().lstrip("@").lower()
    handle = allowed.get(requested_handle)
    if not handle:
        return None

    if url_handle and url_handle.lower() != handle.lower():
        return None

    post_url = canonical_post_url(handle, post_id)
    payload = fetcher(post_url)
    author_url = str(payload.get("author_url") or "").strip()
    author_handle = handle_from_url(author_url + f"/status/{post_id}") if author_url else ""
    if author_handle and author_handle.lower() != handle.lower():
        return None

    text = extract_post_text(str(payload.get("html") or ""))
    if not text:
        return None

    enriched = dict(raw)
    enriched.update(
        {
            "id": post_id,
            "handle": handle,
            "display_name": str(payload.get("author_name") or handle).strip() or handle,
            "published_at": timestamp_from_snowflake(post_id),
            "text": text,
            "url": post_url,
            "media": [],
            "is_reply": bool(raw.get("is_reply", False)),
            "is_repost": bool(raw.get("is_repost", raw.get("is_retweet", False))),
            "content_source": "x-oembed",
        }
    )
    return enriched


def build_x_search_discovery_prompt(handles: list[str], per_account_limit: int) -> str:
    handle_lines = "\n".join(f"- @{handle}" for handle in handles)
    handle_json = json.dumps(handles, ensure_ascii=False)
    return f"""必ずx_searchツールを使用してください。

X上の次の公開アカウントについて、最新の通常投稿を検索してください。

対象:
{handle_lines}

x_searchの指定:
- allowed_x_handles: {handle_json}
- 各アカウント最大{per_account_limit}件
- 新しい順
- 返信とリポストを除外
- citationで実在を確認できた投稿だけを採用
- narrowing filterを使用した結果がdegraded=trueの場合は成功扱いにしない

重要:
- 投稿本文や投稿日時は推測・翻訳・要約しない
- 最終JSONには本文や日時を入れず、citationで確認した投稿IDとURLだけを返す
- URLは https://x.com/<handle>/status/<numeric-id> 形式に正規化する
- DM、下書き、Cookie、認証情報、ローカルパスを含めない

説明文やMarkdownを付けず、次のJSONオブジェクトだけを返してください。

{{
  "success": true,
  "tool": "x_search",
  "degraded": false,
  "credential_source": "xai-oauth or xai",
  "items": [
    {{
      "id": "numeric post id",
      "handle": "account handle without @",
      "url": "https://x.com/handle/status/id",
      "is_reply": false,
      "is_repost": false
    }}
  ]
}}"""
