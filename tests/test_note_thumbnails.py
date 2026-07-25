from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import feedparser
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_note import (  # noqa: E402
    NoteThumbnailResolver,
    _article_page_image_details,
    _feed_entry_image_details,
    normalize_note_thumbnail_url,
)
from merge_note_thumbnails import (  # noqa: E402
    backfill_magazine_thumbnails,
    build_account_article_index,
)


IMAGE_A = "https://assets.st-note.com/production/uploads/images/1/a.png?width=800"
IMAGE_B = "https://assets.st-note.com/production/uploads/images/2/b.webp?quality=85&amp;width=1280"
ARTICLE = "https://note.com/club_pyramid/n/na4c321a60420"


def rss_entry(inner: str):
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns:content="http://purl.org/rss/1.0/modules/content/">
      <channel><title>test</title><link>https://note.com/</link><description>test</description>
      <item><title>article</title><link>{ARTICLE}</link>{inner}</item>
      </channel></rss>"""
    return feedparser.parse(xml).entries[0]


class FakeResponse:
    def __init__(self, text: str, error: Exception | None = None):
        self.text = text
        self.content = text.encode()
        self.error = error

    def raise_for_status(self) -> None:
        if self.error:
            raise self.error


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[str] = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if not self.responses:
            raise AssertionError("unexpected page request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class NoteThumbnailExtractionTests(unittest.TestCase):
    def test_account_index_backfills_only_missing_thumbnail_and_preserves_magazine_data(self):
        account = {"items": [
            {"id": "n1", "url": "https://note.com/club_pyramid/n/n1", "title": "account title", "thumbnail_url": IMAGE_A},
            {"id": "n2", "url": "https://note.com/club_pyramid/n/n2", "title": "account title 2", "thumbnail_url": IMAGE_B},
        ]}
        magazine = {"items": [
            {"id": "n2", "url": "https://note.com/club_pyramid/n/n2", "title": "magazine first", "summary": "keep first", "author": "A", "thumbnail_url": None},
            {"id": "n1", "url": "https://note.com/club_pyramid/n/n1", "title": "magazine second", "summary": "keep second", "author": "B", "thumbnail_url": None},
        ]}
        merged, filled = backfill_magazine_thumbnails(magazine, build_account_article_index([account]))
        self.assertEqual([item["id"] for item in merged["items"]], ["n2", "n1"])
        self.assertEqual([item["title"] for item in merged["items"]], ["magazine first", "magazine second"])
        self.assertEqual([item["summary"] for item in merged["items"]], ["keep first", "keep second"])
        self.assertEqual([item["author"] for item in merged["items"]], ["A", "B"])
        self.assertEqual([item["thumbnail_url"] for item in merged["items"]], [IMAGE_B.replace("&amp;", "&"), IMAGE_A])
        self.assertEqual(filled, ["n2", "n1"])
        self.assertIsNone(magazine["items"][0]["thumbnail_url"])

    def test_account_index_can_match_canonical_url_without_matching_id(self):
        account = {"items": [{
            "id": "",
            "url": "https://note.com/club_pyramid/n/na4c321a60420/?from=feed",
            "thumbnail_url": IMAGE_A,
        }]}
        magazine = {"items": [{
            "id": "different-local-id",
            "url": "http://note.com/club_pyramid/n/na4c321a60420",
            "thumbnail_url": None,
        }]}
        merged, filled = backfill_magazine_thumbnails(magazine, build_account_article_index([account]))
        self.assertEqual(merged["items"][0]["thumbnail_url"], IMAGE_A)
        self.assertEqual(filled, ["different-local-id"])

    def test_rss_priority_and_all_supported_fields(self):
        cases = [
            (
                f"<media:thumbnail url=\"{IMAGE_A}\"/><media:content url=\"{IMAGE_B}\"/>",
                IMAGE_A,
                "rss_media_thumbnail",
            ),
            (f"<media:content url=\"{IMAGE_A}\"/>", IMAGE_A, "rss_media_content"),
            (f"<enclosure url=\"{IMAGE_A}\" type=\"image/png\"/>", IMAGE_A, "rss_image_enclosure"),
            (
                f"<content:encoded><![CDATA[<p>x</p><img src=\"{IMAGE_A}\">]]></content:encoded>",
                IMAGE_A,
                "rss_content_encoded",
            ),
            (f"<description><![CDATA[<img src=\"{IMAGE_A}\">]]></description>", IMAGE_A, "rss_description"),
            ("<description>text only</description>", None, None),
        ]
        for inner, expected, source in cases:
            with self.subTest(source=source):
                self.assertEqual(_feed_entry_image_details(rss_entry(inner)), (expected, source))

    def test_article_page_metadata_priority_and_failures(self):
        cases = [
            (f'<meta property="og:image" content="{IMAGE_A}"><meta name="twitter:image" content="{IMAGE_B}">', IMAGE_A, "page_og_image"),
            (f'<meta name="twitter:image" content="{IMAGE_A}">', IMAGE_A, "page_twitter_image"),
            (f'<meta name="twitter:image:src" content="{IMAGE_A}">', IMAGE_A, "page_twitter_image_src"),
            (f'<link rel="preload image_src" href="{IMAGE_A}">', IMAGE_A, "page_image_src"),
            ("<html><head><meta", None, None),
            ("", None, None),
        ]
        for page_html, expected, source in cases:
            with self.subTest(source=source):
                self.assertEqual(_article_page_image_details(page_html), (expected, source))

    def test_url_validation_preserves_query_and_rejects_unsafe_or_tiny_images(self):
        self.assertEqual(normalize_note_thumbnail_url(IMAGE_B), IMAGE_B.replace("&amp;", "&"))
        for value in (
            "http://assets.st-note.com/production/uploads/images/1/a.png",
            "javascript:alert(1)",
            "data:image/png;base64,AAAA",
            "https://example.com/a.png",
            "https://assets.st-note.com/production/uploads/images/1/no-extension",
            "https://assets.st-note.com/production/uploads/images/1/profile_a.png?width=800",
            "https://assets.st-note.com/production/uploads/images/1/a.png?width=120",
        ):
            with self.subTest(value=value):
                self.assertIsNone(normalize_note_thumbnail_url(value))

    def test_shared_rss_result_avoids_duplicate_page_fetch(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = NoteThumbnailResolver(Path(temp) / "cache.json", {"note_page_interval_seconds": 0})
            resolver.register_rss_entries([rss_entry(f'<media:thumbnail url="{IMAGE_A}"/>')])
            session = FakeSession([])
            first = resolver.resolve("na4c321a60420", ARTICLE, None, session)
            second = resolver.resolve("na4c321a60420", ARTICLE, None, session)
            self.assertEqual((first, second), (IMAGE_A, IMAGE_A))
            self.assertEqual(session.calls, [])
            self.assertEqual(resolver.page_fetch_count, 0)

    def test_existing_valid_thumbnail_precedes_rss_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = NoteThumbnailResolver(Path(temp) / "cache.json", {"note_page_interval_seconds": 0})
            resolver.register_rss_entries([rss_entry(f'<media:thumbnail url="{IMAGE_A}"/>')])
            current = IMAGE_B.replace("&amp;", "&")
            self.assertEqual(resolver.resolve("na4c321a60420", ARTICLE, current, FakeSession([])), current)

    def test_page_fallback_is_fetched_once_then_cached(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cache.json"
            resolver = NoteThumbnailResolver(path, {"note_page_interval_seconds": 0})
            session = FakeSession([FakeResponse(f'<meta property="og:image" content="{IMAGE_A}">')])
            first = resolver.resolve("na4c321a60420", ARTICLE, None, session)
            second = resolver.resolve("na4c321a60420", ARTICLE, None, session)
            resolver.save()
            restored = NoteThumbnailResolver(path, {"note_page_interval_seconds": 0})
            third = restored.resolve("na4c321a60420", ARTICLE, None, FakeSession([]))
            self.assertEqual((first, second, third), (IMAGE_A, IMAGE_A, IMAGE_A))
            self.assertEqual(len(session.calls), 1)

    def test_page_404_timeout_and_missing_metadata_return_none(self):
        failures = [
            requests.Timeout("timeout"),
            FakeResponse("", requests.HTTPError("404")),
            FakeResponse("<html>no image</html>"),
        ]
        for index, failure in enumerate(failures):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temp:
                resolver = NoteThumbnailResolver(Path(temp) / "cache.json", {"note_page_interval_seconds": 0})
                self.assertIsNone(resolver.resolve(f"nmissing{index}", ARTICLE, None, FakeSession([failure])))

    def test_last_good_image_survives_invalid_update_and_corrupt_cache_is_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cache.json"
            resolver = NoteThumbnailResolver(path, {"note_page_interval_seconds": 0})
            resolver.remember("na4c321a60420", ARTICLE, IMAGE_A, "page_og_image")
            resolver.remember("na4c321a60420", ARTICLE, "https://example.com/bad.png", "bad")
            resolver.save()
            restored = NoteThumbnailResolver(path, {"note_page_interval_seconds": 0})
            self.assertEqual(restored.resolve("na4c321a60420", ARTICLE, None, FakeSession([])), IMAGE_A)

            path.write_text("{broken", encoding="utf-8")
            corrupt = NoteThumbnailResolver(path, {"note_page_interval_seconds": 0})
            self.assertEqual(corrupt.cache, {})


if __name__ == "__main__":
    unittest.main()
