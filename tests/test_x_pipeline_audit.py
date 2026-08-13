from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from write_x_pipeline_audit import build_audit


class XPipelineAuditTests(unittest.TestCase):
    def test_records_raw_normalized_retained_and_public_counts(self) -> None:
        config = {"accounts": [{"handle": "alpha"}, {"handle": "beta"}]}
        fetch_status = {
            "status": "success_partial",
            "missing_accounts": ["beta"],
            "retained_accounts": ["beta"],
            "per_account_results": {
                "alpha": {"fresh_count": 2, "state": "updated"},
                "beta": {"fresh_count": 0, "state": "retained_last_known_good"},
            },
        }
        raw_counts = {"raw_response_item_count": 3, "per_account_raw_response_count": {"alpha": 3}}
        cached = {"items": [{"handle": "alpha"}, {"handle": "beta"}]}
        public = {"items": [{"handle": "alpha"}, {"handle": "alpha"}, {"handle": "beta"}]}
        audit = build_audit(config, fetch_status, raw_counts, cached, public)
        self.assertEqual(audit["per_account"]["alpha"]["raw_response_count"], 3)
        self.assertEqual(audit["per_account"]["alpha"]["normalize_success_count"], 2)
        self.assertEqual(audit["per_account"]["alpha"]["reject_count"], 1)
        self.assertEqual(audit["per_account"]["beta"]["retained_previous_count"], 1)
        self.assertEqual(audit["per_account"]["beta"]["state"], "retained_last_known_good")


if __name__ == "__main__":
    unittest.main()
