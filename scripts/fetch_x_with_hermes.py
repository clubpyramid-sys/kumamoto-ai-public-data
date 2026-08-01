from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "x_sources.json"
INPUT_PATH = ROOT / "runtime" / "x" / "hermes_latest.json"
PUBLIC_FALLBACK_PATH = ROOT / "docs" / "x" / "all_latest.json"
STATUS_PATH = ROOT / "runtime" / "x" / "hermes_fetch_status.json"
JST = timezone(timedelta(hours=9))
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def now_jst_iso() -> str:
    return datetime.now(JST).replace(microsecond=0).isoformat()


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_previous_items() -> list[dict[str, Any]]:
    """Combine transient cache and tracked public LKG; public data is never dropped."""
    combined: list[dict[str, Any]] = []
    for path in (INPUT_PATH, PUBLIC_FALLBACK_PATH):
        payload = load_json(path, {})
        items = payload.get("items") if isinstance(payload, dict) else None
        if isinstance(items, list) and items:
            combined.extend(item for item in items if isinstance(item, dict))
    return combined


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def write_status(status: str, **extra: Any) -> None:
    atomic_write_json(
        STATUS_PATH,
        {
            "status": status,
            "finished_at": now_iso(),
            **extra,
        },
    )


def resolve_hermes() -> str:
    configured = os.getenv("HERMES_BIN", "").strip()
    candidates = [
        configured,
        shutil.which("hermes") or "",
        str(Path.home() / ".local" / "bin" / "hermes"),
        "/opt/homebrew/bin/hermes",
        "/usr/local/bin/hermes",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("Hermes CLIが見つかりません。HERMES_BINまたはPATHを確認してください。")


def extract_json(text: str) -> Any:
    clean = ANSI_RE.sub("", text).strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", clean, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        clean = fenced.group(1).strip()

    decoder = json.JSONDecoder()
    for index, character in enumerate(clean):
        if character not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(clean[index:])
            return value
        except json.JSONDecodeError:
            continue
    raise RuntimeError("Hermes出力からJSONを抽出できませんでした。")


def canonical_handle(value: Any, allowed: dict[str, str]) -> str | None:
    raw = str(value or "").strip().lstrip("@").lower()
    return allowed.get(raw)


def parse_timestamp(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc).replace(microsecond=0)
    if parsed > datetime.now(timezone.utc) + timedelta(minutes=15):
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def normalize_media(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for entry in value:
        if isinstance(entry, str):
            url = entry.strip()
            media_type = "image"
        elif isinstance(entry, dict):
            url = str(entry.get("url") or entry.get("media_url") or "").strip()
            media_type = str(entry.get("type") or entry.get("kind") or "image").strip().lower()
        else:
            continue
        if not url.startswith("https://"):
            continue
        host = (urlparse(url).hostname or "").lower()
        if host not in {"pbs.twimg.com", "video.twimg.com", "abs.twimg.com"}:
            continue
        result.append({"type": media_type or "image", "url": url})
    return result[:4]


def normalize_item(raw: Any, allowed: dict[str, str]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    handle = canonical_handle(raw.get("handle") or raw.get("account") or raw.get("username"), allowed)
    if not handle:
        return None

    post_id = str(raw.get("id") or raw.get("post_id") or raw.get("tweet_id") or "").strip()
    url = str(raw.get("url") or raw.get("post_url") or "").strip()
    if not post_id and "/status/" in url:
        post_id = url.rstrip("/").split("/")[-1].split("?")[0]
    if not post_id.isdigit():
        return None

    expected_url = f"https://x.com/{handle}/status/{post_id}"
    if url:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or host not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
            return None
        if f"/status/{post_id}" not in parsed.path:
            return None
    else:
        url = expected_url

    text = re.sub(r"\s+", " ", str(raw.get("text") or raw.get("content") or "")).strip()
    if not text:
        return None

    published_at = parse_timestamp(raw.get("published_at") or raw.get("created_at") or raw.get("date"))
    if not published_at:
        return None

    is_reply = bool(raw.get("is_reply", False))
    is_repost = bool(raw.get("is_repost", raw.get("is_retweet", False)))
    if is_reply or is_repost:
        return None

    return {
        "id": post_id,
        "handle": handle,
        "display_name": re.sub(
            r"\s+", " ", str(raw.get("display_name") or raw.get("name") or handle)
        ).strip()[:100],
        "published_at": published_at,
        "text": text[:5000],
        "url": url,
        "is_reply": False,
        "is_repost": False,
        "media": normalize_media(raw.get("media") or raw.get("media_urls")),
    }


def normalize_items(raw_items: Any, allowed: dict[str, str]) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        raise RuntimeError("Hermes JSONのitemsが配列ではありません。")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_items:
        item = normalize_item(raw, allowed)
        if not item or item["id"] in seen:
            continue
        seen.add(item["id"])
        result.append(item)
    return sorted(result, key=lambda item: item["published_at"], reverse=True)


def merge_items(
    fresh: list[dict[str, Any]],
    previous: list[dict[str, Any]],
    allowed: dict[str, str],
    per_account_limit: int,
    total_limit: int,
) -> list[dict[str, Any]]:
    combined = normalize_items([*fresh, *previous], allowed)
    counts: Counter[str] = Counter()
    result: list[dict[str, Any]] = []
    for item in combined:
        handle = item["handle"]
        if counts[handle] >= per_account_limit:
            continue
        counts[handle] += 1
        result.append(item)
        if len(result) >= total_limit:
            break
    return result


def resolve_x_refresh(
    fresh_items: list[dict[str, Any]],
    previous_items: list[dict[str, Any]],
    allowed: dict[str, str],
    accounts: list[str],
    per_account_limit: int,
    total_limit: int,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Merge per-account results while preserving last-known-good records."""
    fresh_counts = Counter(item["handle"] for item in fresh_items)
    previous_normalized = merge_items(
        [], previous_items, allowed, per_account_limit, total_limit
    )
    previous_counts = Counter(item["handle"] for item in previous_normalized)
    missing = [handle for handle in accounts if fresh_counts[handle] == 0]
    retained = [handle for handle in missing if previous_counts[handle] > 0]
    if not fresh_items:
        detail = "全アカウントの取得に失敗しました"
        if retained:
            detail += "。公開済みの前回値を維持します"
        raise RuntimeError(detail)
    merged = merge_items(
        fresh_items, previous_items, allowed, per_account_limit, total_limit
    )
    if not merged:
        raise RuntimeError("公開可能なX投稿が0件のため更新を中止しました")
    if len({item["id"] for item in merged}) != len(merged):
        raise RuntimeError("X投稿IDの重複を検出したため更新を中止しました")
    return merged, missing, retained


def build_prompt(handles: list[str], per_account_limit: int) -> str:
    handle_lines = "\n".join(f"- @{handle}" for handle in handles)
    return f"""Xのライブ検索を使用し、次の公開アカウントについて最新投稿を取得してください。

対象:
{handle_lines}

取得条件:
- 各アカウント最大{per_account_limit}件
- 新しい順
- 返信とリポストを除外
- 投稿ID、正確な投稿URL、公開日時、本文、表示名、公開メディアURLを含める
- 検索で実在を確認できた投稿だけを返す
- 推測、創作、要約、投稿本文の書き換えをしない
- DM、下書き、Cookie、認証情報、ローカルパスを含めない
- 取得できないアカウントがあれば、そのアカウントを省略せずエラーとして扱う

出力は説明文やMarkdownを付けず、次の形のJSONオブジェクトだけにしてください。

{{
  "generated_at": "ISO 8601 timestamp",
  "items": [
    {{
      "id": "numeric post id",
      "handle": "account handle without @",
      "display_name": "display name",
      "published_at": "ISO 8601 timestamp",
      "text": "exact public post text",
      "url": "https://x.com/handle/status/id",
      "is_reply": false,
      "is_repost": false,
      "media": [
        {{"type": "image or video", "url": "https://..."}}
      ]
    }}
  ]
}}"""


def run_hermes(prompt: str) -> str:
    hermes = resolve_hermes()
    provider = os.getenv("GROK_PROVIDER", "xai-oauth").strip() or "xai-oauth"
    model = os.getenv("GROK_MODEL", "grok-build-0.1").strip() or "grok-build-0.1"
    timeout = int(os.getenv("HERMES_TIMEOUT_SECONDS", "900"))
    command = [hermes, "-z", prompt, "--provider", provider, "--model", model]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env={**os.environ, "HOME": str(Path.home())},
    )
    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"Hermes実行失敗（exit {completed.returncode}）: {error[-1000:]}")
    return completed.stdout


def main() -> int:
    config = load_json(CONFIG_PATH, {})
    accounts = [
        str(account.get("handle") or "").strip().lstrip("@")
        for account in config.get("accounts", [])
        if account.get("enabled", True) and account.get("handle")
    ]
    if not accounts:
        raise RuntimeError("有効なXアカウント設定がありません。")

    allowed = {handle.lower(): handle for handle in accounts}
    per_account_limit = int(config.get("max_items_per_account", 20))
    total_limit = int(config.get("max_items", per_account_limit * len(accounts)))
    previous_items = load_previous_items()

    raw_output = run_hermes(build_prompt(accounts, per_account_limit))
    response = extract_json(raw_output)
    if not isinstance(response, dict):
        raise RuntimeError("Hermes出力のルートがJSONオブジェクトではありません。")

    fresh_items = normalize_items(response.get("items"), allowed)
    previous_normalized = merge_items([], previous_items, allowed, per_account_limit, total_limit)
    merged, missing, retained = resolve_x_refresh(
        fresh_items,
        previous_items,
        allowed,
        accounts,
        per_account_limit,
        total_limit,
    )
    changed = merged != previous_normalized

    if changed:
        atomic_write_json(
            INPUT_PATH,
            {
                "schema_version": "1.0",
                "generated_at": now_jst_iso(),
                "collection_method": "Hermes Agent with Grok",
                "items": merged,
            },
        )

    write_status(
        "success_partial" if missing else "success",
        changed=changed,
        missing_accounts=missing,
        retained_accounts=retained,
        fresh_item_count=len(fresh_items),
        merged_item_count=len(merged),
        per_account=dict(Counter(item["handle"] for item in merged)),
        newest_post=merged[0] if merged else None,
    )
    print("=== Hermes X取得結果 ===")
    print(f"新規取得候補: {len(fresh_items)}件")
    print(f"統合後: {len(merged)}件")
    print(f"入力JSON更新: {'yes' if changed else 'no'}")
    if missing:
        print("一部アカウントは前回値を保持: " + ", ".join(f"@{handle}" for handle in missing))
    for handle in accounts:
        print(f"- @{handle}: {sum(1 for item in merged if item['handle'] == handle)}件")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        write_status("failed", error=str(exc))
        print(f"X取得失敗: {exc}", file=sys.stderr)
        raise SystemExit(1)
