from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

import isodate
import requests
from dateutil import parser as date_parser
from yt_dlp import YoutubeDL

from common import best_thumbnail, dedupe_keep_order, strip_html
from http_client import get_or_raise, make_session

API_BASE = "https://www.googleapis.com/youtube/v3"


def _iso_from_upload_date(value: str | None) -> str | None:
    if not value:
        return None
    if re.fullmatch(r"\d{8}", value):
        dt = datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    try:
        dt = date_parser.parse(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return None


def _duration_iso(seconds: int | float | None) -> str | None:
    if seconds is None:
        return None
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    parts = "PT"
    if hours:
        parts += f"{hours}H"
    if minutes:
        parts += f"{minutes}M"
    if secs or parts == "PT":
        parts += f"{secs}S"
    return parts


def _api_get(session: requests.Session, path: str, api_key: str, timeout: int, **params) -> dict:
    params["key"] = api_key
    response = get_or_raise(session, API_BASE + path, timeout, params=params)
    return response.json()


def _resolve_channel_uploads_playlist(source: dict, session, api_key: str, timeout: int) -> tuple[str, dict]:
    if source.get("uploads_playlist_id"):
        return source["uploads_playlist_id"], {}
    params: dict[str, Any] = {"part": "snippet,contentDetails", "maxResults": 1}
    if source.get("channel_id"):
        params["id"] = source["channel_id"]
    elif source.get("handle"):
        params["forHandle"] = str(source["handle"]).lstrip("@")
    else:
        raise RuntimeError("YouTube API利用にはchannel_idまたはhandleが必要です")
    data = _api_get(session, "/channels", api_key, timeout, **params)
    items = data.get("items") or []
    if not items:
        raise RuntimeError("YouTubeチャンネルを解決できませんでした")
    channel = items[0]
    playlist_id = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    if not playlist_id:
        raise RuntimeError("アップロード再生リストIDを取得できませんでした")
    return playlist_id, channel


def _youtube_api(source: dict, http_config: dict, api_key: str) -> dict:
    session = make_session(http_config)
    timeout = int(http_config.get("timeout_seconds", 25))
    max_items = min(50, int(source.get("max_items", 20)))
    channel_meta: dict = {}
    if source.get("type") == "channel":
        playlist_id, channel_meta = _resolve_channel_uploads_playlist(source, session, api_key, timeout)
    elif source.get("type") == "playlist":
        playlist_id = source["playlist_id"]
    else:
        raise ValueError(f"未対応のYouTube source type: {source.get('type')}")

    playlist_data = _api_get(
        session,
        "/playlistItems",
        api_key,
        timeout,
        part="snippet,contentDetails,status",
        playlistId=playlist_id,
        maxResults=max_items,
    )
    playlist_items = playlist_data.get("items") or []
    video_ids = [
        item.get("contentDetails", {}).get("videoId")
        or item.get("snippet", {}).get("resourceId", {}).get("videoId")
        for item in playlist_items
    ]
    video_ids = [v for v in video_ids if v]
    videos_by_id: dict[str, dict] = {}
    for offset in range(0, len(video_ids), 50):
        batch = video_ids[offset:offset + 50]
        data = _api_get(
            session,
            "/videos",
            api_key,
            timeout,
            part="snippet,contentDetails,status",
            id=",".join(batch),
        )
        videos_by_id.update({item["id"]: item for item in data.get("items", [])})

    items: list[dict] = []
    for position, pitem in enumerate(playlist_items):
        psnip = pitem.get("snippet", {})
        video_id = pitem.get("contentDetails", {}).get("videoId") or psnip.get("resourceId", {}).get("videoId")
        video = videos_by_id.get(video_id, {})
        snippet = video.get("snippet", {}) or psnip
        duration = video.get("contentDetails", {}).get("duration")
        try:
            duration_seconds = int(isodate.duration_parse(duration).total_seconds()) if duration else None
        except Exception:
            duration_seconds = None
        title = snippet.get("title") or psnip.get("title") or video_id
        if title in {"Deleted video", "Private video"}:
            continue
        items.append({
            "id": video_id,
            "title": strip_html(title, 300),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "published_at": snippet.get("publishedAt") or pitem.get("contentDetails", {}).get("videoPublishedAt"),
            "description": strip_html(snippet.get("description") or psnip.get("description"), 1000),
            "duration": duration,
            "duration_seconds": duration_seconds,
            "thumbnail_url": best_thumbnail(snippet.get("thumbnails") or psnip.get("thumbnails")),
            "playlist_position": psnip.get("position", position),
            "channel_title": snippet.get("channelTitle") or psnip.get("videoOwnerChannelTitle") or psnip.get("channelTitle"),
            "source_id": source["source_id"],
            "source_type": "youtube_channel" if source.get("type") == "channel" else "youtube_playlist",
        })
    if not items:
        raise RuntimeError("YouTube Data APIから動画を取得できませんでした")
    return _payload(source, items, collector="youtube_data_api_v3", extra={"playlist_id": playlist_id})


def _youtube_yt_dlp(source: dict) -> dict:
    max_items = int(source.get("max_items", 20))
    url = source["url"]
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
        "playlistend": max_items,
        "extract_flat": False,
        "lazy_playlist": False,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
    }
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise RuntimeError("yt-dlpから情報を取得できませんでした")
    entries = info.get("entries") or [info]
    items: list[dict] = []
    for position, entry in enumerate(entries):
        if not entry:
            continue
        video_id = entry.get("id")
        if not video_id:
            continue
        duration_seconds = entry.get("duration")
        timestamp = entry.get("release_timestamp") or entry.get("timestamp")
        published_at = None
        if timestamp:
            published_at = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        else:
            published_at = _iso_from_upload_date(entry.get("upload_date") or entry.get("release_date"))
        thumbnails = entry.get("thumbnails") or []
        thumbnail_url = entry.get("thumbnail")
        if not thumbnail_url and thumbnails:
            thumbnail_url = thumbnails[-1].get("url")
        items.append({
            "id": str(video_id),
            "title": strip_html(entry.get("title") or video_id, 300),
            "url": entry.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}",
            "published_at": published_at,
            "description": strip_html(entry.get("description"), 1000),
            "duration": _duration_iso(duration_seconds),
            "duration_seconds": int(duration_seconds) if duration_seconds is not None else None,
            "thumbnail_url": thumbnail_url,
            "playlist_position": entry.get("playlist_index", position + 1),
            "channel_title": entry.get("channel") or entry.get("uploader"),
            "source_id": source["source_id"],
            "source_type": "youtube_channel" if source.get("type") == "channel" else "youtube_playlist",
        })
    items = dedupe_keep_order(items)[:max_items]
    if not items:
        raise RuntimeError("yt-dlpから公開動画を取得できませんでした")
    return _payload(source, items, collector="yt_dlp")


def _payload(source: dict, items: list[dict], collector: str, extra: dict | None = None) -> dict:
    source_type = "youtube_channel" if source.get("type") == "channel" else "youtube_playlist"
    metadata = {
        "id": source["source_id"],
        "type": source_type,
        "title": source.get("title", source["source_id"]),
        "url": source["url"],
        "collector": collector,
    }
    metadata.update(extra or {})
    return {"schema_version": "1.0", "source": metadata, "items": dedupe_keep_order(items)}


def fetch_youtube(source: dict, http_config: dict) -> dict:
    mode = str(source.get("mode", "auto"))
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if mode in {"auto", "api"} and api_key:
        try:
            return _youtube_api(source, http_config, api_key)
        except Exception:
            if mode == "api":
                raise
    return _youtube_yt_dlp(source)
