from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import feedparser
from bs4 import BeautifulSoup
from jsonschema import Draft202012Validator, FormatChecker

from common import append_jsonl, atomic_write_json, canonical_json, load_json
from http_client import get_or_raise, make_session


ROOT = Path(__file__).resolve().parents[1]
RSS_URL = "https://kumamotosecretclub.jp/blog2/rss.xml"
SITE_URL = "https://kumamotosecretclub.jp/"
BLOG_URL = "https://kumamotosecretclub.jp/blog2/"
DEFAULT_OUTPUT = ROOT / "docs" / "events" / "kumamoto_secret_club_current.json"
DEFAULT_SCHEMA = ROOT / "schemas" / "kumamoto_secret_club_current.schema.json"
DEFAULT_LOG_DIR = ROOT / "logs" / "kumamoto_secret_club_events"
JST = ZoneInfo("Asia/Tokyo")
ALLOWED_STATUSES = {"scheduled", "accepting", "updated", "cancelled", "finished", "unknown"}
PUBLIC_STATUSES = ALLOWED_STATUSES - {"finished", "unknown"}

SOURCE = {
    "name": "熊本秘密クラブ 開催情報BLOG",
    "rss_url": RSS_URL,
    "site_url": SITE_URL,
    "blog_url": BLOG_URL,
}

REPORT_WORDS = re.compile(r"(?:開催レポート|活動報告|参加レポート|振り返り|終了しました|開催しました|御礼|お礼)")
CANCEL_WORDS = re.compile(r"(?:中止|延期|取り止め|取りやめ)")
UPDATE_WORDS = re.compile(r"(?:変更|訂正|更新|時間変更|会場変更|直前のお知らせ)")
ACCEPTING_WORDS = re.compile(r"(?:受付中|募集中|参加者募集|面談会|予約受付|申込受付)")
TIME_PATTERN = re.compile(r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)(?!\d)")
DATE_PATTERN = re.compile(r"(?:(20\d{2})年)?\s*(1[0-2]|0?[1-9])月\s*(3[01]|[12]?\d)日")
URL_DATE_PATTERN = re.compile(r"/(20\d{2})-(\d{2})-(\d{2})(?:[./_-]|$)")

FORBIDDEN_CONTENT = re.compile(
    r"(?:セフレ|出会い系|援助交際|パパ活|乱交|ハプニングバー|売春|買春|露骨な性描写)",
    re.IGNORECASE,
)
PII_PATTERNS = (
    re.compile(r"https?://(?:maps\.(?:google|apple)\.[^\s]+|goo\.gl/maps/[^\s]+)", re.IGNORECASE),
    re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
    re.compile(r"(?<!\d)(?:0\d{1,4}[-ー−]?\d{1,4}[-ー−]?\d{3,4})(?!\d)"),
    re.compile(r"(?:LINE|ライン)\s*(?:ID|ＩＤ|id)?\s*[:：]?\s*[@A-Za-z0-9_.-]{4,}", re.IGNORECASE),
    re.compile(r"(?:部屋|ルーム|ROOM)\s*(?:番号|No\.?|NO\.?|#)?\s*[:：]?\s*[A-Za-z0-9０-９-]{1,8}", re.IGNORECASE),
    re.compile(r"(?:集合場所|予約名義)\s*[:：]\s*[^。\n]{1,80}"),
    re.compile(r"熊本県[^。\n]{0,100}(?:\d{1,4}[-ー−]\d{1,4}|\d{1,4}番地)[^。\n]{0,30}"),
    re.compile(r"[一-龯々]{2,5}(?:様|さん|氏)(?!々)"),
)


def now_jst() -> datetime:
    return datetime.now(JST).replace(microsecond=0)


def iso_datetime(value: Any) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(JST).replace(microsecond=0).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def plain_text(value: Any, max_chars: int = 260) -> str:
    soup = BeautifulSoup(str(value or ""), "html.parser")
    for node in soup(["script", "style", "iframe", "object", "embed", "form"]):
        node.decompose()
    text = html.unescape(" ".join(soup.stripped_strings))
    text = re.sub(r"https?://\S+", "", text)
    for pattern in PII_PATTERNS:
        text = pattern.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" -・、。")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def safe_article_url(*values: Any) -> str | None:
    for value in values:
        if not isinstance(value, str):
            continue
        candidate = html.unescape(value).strip()
        try:
            parsed = urlparse(candidate)
        except ValueError:
            continue
        if (
            parsed.scheme == "https"
            and (parsed.hostname or "").lower() == "kumamotosecretclub.jp"
            and parsed.path.startswith("/blog2/")
            and parsed.path != "/blog2/"
            and not parsed.username
            and not parsed.password
        ):
            return candidate
    return None


