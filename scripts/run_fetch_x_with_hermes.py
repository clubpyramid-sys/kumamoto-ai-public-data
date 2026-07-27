from __future__ import annotations

import sys

import fetch_x_with_hermes
from hermes_response_parser import extract_hermes_payload


def main() -> int:
    fetch_x_with_hermes.extract_json = extract_hermes_payload
    return fetch_x_with_hermes.main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        fetch_x_with_hermes.write_status("failed", error=str(exc))
        print(f"X取得失敗: {exc}", file=sys.stderr)
        raise SystemExit(1)
