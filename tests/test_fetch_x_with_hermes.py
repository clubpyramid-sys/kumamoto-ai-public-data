from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_x_with_hermes import extract_json, merge_items, normalize_items


class HermesXFetcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.allowed = {
            "club_kumamoto": "club_kumamoto",
            "kumamoto_luna": "kumamoto_luna",
        }

    def test_extracts_json_from_markdown_fence(self) -> None:
        value = extract_json('answer\n```json\n{"items": []}\n```')
        self.assertEqual(value, {"items": []})

    def test_normalizes_and_filters_records(self) -> None:
        records = [
            {
                "id": "123",
                "handle": "@club_kumamoto",
                "published_at": "2026-07-26T00:00:00Z",
                "text": "公開投稿",
                "url": "https://x.com/club_kumamoto/status/123",
                "is_reply": False,
                "is_repost": False,
                "media": [],
            },
            {
                "id": "124",
                "handle": "unknown",
                "published_at": "2026-07-26T01:00:00Z",
                "text": "対象外",
                "url": "https://x.com/unknown/status/124",
            },
            {
                "id": "125",
                "handle": "club_kumamoto",
                "published_at": "2026-07-26T02:00:00Z",
                "text": "返信",
                "url": "https://x.com/club_kumamoto/status/125",
                "is_reply": True,
            },
        ]
        items = normalize_items(records, self.allowed)
        self.assertEqual([item["id"] for item in items], ["123"])

    def test_merges_new_and_previous_items(self) -> None:
        fresh = [
            {
                "id": "200",
                "handle": "club_kumamoto",
                "display_name": "KSC",
                "published_at": "2026-07-27T00:00:00Z",
                "text": "new",
                "url": "https://x.com/club_kumamoto/status/200",
                "is_reply": False,
                "is_repost": False,
                "media": [],
            }
        ]
        previous = [
            {
                "id": "199",
                "handle": "club_kumamoto",
                "display_name": "KSC",
                "published_at": "2026-07-26T00:00:00Z",
                "text": "old",
                "url": "https://x.com/club_kumamoto/status/199",
                "is_reply": False,
                "is_repost": False,
                "media": [],
            }
        ]
        merged = merge_items(fresh, previous, self.allowed, per_account_limit=20, total_limit=40)
        self.assertEqual([item["id"] for item in merged], ["200", "199"])


if __name__ == "__main__":
    unittest.main()
