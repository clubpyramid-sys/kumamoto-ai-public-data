from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_x_with_hermes import extract_json, merge_items, normalize_items, resolve_x_refresh


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

    def _item(self, post_id: str, handle: str, date: str) -> dict:
        return {
            "id": post_id,
            "handle": handle,
            "display_name": handle,
            "published_at": date,
            "text": post_id,
            "url": f"https://x.com/{handle}/status/{post_id}",
            "is_reply": False,
            "is_repost": False,
            "media": [],
        }

    def test_all_accounts_success(self) -> None:
        fresh = [
            self._item("301", "club_kumamoto", "2026-07-31T01:00:00Z"),
            self._item("302", "kumamoto_luna", "2026-07-31T00:00:00Z"),
        ]
        merged, missing, retained = resolve_x_refresh(
            fresh, [], self.allowed, list(self.allowed.values()), 20, 40
        )
        self.assertEqual(len(merged), 2)
        self.assertEqual(missing, [])
        self.assertEqual(retained, [])

    def test_partial_success_retains_previous_account(self) -> None:
        fresh = [self._item("401", "club_kumamoto", "2026-07-31T01:00:00Z")]
        previous = [self._item("399", "kumamoto_luna", "2026-07-30T01:00:00Z")]
        merged, missing, retained = resolve_x_refresh(
            fresh, previous, self.allowed, list(self.allowed.values()), 20, 40
        )
        self.assertEqual({item["id"] for item in merged}, {"401", "399"})
        self.assertEqual(missing, ["kumamoto_luna"])
        self.assertEqual(retained, ["kumamoto_luna"])

    def test_all_failed_with_previous_keeps_previous_unmodified(self) -> None:
        previous = [self._item("499", "club_kumamoto", "2026-07-30T01:00:00Z")]
        before = list(previous)
        with self.assertRaisesRegex(RuntimeError, "前回値を維持"):
            resolve_x_refresh([], previous, self.allowed, list(self.allowed.values()), 20, 40)
        self.assertEqual(previous, before)

    def test_all_failed_without_previous_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "全アカウント"):
            resolve_x_refresh([], [], self.allowed, list(self.allowed.values()), 20, 40)


if __name__ == "__main__":
    unittest.main()
