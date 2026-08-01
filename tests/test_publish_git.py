from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from publish_git import _publish_from_clean_worktree


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )


class CleanWorktreePublishTests(unittest.TestCase):
    def test_publishes_only_requested_generated_file_from_remote_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            remote = base / "remote.git"
            seed = base / "seed"
            collector = base / "collector"
            concurrent = base / "concurrent"

            subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
            subprocess.run(["git", "init", "-b", "main", str(seed)], check=True, capture_output=True)
            git(seed, "config", "user.name", "test")
            git(seed, "config", "user.email", "test@example.invalid")
            (seed / "docs").mkdir()
            (seed / "docs" / "feed.json").write_text('{"value":"old"}\n', encoding="utf-8")
            git(seed, "add", "docs/feed.json")
            git(seed, "commit", "-m", "seed")
            git(seed, "remote", "add", "origin", str(remote))
            git(seed, "push", "origin", "main")

            subprocess.run(["git", "clone", "-b", "main", str(remote), str(collector)], check=True, capture_output=True)
            git(collector, "config", "user.name", "test")
            git(collector, "config", "user.email", "test@example.invalid")
            (collector / "docs" / "feed.json").write_text('{"value":"fresh"}\n', encoding="utf-8")
            (collector / "local-only.txt").write_text("preserve me\n", encoding="utf-8")

            subprocess.run(["git", "clone", "-b", "main", str(remote), str(concurrent)], check=True, capture_output=True)
            git(concurrent, "config", "user.name", "test")
            git(concurrent, "config", "user.email", "test@example.invalid")
            (concurrent / "docs" / "other.json").write_text('{"other":true}\n', encoding="utf-8")
            git(concurrent, "add", "docs/other.json")
            git(concurrent, "commit", "-m", "concurrent update")
            git(concurrent, "push", "origin", "main")

            _publish_from_clean_worktree(
                collector,
                "origin",
                "main",
                ["docs/feed.json"],
                "data: publish fresh feed",
            )

            verify = base / "verify"
            subprocess.run(["git", "clone", "-b", "main", str(remote), str(verify)], check=True, capture_output=True)
            self.assertEqual((verify / "docs" / "feed.json").read_text(encoding="utf-8"), '{"value":"fresh"}\n')
            self.assertTrue((verify / "docs" / "other.json").is_file())
            self.assertFalse((verify / "local-only.txt").exists())


if __name__ == "__main__":
    unittest.main()
