from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from x_oembed_enricher import (
    build_x_search_discovery_prompt,
    enrich_discovered_item,
    extract_post_text,
    timestamp_from_snowflake,
)


class XOEmbedEnricherTests(unittest.TestCase):
    def test_extracts_exact_post_text_from_oembed_html(self) -> None:
        html = (
            '<blockquote class="twitter-tweet">'
            '<p lang="ja" dir="ltr">熊本で開催します😊<br>'
            '<a href="https://x.com/hashtag/熊本">#熊本</a> '
            '<a href="https://t.co/example">example.com</a></p>'
            '&mdash; KSC (@club_kumamoto) '
            '<a href="https://x.com/club_kumamoto/status/2081839549874077869">July 28, 2026</a>'
            '</blockquote>'
        )
        self.assertEqual(
            extract_post_text(html),
            "熊本で開催します😊\n#熊本 example.com",
        )

    def test_derives_timestamp_from_known_snowflake(self) -> None:
        self.assertEqual(
            timestamp_from_snowflake("463440424141459456"),
            "2014-05-05T22:09:42Z",
        )

    def test_enriches_discovered_url_with_official_oembed(self) -> None:
        raw = {
            "id": "2081839549874077869",
            "handle": "club_kumamoto",
            "url": "https://x.com/club_kumamoto/status/2081839549874077869",
            "is_reply": False,
            "is_repost": False,
            "media": [
                {
                    "type": "image",
                    "url": "https://pbs.twimg.com/media/example.jpg?name=orig",
                }
            ],
        }

        def fake_fetcher(url: str):
            self.assertEqual(
                url,
                "https://x.com/club_kumamoto/status/2081839549874077869",
            )
            return {
                "author_name": "熊本シークレットクラブ",
                "author_url": "https://x.com/club_kumamoto",
                "html": '<blockquote><p lang="ja">最新のお知らせです。</p></blockquote>',
            }

        enriched = enrich_discovered_item(
            raw,
            {"club_kumamoto": "club_kumamoto"},
            fetcher=fake_fetcher,
        )
        self.assertIsNotNone(enriched)
        assert enriched is not None
        self.assertEqual(enriched["text"], "最新のお知らせです。")
        self.assertEqual(enriched["display_name"], "熊本シークレットクラブ")
        self.assertTrue(enriched["published_at"].endswith("Z"))
        self.assertEqual(enriched["content_source"], "x-oembed")
        self.assertEqual(enriched["media"], raw["media"])

    def test_reuses_previous_normalized_item_without_network(self) -> None:
        previous = {
            "id": "123",
            "handle": "club_kumamoto",
            "published_at": "2026-07-27T00:00:00Z",
            "text": "保存済み本文",
            "url": "https://x.com/club_kumamoto/status/123",
        }

        def should_not_run(_: str):
            raise AssertionError("network fetch should not run")

        enriched = enrich_discovered_item(
            previous,
            {"club_kumamoto": "club_kumamoto"},
            fetcher=should_not_run,
        )
        self.assertEqual(enriched, previous)

    def test_prompt_requires_x_search_and_discovery_only(self) -> None:
        prompt = build_x_search_discovery_prompt(["club_kumamoto"], 6)
        self.assertIn("必ずx_searchツールを使用", prompt)
        self.assertIn('"degraded": false', prompt)
        self.assertIn("本文や日時を入れず", prompt)
        self.assertIn("X公式配信URLをmediaへ含める", prompt)
        self.assertIn("club_kumamoto", prompt)


if __name__ == "__main__":
    unittest.main()
