from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.public_git_sync import sync_clean_clone


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=check,
    )


class PublicGitSyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.remote = root / "remote.git"
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, capture_output=True)
        self.seed = root / "seed"
        subprocess.run(["git", "clone", str(self.remote), str(self.seed)], check=True, capture_output=True)
        for repo in (self.seed,):
            git(repo, "config", "user.name", "Test")
            git(repo, "config", "user.email", "test@example.invalid")
        (self.seed / "value.txt").write_text("one\n", encoding="utf-8")
        git(self.seed, "add", "value.txt")
        git(self.seed, "commit", "-m", "initial")
        git(self.seed, "branch", "-M", "main")
        git(self.seed, "push", "-u", "origin", "main")
        git(self.remote, "symbolic-ref", "HEAD", "refs/heads/main")
        self.runtime = root / "runtime"
        subprocess.run(["git", "clone", str(self.remote), str(self.runtime)], check=True, capture_output=True)
        git(self.runtime, "config", "user.name", "Test")
        git(self.runtime, "config", "user.email", "test@example.invalid")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_fast_forward_sync(self) -> None:
        (self.seed / "value.txt").write_text("two\n", encoding="utf-8")
        git(self.seed, "add", "value.txt")
        git(self.seed, "commit", "-m", "remote update")
        git(self.seed, "push")
        sync_clean_clone(self.runtime)
        self.assertEqual((self.runtime / "value.txt").read_text(), "two\n")

    def test_divergence_fails_without_destroying_local_commit(self) -> None:
        (self.runtime / "local.txt").write_text("local\n", encoding="utf-8")
        git(self.runtime, "add", "local.txt")
        git(self.runtime, "commit", "-m", "local commit")
        local_head = git(self.runtime, "rev-parse", "HEAD").stdout.strip()

        (self.seed / "remote.txt").write_text("remote\n", encoding="utf-8")
        git(self.seed, "add", "remote.txt")
        git(self.seed, "commit", "-m", "remote commit")
        git(self.seed, "push")

        with self.assertRaisesRegex(RuntimeError, "git_fast_forward_failed"):
            sync_clean_clone(self.runtime)
        self.assertEqual(git(self.runtime, "rev-parse", "HEAD").stdout.strip(), local_head)
        self.assertEqual((self.runtime / "local.txt").read_text(), "local\n")

    def test_dirty_worktree_is_rejected_without_changes(self) -> None:
        (self.runtime / "value.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "git_worktree_not_clean"):
            sync_clean_clone(self.runtime)
        self.assertEqual((self.runtime / "value.txt").read_text(), "dirty\n")


if __name__ == "__main__":
    unittest.main()
