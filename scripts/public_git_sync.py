from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


def _safe_text(value: str) -> str:
    text = re.sub(
        r"https://[^\s/@:]+:[^\s/@]+@",
        "https://[credentials-removed]@",
        value,
    )
    text = re.sub(
        r"(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}",
        "[token-removed]",
        text,
    )
    text = re.sub(r"(?:/Users|/Volumes)/[^\s]+", "local-repository", text)
    return " ".join(text.split())[-500:]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def sync_clean_clone(
    root: Path,
    *,
    remote: str = "origin",
    branch: str = "main",
) -> None:
    """Synchronize a dedicated clean clone without reset, rebase, or stashing."""
    status = _git(root, "status", "--porcelain")
    if status.returncode != 0:
        raise RuntimeError("git_status_failed")
    if status.stdout.strip():
        raise RuntimeError("git_worktree_not_clean")

    fetched = _git(root, "fetch", remote, branch)
    if fetched.returncode != 0:
        raise RuntimeError("git_fetch_failed: " + _safe_text(fetched.stderr))

    pulled = _git(root, "pull", "--ff-only", remote, branch)
    if pulled.returncode != 0:
        raise RuntimeError("git_fast_forward_failed: " + _safe_text(pulled.stderr))

    final_status = _git(root, "status", "--porcelain")
    if final_status.returncode != 0 or final_status.stdout.strip():
        raise RuntimeError("git_sync_left_dirty_worktree")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="main")
    args = parser.parse_args()
    try:
        sync_clean_clone(args.root.resolve(), remote=args.remote, branch=args.branch)
    except RuntimeError as exc:
        print(f"[git_sync_failed] {exc}")
        return 2
    print("[git_sync_completed]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
