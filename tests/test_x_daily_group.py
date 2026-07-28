from __future__ import annotations

import json
import plistlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from publish_x_daily import safe_relative_path


class XDailyGroupTests(unittest.TestCase):
    def test_daily_config_uses_independent_paths_and_accounts(self) -> None:
        config = json.loads(
            (ROOT / "config/x_sources_daily.json").read_text(encoding="utf-8")
        )
        self.assertEqual(config["input"], "runtime/x/hermes_daily_latest.json")
        self.assertEqual(config["output"], "x/daily_latest.json")
        self.assertEqual(config["max_items_per_account"], 10)
        handles = [account["handle"] for account in config["accounts"]]
        self.assertEqual(
            handles,
            ["SEA_PYRAMID", "CLUB_PYRAMID", "STARLIGHT_CAFE_", "kumamotodeai"],
        )

    def test_launchd_runs_once_at_5am(self) -> None:
        template = (
            ROOT
            / "launchd/com.clubpyramid.kumamoto-ai-public-data.x-feed-daily.plist.template"
        ).read_text(encoding="utf-8")
        payload = template.replace("__ROOT__", "/tmp/repo")
        payload = payload.replace("__HOME__", "/tmp/home")
        payload = payload.replace("__HERMES_BIN__", "/tmp/hermes")
        plist = plistlib.loads(payload.encode("utf-8"))
        self.assertEqual(
            plist["Label"],
            "com.clubpyramid.kumamoto-ai-public-data.x-feed-daily",
        )
        self.assertEqual(plist["StartCalendarInterval"], {"Hour": 5, "Minute": 0})
        self.assertIn("/tmp/repo/bin/run_x_daily_update.sh", plist["ProgramArguments"])

    def test_daily_paths_reject_parent_traversal(self) -> None:
        self.assertEqual(safe_relative_path("x/daily_latest.json"), Path("x/daily_latest.json"))
        with self.assertRaises(ValueError):
            safe_relative_path("../outside.json")
        with self.assertRaises(ValueError):
            safe_relative_path("/tmp/outside.json")


if __name__ == "__main__":
    unittest.main()
