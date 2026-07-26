from __future__ import annotations

import re
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


def _safe_error(value: str) -> str:
    value = re.sub(r"https://[^\s/@:]+:[^\s/@]+@", "https://[credentials-removed]@", value)
    value = re.sub(r"(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}", "[token-removed]", value)
    return value


def _safe_targets(paths: list[str] | None) -> list[str]:
    targets = paths or ["docs"]
    for target in targets:
        path = Path(target)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError(f"unsafe git target: {target}")
    return targets


def publish(root: Path, git_config: dict, paths: list[str] | None = None) -> dict:
    if not (root / ".git").exists():
        return {"status": "skipped", "reason": "not_a_git_repository"}
    targets = _safe_targets(paths)
    staged_before = _run(root, ["diff", "--cached", "--name-only"], check=False)
    if staged_before.returncode != 0:
        raise RuntimeError(_safe_error(staged_before.stderr.strip()) or "git staged status失敗")
    if staged_before.stdout.strip():
        raise RuntimeError("予期しないstage済みファイルがあります。commitせず停止します。")
    status = _run(root, ["status", "--porcelain", "--", *targets], check=False)
    if status.returncode != 0:
        raise RuntimeError(_safe_error(status.stderr.strip()) or "git status失敗")
    if not status.stdout.strip():
        return {"status": "no_changes"}
    _run(root, ["add", "--", *targets])
    staged_after = _run(root, ["diff", "--cached", "--name-only"], check=False)
    staged_paths = [line for line in staged_after.stdout.splitlines() if line]
    def allowed_path(path: str) -> bool:
        return any(path == target or path.startswith(target.rstrip("/") + "/") for target in targets)

    if staged_after.returncode != 0 or not staged_paths or any(not allowed_path(path) for path in staged_paths):
        raise RuntimeError("許可対象外のstageを検出しました。commitせず停止します。")
    message = "data: update public feeds " + datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    commit = _run(root, ["commit", "-m", message], check=False)
    if commit.returncode != 0:
        combined = (commit.stdout + "\n" + commit.stderr).strip()
        if "nothing to commit" in combined.lower():
            return {"status": "no_changes"}
        raise RuntimeError(_safe_error(combined) or "git commit失敗")
    result = {"status": "committed", "message": message, "paths": targets}
    if git_config.get("auto_push", True):
        remote = git_config.get("remote", "origin")
        branch = git_config.get("branch", "main")
        push = _run(root, ["push", remote, branch], check=False)
        if push.returncode != 0:
            raise RuntimeError(_safe_error(push.stderr.strip() or push.stdout.strip()) or "git push失敗")
        result["status"] = "pushed"
    return result
