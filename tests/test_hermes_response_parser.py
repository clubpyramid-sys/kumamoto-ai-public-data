from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from hermes_response_parser import extract_hermes_payload


POST = {
    "id": "123",
    "handle": "club_kumamoto",
    "published_at": "2026-07-27T00:00:00Z",
    "text": "test",
    "url": "https://x.com/club_kumamoto/status/123",
}


class HermesResponseParserTests(unittest.TestCase):
    def test_direct_items(self) -> None:
        payload = extract_hermes_payload(json.dumps({"generated_at": "x", "items": [POST]}))
        self.assertEqual(payload["items"][0]["id"], "123")

    def test_direct_array(self) -> None:
        payload = extract_hermes_payload(json.dumps([POST]))
        self.assertEqual(payload["items"][0]["handle"], "club_kumamoto")

    def test_accounts_groups(self) -> None:
        raw = {
            "accounts": [
                {
                    "handle": "club_kumamoto",
                    "display_name": "KSC",
                    "posts": [{k: v for k, v in POST.items() if k != "handle"}],
                }
            ]
        }
        payload = extract_hermes_payload(json.dumps(raw))
        self.assertEqual(payload["items"][0]["handle"], "club_kumamoto")
        self.assertEqual(payload["items"][0]["display_name"], "KSC")

    def test_nested_json_string(self) -> None:
        inner = json.dumps({"items": [POST]})
        outer = json.dumps({"result": inner})
        payload = extract_hermes_payload(outer)
        self.assertEqual(payload["items"][0]["id"], "123")

    def test_prefers_final_candidate(self) -> None:
        metadata = json.dumps({"status": "tool_done"})
        final = json.dumps({"items": [POST]})
        payload = extract_hermes_payload(metadata + "\n" + final)
        self.assertEqual(payload["items"][0]["id"], "123")

    def test_handle_mapping(self) -> None:
        raw_post = {k: v for k, v in POST.items() if k != "handle"}
        payload = extract_hermes_payload(json.dumps({"club_kumamoto": [raw_post]}))
        self.assertEqual(payload["items"][0]["handle"], "club_kumamoto")


if __name__ == "__main__":
    unittest.main()
