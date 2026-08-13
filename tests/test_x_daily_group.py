from __future__ import annotations

import json
import plistlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from publish_x_daily import safe_relative_path, target_has_unpublished_change
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
        self.assertTrue(config["retry_missing_accounts_individually"])
        self.assertTrue(config["allow_missing_accounts_after_retry"])
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

    def test_daily_config_writes_separate_raw_audit_path(self) -> None:
        import run_fetch_x_daily_with_hermes as module
        module.configure_daily_pipeline()
        self.assertEqual(module.fetch_x_with_hermes.RAW_COUNTS_PATH.name, "hermes_daily_raw_counts.json")

    def test_unpublished_target_is_detected_without_staging(self) -> None:
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "test"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
            target = root / "docs/x/daily_latest.json"
            target.parent.mkdir(parents=True)
            target.write_text('{"value":"old"}\n', encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "docs/x/daily_latest.json"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-m", "seed"], check=True, capture_output=True)
            target.write_text('{"value":"new"}\n', encoding="utf-8")
            self.assertTrue(target_has_unpublished_change(root, target))


if __name__ == "__main__":
    unittest.main()
