from __future__ import annotations

import json
import re
from typing import Any

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
TOKEN_RE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._~+/=-]+|"
    r"(?:xai|sk|ghp|github_pat)_[A-Za-z0-9._-]{12,}|"
    r"access[_-]?token\s*[:=]\s*[^\s,}\]]+)"
)
LOCAL_PATH_RE = re.compile(r"/(?:Users|Volumes)/[^\s,}\]]+")


def _json_values(text: str) -> list[Any]:
    clean = ANSI_RE.sub("", text).strip()
    values: list[Any] = []

    for match in re.finditer(r"```(?:json)?\s*(.*?)```", clean, flags=re.IGNORECASE | re.DOTALL):
        block = match.group(1).strip()
        try:
            values.append(json.loads(block))
        except json.JSONDecodeError:
            pass

    decoder = json.JSONDecoder()
    index = 0
    while index < len(clean):
        if clean[index] not in "[{":
            index += 1
            continue
        try:
            value, length = decoder.raw_decode(clean[index:])
        except json.JSONDecodeError:
            index += 1
            continue
        values.append(value)
        index += max(length, 1)

    try:
        values.append(json.loads(clean))
    except json.JSONDecodeError:
        pass

    return values


def _unwrap_json_string(value: Any) -> Any:
    current = value
    for _ in range(4):
        if not isinstance(current, str):
            break
        text = current.strip()
        if not text or text[0] not in "[{\"":
            break
        try:
            current = json.loads(text)
        except json.JSONDecodeError:
            break
    return current


def _looks_like_post(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    has_id = any(value.get(key) for key in ("id", "post_id", "tweet_id"))
    has_handle = any(value.get(key) for key in ("handle", "account", "username"))
    has_text = any(value.get(key) for key in ("text", "content"))
    return bool(has_id and has_handle and has_text)


def _flatten_account_groups(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    items: list[dict[str, Any]] = []
    found_group = False
    for group in value:
        if not isinstance(group, dict):
            continue
        group_items = group.get("items") or group.get("posts") or group.get("tweets")
        if not isinstance(group_items, list):
            continue
        found_group = True
        handle = group.get("handle") or group.get("account") or group.get("username")
        display_name = group.get("display_name") or group.get("name")
        for raw in group_items:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            if handle and not any(item.get(key) for key in ("handle", "account", "username")):
                item["handle"] = handle
            if display_name and not any(item.get(key) for key in ("display_name", "name")):
                item["display_name"] = display_name
            items.append(item)
    return items if found_group else None


def _to_payload(value: Any) -> dict[str, Any] | None:
    value = _unwrap_json_string(value)

    if isinstance(value, list):
        if all(isinstance(item, dict) for item in value):
            if any(_looks_like_post(item) for item in value):
                return {"items": value}
            grouped = _flatten_account_groups(value)
            if grouped is not None:
                return {"items": grouped}
        return None

    if not isinstance(value, dict):
        return None

    for key in ("items", "posts", "tweets", "results"):
        candidate = value.get(key)
        if isinstance(candidate, list):
            if key == "items" and any(_looks_like_post(item) for item in candidate if isinstance(item, dict)):
                return {**value, "items": candidate}
            grouped = _flatten_account_groups(candidate)
            if grouped is not None:
                return {**value, "items": grouped}
            if all(isinstance(item, dict) for item in candidate):
                return {**value, "items": candidate}

    accounts = value.get("accounts")
    grouped = _flatten_account_groups(accounts)
    if grouped is not None:
        return {**value, "items": grouped}

    mapped_items: list[dict[str, Any]] = []
    found_mapping = False
    for handle, candidate in value.items():
        if handle in {"generated_at", "updated_at", "schema_version", "status", "metadata"}:
            continue
        if not isinstance(candidate, list):
            continue
        if not all(isinstance(item, dict) for item in candidate):
            continue
        found_mapping = True
        for raw in candidate:
            item = dict(raw)
            if not any(item.get(key) for key in ("handle", "account", "username")):
                item["handle"] = str(handle).lstrip("@")
            mapped_items.append(item)
    if found_mapping:
        return {**value, "items": mapped_items}

    for key in (
        "data",
        "result",
        "response",
        "output",
        "content",
        "message",
        "final",
        "answer",
        "text",
    ):
        if key not in value:
            continue
        payload = _to_payload(value[key])
        if payload is not None:
            for timestamp_key in ("generated_at", "updated_at"):
                if timestamp_key in value and timestamp_key not in payload:
                    payload[timestamp_key] = value[timestamp_key]
            return payload

    for candidate in value.values():
        payload = _to_payload(candidate)
        if payload is not None:
            return payload

    return None


def _safe_text(value: Any, limit: int = 700) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            text = str(value)
    text = ANSI_RE.sub("", text)
    text = TOKEN_RE.sub("[credential removed]", text)
    text = LOCAL_PATH_RE.sub("[local path removed]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _provider_error(value: Any) -> tuple[str, str] | None:
    value = _unwrap_json_string(value)
    if not isinstance(value, dict) or "error" not in value:
        return None

    code = value.get("code") or value.get("status") or value.get("status_code") or "unknown"
    error = value.get("error")
    if isinstance(error, dict):
        nested_code = error.get("code") or error.get("type")
        if nested_code and str(code) == "unknown":
            code = nested_code
        message = (
            error.get("message")
            or error.get("detail")
            or error.get("error")
            or error
        )
    else:
        message = error

    return _safe_text(code, 120), _safe_text(message)


def extract_hermes_payload(text: str) -> dict[str, Any]:
    candidates = _json_values(text)
    provider_errors: list[tuple[str, str]] = []

    for candidate in reversed(candidates):
        payload = _to_payload(candidate)
        if payload is not None and isinstance(payload.get("items"), list):
            return payload
        provider_error = _provider_error(candidate)
        if provider_error is not None:
            provider_errors.append(provider_error)

    if provider_errors:
        code, message = provider_errors[0]
        raise RuntimeError(f"Hermes provider error [{code}]: {message}")

    shapes: list[str] = []
    for candidate in candidates[-6:]:
        candidate = _unwrap_json_string(candidate)
        if isinstance(candidate, dict):
            shapes.append("dict:" + ",".join(sorted(map(str, candidate.keys()))[:12]))
        elif isinstance(candidate, list):
            shapes.append(f"list:{len(candidate)}")
        else:
            shapes.append(type(candidate).__name__)
    detail = " / ".join(shapes) if shapes else "JSON候補なし"
    raise RuntimeError(f"Hermes出力に投稿配列を見つけられませんでした（{detail}）")