def extract_event_date(text: str, url: str, today: date) -> date | None:
    match = DATE_PATTERN.search(text)
    if match:
        year = int(match.group(1)) if match.group(1) else today.year
        month, day = int(match.group(2)), int(match.group(3))
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if not match.group(1) and candidate < today and (today - candidate).days > 180:
            try:
                candidate = candidate.replace(year=today.year + 1)
            except ValueError:
                return None
        return candidate
    match = URL_DATE_PATTERN.search(url)
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def extract_event_time(text: str) -> str | None:
    match = TIME_PATTERN.search(text)
    return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}" if match else None


def generalize_area(text: str) -> str | None:
    areas = (
        (re.compile(r"西銀座"), "西銀座通り周辺"),
        (re.compile(r"(?:下通|新市街)"), "下通周辺"),
        (re.compile(r"上通"), "上通周辺"),
        (re.compile(r"(?:熊本インター|熊本市郊外|郊外)"), "熊本市郊外"),
        (re.compile(r"(?:熊本市中心|中心街|市街地)"), "熊本市中心部"),
        (re.compile(r"熊本市内"), "熊本市内"),
    )
    for pattern, label in areas:
        if pattern.search(text):
            return label
    return None


def classify(text: str, event_date: date | None, today: date) -> tuple[str, str | None]:
    if FORBIDDEN_CONTENT.search(text):
        return "unknown", "inappropriate_content"
    if REPORT_WORDS.search(text):
        return "finished", "report_or_finished"
    if not event_date:
        return "unknown", "date_unknown"
    if event_date < today:
        return "finished", "past_event"
    if CANCEL_WORDS.search(text):
        return "cancelled", None
    if UPDATE_WORDS.search(text):
        return "updated", None
    if ACCEPTING_WORDS.search(text):
        return "accepting", None
    return "scheduled", None


def normalize_entry(entry: Any, today: date) -> tuple[dict[str, Any] | None, str | None]:
    title = plain_text(entry.get("title"), 120)
    raw_summary = entry.get("summary") or entry.get("description") or ""
    combined_raw = f"{entry.get('title') or ''} {raw_summary}"
    url = safe_article_url(entry.get("link"), entry.get("id"), entry.get("guid"))
    if not title:
        return None, "missing_title"
    if not url:
        return None, "invalid_article_url"
    if FORBIDDEN_CONTENT.search(combined_raw):
        return None, "inappropriate_content"
    event_date = extract_event_date(f"{title} {plain_text(raw_summary, 1000)}", url, today)
    status, reason = classify(combined_raw, event_date, today)
    if status not in PUBLIC_STATUSES:
        return None, reason or status
    summary = plain_text(raw_summary, 260)
    item = {
        "title": title,
        "published_at": iso_datetime(entry.get("published") or entry.get("pubDate")),
        "updated_at": iso_datetime(entry.get("updated")),
        "event_date": event_date.isoformat() if event_date else None,
        "event_time": extract_event_time(f"{title} {summary}"),
        "area": generalize_area(f"{title} {summary}"),
        "summary": summary,
        "status": status,
        "url": url,
        "source_type": "rss",
    }
    return item, None


