from __future__ import annotations

import json
import plistlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from publish_x_daily import safe_relative_path
from run_fetch_x_daily_with_hermes import validate_account_coverage


class XDailyGroupTests(unittest.TestCase):
    def test_daily_config_uses_independent_paths_and_accounts(self) -> None:
        config = json.loads(
            (ROOT / "config/x_sources_daily.json").read_text(encoding="utf-8")
        )
        self.assertEqual(config["input"], "runtime/x/hermes_daily_latest.json")
        self.assertEqual(config["output"], "x/daily_latest.json")
        self.assertEqual(config["max_items_per_account"], 10)
        self.assertEqual(config["minimum_accounts_with_items"], 3)
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

    def test_one_dormant_account_is_allowed(self) -> None:
        accounts = ["SEA_PYRAMID", "CLUB_PYRAMID", "STARLIGHT_CAFE_", "kumamotodeai"]
        missing = validate_account_coverage(
            accounts,
            {
                "SEA_PYRAMID": 10,
                "CLUB_PYRAMID": 10,
                "STARLIGHT_CAFE_": 10,
                "kumamotodeai": 0,
            },
            3,
        )
        self.assertEqual(missing, ["kumamotodeai"])

    def test_broad_search_failure_is_rejected(self) -> None:
        accounts = ["SEA_PYRAMID", "CLUB_PYRAMID", "STARLIGHT_CAFE_", "kumamotodeai"]
        with self.assertRaises(RuntimeError):
            validate_account_coverage(
                accounts,
                {
                    "SEA_PYRAMID": 10,
                    "CLUB_PYRAMID": 10,
                    "STARLIGHT_CAFE_": 0,
                    "kumamotodeai": 0,
                },
                3,
            )


if __name__ == "__main__":
    unittest.main()
