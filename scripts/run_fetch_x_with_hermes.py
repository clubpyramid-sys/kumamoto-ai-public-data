from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import fetch_x_with_hermes
from hermes_response_parser import extract_hermes_payload
from x_oembed_enricher import (
    build_x_search_discovery_prompt,
    enrich_discovered_item,
    handle_from_url,
    post_id_from_value,
)

_ORIGINAL_NORMALIZE_ITEMS = fetch_x_with_hermes.normalize_items
_DISCOVERY_PASS_PENDING = True


def run_hermes_with_saved_config(prompt: str) -> str:
    """Run Hermes with saved model config and the X Search toolset only.

    Explicit provider/model flags are intentionally omitted by default because
    Hermes gives CLI flags priority over the model selected in `hermes model`
    or Hermes Desktop. Optional overrides remain available for diagnostics.
    """

    hermes = fetch_x_with_hermes.resolve_hermes()
    timeout = int(os.getenv("HERMES_TIMEOUT_SECONDS", "900"))
    provider_override = os.getenv("HERMES_PROVIDER_OVERRIDE", "").strip()
    model_override = os.getenv("HERMES_MODEL_OVERRIDE", "").strip()

    command = [hermes, "--ignore-rules", "-t", "x_search"]
    if provider_override:
        command.extend(["--provider", provider_override])
    if model_override:
        command.extend(["--model", model_override])
    command.extend(["-z", prompt])

    completed = subprocess.run(
        command,
        cwd=fetch_x_with_hermes.ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env={**os.environ, "HOME": str(Path.home())},
    )
    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(
            f"Hermes実行失敗（exit {completed.returncode}）: {error[-1000:]}"
        )
    return completed.stdout


def extract_verified_x_search_payload(text: str) -> dict[str, Any]:
    payload = extract_hermes_payload(text)
    if payload.get("tool") != "x_search":
        raise RuntimeError("Hermesがx_searchを使用したことを確認できませんでした。")
    if payload.get("degraded") is not False:
        raise RuntimeError("x_searchがcitationなしのdegraded結果を返しました。")
    credential_source = str(payload.get("credential_source") or "").strip()
    if credential_source not in {"xai-oauth", "xai"}:
        raise RuntimeError("x_searchの認証経路を確認できませんでした。")
    return payload


def _raw_handle(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    direct = str(raw.get("handle") or raw.get("account") or raw.get("username") or "")
    if direct.strip():
        return direct.strip().lstrip("@").lower()
    url = str(raw.get("url") or raw.get("post_url") or "").strip()
    return handle_from_url(url).lower() if url else ""


def normalize_discovery_items_with_oembed(
    raw_items: Any,
    allowed: dict[str, str],
) -> list[dict[str, Any]]:
    global _DISCOVERY_PASS_PENDING

    # The base pipeline calls normalize_items three times. Only the first call
    # contains untrusted Grok discovery output. Later calls contain already
    # normalized fresh/previous records and must not trigger network requests.
    if not _DISCOVERY_PASS_PENDING:
        return _ORIGINAL_NORMALIZE_ITEMS(raw_items, allowed)
    _DISCOVERY_PASS_PENDING = False

    if not isinstance(raw_items, list):
        return _ORIGINAL_NORMALIZE_ITEMS(raw_items, allowed)

    previous_payload = fetch_x_with_hermes.load_json(fetch_x_with_hermes.INPUT_PATH, {})
    previous_raw = (
        previous_payload.get("items", []) if isinstance(previous_payload, dict) else []
    )
    previous_items = _ORIGINAL_NORMALIZE_ITEMS(previous_raw, allowed)
    previous_by_id = {item["id"]: item for item in previous_items}

    enriched_items: list[dict[str, Any]] = []
    for raw in raw_items:
        post_id = post_id_from_value(raw) if isinstance(raw, dict) else ""
        raw_handle = _raw_handle(raw)
        previous = previous_by_id.get(post_id)
        if (
            previous is not None
            and raw_handle
            and previous.get("handle", "").lower() == raw_handle
        ):
            enriched_items.append(previous)
            continue

        # Never trust model-supplied text or timestamps. Force the exact public
        # post body through X's official oEmbed endpoint and derive time from ID.
        discovery = dict(raw) if isinstance(raw, dict) else raw
        if isinstance(discovery, dict):
            for key in (
                "text",
                "content",
                "published_at",
                "created_at",
                "date",
                "display_name",
                "name",
                "media",
                "media_urls",
            ):
                discovery.pop(key, None)

        try:
            enriched = enrich_discovered_item(discovery, allowed)
        except Exception as exc:
            print(
                f"X oEmbed取得をスキップ: id={post_id or 'unknown'} "
                f"error={type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            continue
        if enriched is not None:
            enriched_items.append(enriched)

    return _ORIGINAL_NORMALIZE_ITEMS(enriched_items, allowed)


def main() -> int:
    global _DISCOVERY_PASS_PENDING
    _DISCOVERY_PASS_PENDING = True
    fetch_x_with_hermes.extract_json = extract_verified_x_search_payload
    fetch_x_with_hermes.run_hermes = run_hermes_with_saved_config
    fetch_x_with_hermes.build_prompt = build_x_search_discovery_prompt
    fetch_x_with_hermes.normalize_items = normalize_discovery_items_with_oembed
    return fetch_x_with_hermes.main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        fetch_x_with_hermes.write_status("failed", error=str(exc))
        print(f"X取得失敗: {exc}", file=sys.stderr)
        raise SystemExit(1)