def validate_payload(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["payload must be an object"]
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if payload.get("source") != SOURCE:
        errors.append("source does not match the approved source")
    try:
        datetime.fromisoformat(str(payload.get("generated_at")))
    except ValueError:
        errors.append("generated_at is not an ISO datetime")
    if payload.get("status") not in {"ok", "no_current_event"}:
        errors.append("invalid top-level status")
    current = payload.get("current_event")
    recent = payload.get("recent_items")
    if not isinstance(recent, list) or len(recent) > 5:
        errors.append("recent_items must be an array with at most 5 items")
        recent = []
    if payload.get("status") == "ok" and not isinstance(current, dict):
        errors.append("status ok requires current_event")
    if payload.get("status") == "no_current_event" and (current is not None or recent):
        errors.append("no_current_event requires null current_event and empty recent_items")
    for index, item in enumerate(([current] if isinstance(current, dict) else []) + recent):
        prefix = f"item[{index}]"
        required = {"title", "published_at", "updated_at", "event_date", "event_time", "area", "summary", "status", "url", "source_type"}
        if not required.issubset(item):
            errors.append(f"{prefix} is missing fields")
            continue
        if not item.get("title") or len(item["title"]) > 120:
            errors.append(f"{prefix}.title is invalid")
        if not isinstance(item.get("summary"), str) or len(item["summary"]) > 260:
            errors.append(f"{prefix}.summary is invalid")
        if item.get("status") not in PUBLIC_STATUSES:
            errors.append(f"{prefix}.status is invalid")
        if safe_article_url(item.get("url")) != item.get("url"):
            errors.append(f"{prefix}.url is invalid")
        if item.get("source_type") != "rss":
            errors.append(f"{prefix}.source_type is invalid")
        raw = json.dumps(item, ensure_ascii=False)
        if FORBIDDEN_CONTENT.search(raw) or any(pattern.search(raw) for pattern in PII_PATTERNS):
            errors.append(f"{prefix} contains prohibited content")
    return errors


def build_payload(feed_content: bytes, generated_at: datetime | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    parsed = feedparser.parse(feed_content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"RSS parse failed: {parsed.bozo_exception}")
    today = (generated_at or now_jst()).astimezone(JST).date()
    accepted: list[dict[str, Any]] = []
    excluded: Counter[str] = Counter()
    seen_urls: set[str] = set()
    for entry in parsed.entries:
        item, reason = normalize_entry(entry, today)
        if not item:
            excluded[reason or "unknown"] += 1
            continue
        if item["url"] in seen_urls:
            excluded["duplicate_url"] += 1
            continue
        seen_urls.add(item["url"])
        accepted.append(item)
    accepted.sort(key=lambda item: (item["event_date"], item["published_at"] or "", item["url"]))
    recent = accepted[:5]
    stamp = (generated_at or now_jst()).astimezone(JST).replace(microsecond=0).isoformat()
    payload = {
        "schema_version": 1,
        "source": SOURCE,
        "generated_at": stamp,
        "status": "ok" if recent else "no_current_event",
        "current_event": recent[0] if recent else None,
        "recent_items": recent,
    }
    diagnostics = {
        "fetched_items": len(parsed.entries),
        "current_candidates": len(recent),
        "excluded_items": sum(excluded.values()),
        "excluded_reasons": dict(sorted(excluded.items())),
    }
    return payload, diagnostics


def semantic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": payload.get("source"),
        "status": payload.get("status"),
        "current_event": payload.get("current_event"),
        "recent_items": payload.get("recent_items"),
    }


def run(
    rss_url: str,
    output: Path,
    schema_path: Path,
    log_dir: Path,
    timeout: int = 15,
    session: Any = None,
) -> tuple[bool, dict[str, Any]]:
    started = now_jst()
    log_record: dict[str, Any] = {
        "executed_at": started.isoformat(),
        "rss_url": rss_url,
        "fetch_result": "error",
        "http_status": None,
        "fetched_items": 0,
        "current_candidates": 0,
        "excluded_items": 0,
        "excluded_reasons": {},
        "schema_validation": "not_run",
        "changed": False,
        "github_push": "not_attempted",
        "error": None,
    }
    log_path = log_dir / f"{started:%Y-%m}.jsonl"
    try:
        if not schema_path.is_file():
            raise FileNotFoundError(f"schema not found: {schema_path}")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        client = session or make_session({
            "retries": 3,
            "user_agent": "KumamotoEventFeedBot/1.0 (+https://clubpyramid-sys.github.io/kumamoto-ai-public-data/)",
        })
        response = get_or_raise(client, rss_url, timeout)
        log_record["http_status"] = getattr(response, "status_code", 200)
        payload, diagnostics = build_payload(response.content, started)
        log_record.update(diagnostics)
        errors = validate_payload(payload)
        if errors:
            raise ValueError("Safety validation failed: " + "; ".join(errors))
        schema_errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload),
            key=lambda error: list(error.absolute_path),
        )
        if schema_errors:
            messages = [f"{'/'.join(map(str, error.absolute_path)) or '$'}: {error.message}" for error in schema_errors]
            raise ValueError("JSON Schema validation failed: " + "; ".join(messages))
        log_record["schema_validation"] = "passed"
        existing = load_json(output, {})
        changed = canonical_json(semantic_payload(payload)) != canonical_json(semantic_payload(existing))
        if changed:
            atomic_write_json(output, payload)
        log_record.update({"fetch_result": "success", "changed": changed})
        append_jsonl(log_path, log_record)
        return changed, log_record
    except Exception as exc:
        log_record["error"] = f"{type(exc).__name__}: {exc}"[:1000]
        append_jsonl(log_path, log_record)
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="熊本秘密クラブの現在開催情報RSSを安全な公開JSONへ変換します。")
    parser.add_argument("--rss-url", default=RSS_URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--timeout", type=int, default=15)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        changed, record = run(args.rss_url, args.output, args.schema, args.log_dir, args.timeout)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"changed": changed, **record}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
