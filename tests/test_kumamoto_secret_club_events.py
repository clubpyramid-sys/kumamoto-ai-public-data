from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_kumamoto_secret_club_events import (  # noqa: E402
    build_payload,
    plain_text,
    run,
    validate_payload,
)
from publish_git import publish  # noqa: E402

JST = ZoneInfo("Asia/Tokyo")


def rss(items: list[str]) -> bytes:
    content = "".join(items)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>test</title><link>https://kumamotosecretclub.jp/blog2/</link>
    <description>test</description>{content}</channel></rss>'''.encode()


def item(title: str, link: str, description: str = "", pub_date: str = "Sun, 26 Jul 2026 01:00:00 GMT") -> str:
    return f"<item><title>{title}</title><link>{link}</link><description><![CDATA[{description}]]></description><pubDate>{pub_date}</pubDate></item>"


class FakeResponse:
    status_code = 200

    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, result):
        self.result = result

    def get(self, url, **kwargs):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class KumamotoSecretClubEventTests(unittest.TestCase):
    NOW = datetime(2026, 7, 26, 12, 0, tzinfo=JST)

    def test_future_event_is_normalized_and_schema_compatible(self):
        source = rss([item(
            "7月30日 西銀座通り BAR開催・受付中",
            "https://kumamotosecretclub.jp/blog2/2026-07-30.html",
            "<p>19:00から受付中です。</p>",
        )])
        payload, diagnostics = build_payload(source, self.NOW)
        event = payload["current_event"]
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(event["event_date"], "2026-07-30")
        self.assertEqual(event["event_time"], "19:00")
        self.assertEqual(event["area"], "西銀座通り周辺")
        self.assertEqual(event["status"], "accepting")
        self.assertEqual(diagnostics["current_candidates"], 1)
        self.assertEqual(validate_payload(payload), [])

    def test_past_report_and_unknown_date_are_excluded(self):
        source = rss([
            item("7月20日 開催レポート", "https://kumamotosecretclub.jp/blog2/2026-07-20.html"),
            item("読み物", "https://kumamotosecretclub.jp/blog2/essay.html"),
        ])
        payload, diagnostics = build_payload(source, self.NOW)
        self.assertEqual(payload["status"], "no_current_event")
        self.assertIsNone(payload["current_event"])
        self.assertEqual(diagnostics["excluded_items"], 2)
        self.assertEqual(validate_payload(payload), [])

    def test_cancel_and_update_are_current_public_statuses(self):
        source = rss([
            item("7月27日 開催中止のお知らせ", "https://kumamotosecretclub.jp/blog2/2026-07-27.html"),
            item("7月28日 時間変更", "https://kumamotosecretclub.jp/blog2/2026-07-28.html"),
        ])
        payload, _ = build_payload(source, self.NOW)
        self.assertEqual([entry["status"] for entry in payload["recent_items"]], ["cancelled", "updated"])

    def test_html_and_personal_details_are_removed(self):
        raw = "<script>bad()</script><style>x</style><p>集合場所：秘密の建物 田中さん 090-1234-5678 a@example.com LINE ID: abcd1234</p>"
        cleaned = plain_text(raw)
        for forbidden in ("bad", "秘密の建物", "田中さん", "090", "example.com", "abcd1234", "<p>"):
            self.assertNotIn(forbidden, cleaned)

    def test_forbidden_content_is_excluded(self):
        source = rss([item(
            "7月30日 開催",
            "https://kumamotosecretclub.jp/blog2/2026-07-30.html",
            "出会い系サービスへの紹介",
        )])
        payload, diagnostics = build_payload(source, self.NOW)
        self.assertEqual(payload["status"], "no_current_event")
        self.assertEqual(diagnostics["excluded_reasons"], {"inappropriate_content": 1})

    def test_unchanged_semantics_does_not_rewrite_generated_at(self):
        source = rss([item("7月30日 開催", "https://kumamotosecretclub.jp/blog2/2026-07-30.html")])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "current.json"
            log_dir = root / "logs"
            session = FakeSession(FakeResponse(source))
            changed, _ = run("https://example.invalid/rss", output, ROOT / "schemas" / "kumamoto_secret_club_current.schema.json", log_dir, session=session)
            first = output.read_bytes()
            changed_again, _ = run("https://example.invalid/rss", output, ROOT / "schemas" / "kumamoto_secret_club_current.schema.json", log_dir, session=session)
            self.assertTrue(changed)
            self.assertFalse(changed_again)
            self.assertEqual(output.read_bytes(), first)

    def test_fetch_failure_preserves_last_good_json(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "current.json"
            original = b'{"last":"good"}\n'
            output.write_bytes(original)
            with self.assertRaises(requests.Timeout):
                run(
                    "https://example.invalid/rss",
                    output,
                    ROOT / "schemas" / "kumamoto_secret_club_current.schema.json",
                    root / "logs",
                    session=FakeSession(requests.Timeout("timeout")),
                )
            self.assertEqual(output.read_bytes(), original)
            record = json.loads(next((root / "logs").glob("*.jsonl")).read_text(encoding="utf-8"))
            self.assertEqual(record["fetch_result"], "error")
            self.assertEqual(record["github_push"], "not_attempted")

    def test_targeted_publish_does_not_stage_unrelated_x_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            event_path = root / "docs" / "events" / "current.json"
            x_path = root / "docs" / "x" / "all_latest.json"
            event_path.parent.mkdir(parents=True)
            x_path.parent.mkdir(parents=True)
            event_path.write_text('{"version":1}\n', encoding="utf-8")
            x_path.write_text('{"version":1}\n', encoding="utf-8")
            subprocess.run(["git", "add", "docs"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "initial"], cwd=root, check=True)
            event_path.write_text('{"version":2}\n', encoding="utf-8")
            x_path.write_text('{"version":2}\n', encoding="utf-8")

            result = publish(root, {"auto_push": False}, paths=["docs/events/current.json"])
            committed = subprocess.run(
                ["git", "show", "--pretty=format:", "--name-only", "HEAD"],
                cwd=root,
                check=True,
                text=True,
                capture_output=True,
            ).stdout.splitlines()
            status = subprocess.run(
                ["git", "status", "--short"],
                cwd=root,
                check=True,
                text=True,
                capture_output=True,
            ).stdout
            self.assertEqual(result["status"], "committed")
            self.assertEqual(committed, ["docs/events/current.json"])
            self.assertIn(" M docs/x/all_latest.json", status)

    def test_publish_stops_when_unrelated_file_is_already_staged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            event_path = root / "docs" / "events" / "current.json"
            x_path = root / "docs" / "x" / "all_latest.json"
            event_path.parent.mkdir(parents=True)
            x_path.parent.mkdir(parents=True)
            event_path.write_text('{"version":1}\n', encoding="utf-8")
            x_path.write_text('{"version":1}\n', encoding="utf-8")
            subprocess.run(["git", "add", "docs"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "initial"], cwd=root, check=True)
            event_path.write_text('{"version":2}\n', encoding="utf-8")
            x_path.write_text('{"version":2}\n', encoding="utf-8")
            subprocess.run(["git", "add", "docs/x/all_latest.json"], cwd=root, check=True)

            with self.assertRaisesRegex(RuntimeError, "stage"):
                publish(root, {"auto_push": False}, paths=["docs/events/current.json"])
            head = subprocess.run(
                ["git", "log", "-1", "--pretty=%s"],
                cwd=root,
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip()
            self.assertEqual(head, "initial")

    def test_publish_does_nothing_when_target_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True)
            event_path = root / "docs" / "events" / "current.json"
            event_path.parent.mkdir(parents=True)
            event_path.write_text('{"version":1}\n', encoding="utf-8")
            subprocess.run(["git", "add", "docs"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "initial"], cwd=root, check=True)

            result = publish(root, {"auto_push": False}, paths=["docs/events/current.json"])
            count = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=root,
                check=True,
                text=True,
                capture_output=True,
            ).stdout.strip()
            self.assertEqual(result["status"], "no_changes")
            self.assertEqual(count, "1")


if __name__ == "__main__":
    unittest.main()
