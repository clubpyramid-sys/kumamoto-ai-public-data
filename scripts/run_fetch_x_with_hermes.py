from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import fetch_x_with_hermes
from hermes_response_parser import extract_hermes_payload


def run_hermes_with_saved_config(prompt: str) -> str:
    """Run Hermes with its saved Desktop/CLI model configuration.

    Explicit provider/model flags are intentionally omitted by default because
    Hermes gives CLI flags priority over the model selected in `hermes model`
    or Hermes Desktop. Optional overrides remain available for diagnostics.
    """

    hermes = fetch_x_with_hermes.resolve_hermes()
    timeout = int(os.getenv("HERMES_TIMEOUT_SECONDS", "900"))
    provider_override = os.getenv("HERMES_PROVIDER_OVERRIDE", "").strip()
    model_override = os.getenv("HERMES_MODEL_OVERRIDE", "").strip()

    command = [hermes, "-z", prompt]
    if provider_override:
        command.extend(["--provider", provider_override])
    if model_override:
        command.extend(["--model", model_override])

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


def main() -> int:
    fetch_x_with_hermes.extract_json = extract_hermes_payload
    fetch_x_with_hermes.run_hermes = run_hermes_with_saved_config
    return fetch_x_with_hermes.main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        fetch_x_with_hermes.write_status("failed", error=str(exc))
        print(f"X取得失敗: {exc}", file=sys.stderr)
        raise SystemExit(1)
