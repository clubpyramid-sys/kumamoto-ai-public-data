from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path


def _run(root: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=check,
    )


def publish(root: Path, git_config: dict) -> dict:
    if not (root / ".git").exists():
        return {"status": "skipped", "reason": "not_a_git_repository"}
    status = _run(root, ["status", "--porcelain", "--", "docs"], check=False)
    if status.returncode != 0:
        raise RuntimeError(status.stderr.strip() or "git status失敗")
    if not status.stdout.strip():
        return {"status": "no_changes"}
    _run(root, ["add", "--", "docs"])
    message = "data: update public feeds " + datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    commit = _run(root, ["commit", "-m", message], check=False)
    if commit.returncode != 0:
        combined = (commit.stdout + "\n" + commit.stderr).strip()
        if "nothing to commit" in combined.lower():
            return {"status": "no_changes"}
        raise RuntimeError(combined or "git commit失敗")
    result = {"status": "committed", "message": message}
    if git_config.get("auto_push", True):
        remote = git_config.get("remote", "origin")
        branch = git_config.get("branch", "main")
        push = _run(root, ["push", remote, branch], check=False)
        if push.returncode != 0:
            raise RuntimeError(push.stderr.strip() or push.stdout.strip() or "git push失敗")
        result["status"] = "pushed"
    return result
