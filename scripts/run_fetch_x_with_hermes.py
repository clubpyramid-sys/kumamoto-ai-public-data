from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import fetch_x_with_hermes
from hermes_response_parser import extract_hermes_payload
from x_oembed_enricher import build_x_search_discovery_prompt, enrich_discovered_item

_ORIGINAL_NORMALIZE_ITEM = fetch_x_with_hermes.normalize_item


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


def normalize_item_with_oembed(
    raw: Any,
    allowed: dict[str, str],
) -> dict[str, Any] | None:
    try:
        enriched = enrich_discovered_item(raw, allowed)
    except Exception as exc:
        post_id = ""
        if isinstance(raw, dict):
            post_id = str(raw.get("id") or raw.get("post_id") or raw.get("tweet_id") or "")
        print(
            f"X oEmbed取得をスキップ: id={post_id or 'unknown'} "
            f"error={type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return None
    if enriched is None:
        return None
    return _ORIGINAL_NORMALIZE_ITEM(enriched, allowed)


def main() -> int:
    fetch_x_with_hermes.extract_json = extract_verified_x_search_payload
    fetch_x_with_hermes.run_hermes = run_hermes_with_saved_config
    fetch_x_with_hermes.build_prompt = build_x_search_discovery_prompt
    fetch_x_with_hermes.normalize_item = normalize_item_with_oembed
    return fetch_x_with_hermes.main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        fetch_x_with_hermes.write_status("failed", error=str(exc))
        print(f"X取得失敗: {exc}", file=sys.stderr)
        raise SystemExit(1)
