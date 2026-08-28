from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_x_with_hermes as module
from fetch_x_with_hermes import build_per_account_results, extract_json, merge_items, normalize_items, raw_response_counts, resolve_x_refresh, sanitize_raw_items
from import_hermes_x import import_hermes_x


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

    def test_raw_counts_preserve_the_pre_normalisation_stage(self) -> None:
        records = [
            {"id": "123", "handle": "club_kumamoto"},
            {"id": "124", "handle": "unknown"},
            "not-a-record",
        ]
        self.assertEqual(
            raw_response_counts(records, self.allowed),
            {"club_kumamoto": 1, "_unclassified": 2},
        )

    def test_raw_capture_keeps_only_allowlisted_public_fields(self) -> None:
        records = [
            {
                "id": "123",
                "handle": "@club_kumamoto",
                "text": "公開投稿",
                "url": "https://x.com/club_kumamoto/status/123",
                "provider_trace": "must-not-be-saved",
                "token": "must-not-be-saved",
            },
            {"id": "124", "handle": "unknown", "text": "対象外"},
        ]
        captured = sanitize_raw_items(records, self.allowed)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]["handle"], "club_kumamoto")
        self.assertNotIn("provider_trace", captured[0])
        self.assertNotIn("token", captured[0])

    def test_standard_config_has_its_own_publish_status_path(self) -> None:
        import json
        config = json.loads((ROOT / "config/x_sources.json").read_text(encoding="utf-8"))
        self.assertEqual(config["publish_status"], "runtime/x/hermes_publish_status.json")

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
        results = build_per_account_results(
            list(self.allowed.values()), fresh, merged, retained
        )
        self.assertEqual(results["club_kumamoto"]["state"], "updated")
        self.assertEqual(results["club_kumamoto"]["fresh_count"], 1)
        self.assertEqual(
            results["kumamoto_luna"]["state"],
            "retained_last_known_good",
        )
        self.assertEqual(results["kumamoto_luna"]["published_count"], 1)

    def test_all_failed_with_previous_keeps_previous_unmodified(self) -> None:
        previous = [self._item("499", "club_kumamoto", "2026-07-30T01:00:00Z")]
        before = list(previous)
        with self.assertRaisesRegex(RuntimeError, "前回値を維持"):
            resolve_x_refresh([], previous, self.allowed, list(self.allowed.values()), 20, 40)
        self.assertEqual(previous, before)

    def test_all_failed_without_previous_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "全アカウント"):
            resolve_x_refresh([], [], self.allowed, list(self.allowed.values()), 20, 40)

    def test_uses_tracked_public_json_when_transient_cache_is_missing(self) -> None:
        import json
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            public_path = root / "all_latest.json"
            public_path.write_text(
                json.dumps({"items": [self._item("599", "club_kumamoto", "2026-07-30T01:00:00Z")]}),
                encoding="utf-8",
            )
            with patch.object(module, "INPUT_PATH", root / "missing.json"), patch.object(module, "PUBLIC_FALLBACK_PATH", public_path):
                items = module.load_previous_items()
        self.assertEqual([item["id"] for item in items], ["599"])

    def test_combines_transient_cache_with_tracked_public_lkg(self) -> None:
        import json
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cache_path = root / "cache.json"
            public_path = root / "public.json"
            cache_path.write_text(
                json.dumps({"items": [self._item("601", "club_kumamoto", "2026-07-31T01:00:00Z")]}),
                encoding="utf-8",
            )
            public_path.write_text(
                json.dumps({"items": [self._item("599", "kumamoto_luna", "2026-07-30T01:00:00Z")]}),
                encoding="utf-8",
            )
            with patch.object(module, "INPUT_PATH", cache_path), patch.object(module, "PUBLIC_FALLBACK_PATH", public_path):
                items = module.load_previous_items()
        self.assertEqual({item["id"] for item in items}, {"601", "599"})

    def test_cached_replay_merges_per_post_without_replacing_an_account(self) -> None:
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            input_path = root / "cached.json"
            input_path.write_text(
                json.dumps({"items": [self._item("701", "club_kumamoto", "2026-07-20T00:00:00Z")]}),
                encoding="utf-8",
            )
            audit: dict = {}
            payload = import_hermes_x(
                root,
                {
                    "input": "cached.json",
                    "max_items": 40,
                    "max_items_per_account": 20,
                    "accounts": [{"handle": "club_kumamoto"}],
                },
                previous_items=[self._item("702", "club_kumamoto", "2026-08-01T00:00:00Z")],
                audit=audit,
            )
        self.assertEqual([item["id"] for item in payload["items"]], ["702", "701"])
        self.assertEqual(audit["normalized_count"], 1)
        self.assertEqual(audit["retained_previous_count"], 1)

    def test_cached_replay_preserves_richer_last_known_good_for_same_post(self) -> None:
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "cached.json").write_text(
                json.dumps({"items": [self._item("705", "club_kumamoto", "2026-07-20T00:00:00Z")]}),
                encoding="utf-8",
            )
            previous = self._item("705", "club_kumamoto", "2026-07-20T00:00:00Z")
            previous["text"] = "last-known-good text with complete content"
            payload = import_hermes_x(
                root,
                {"input": "cached.json", "accounts": [{"handle": "club_kumamoto"}]},
                previous_items=[previous],
            )
        self.assertEqual(payload["items"][0]["text"], "last-known-good text with complete content")

    def test_cached_replay_reports_safe_rejection_reason(self) -> None:
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "cached.json").write_text(
                json.dumps({"items": [{
                    "id": "711",
                    "handle": "club_kumamoto",
                    "published_at": "2026-07-20T00:00:00Z",
                    "text": "bad URL",
                    "url": "https://example.com/not-a-status/711",
                }]}),
                encoding="utf-8",
            )
            audit: dict = {}
            with self.assertRaisesRegex(RuntimeError, "1件も生成"):
                import_hermes_x(
                    root,
                    {"input": "cached.json", "accounts": [{"handle": "club_kumamoto"}]},
                    audit=audit,
                )
        self.assertEqual(audit["rejected"], [{"id": "711", "handle": "club_kumamoto", "reason": "invalid_status_url"}])


if __name__ == "__main__":
    unittest.main()
