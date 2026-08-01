from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
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


def _publish_from_clean_worktree(
    root: Path,
    remote: str,
    branch: str,
    targets: list[str],
    message: str,
) -> None:
    """Publish only the approved generated targets from a clean remote head.

    The collector's working tree can contain unrelated local work.  A rejected
    non-fast-forward push must not require resetting, stashing, or rebasing
    that work.  This isolated worktree starts at ``remote/branch`` and receives
    only the generated public targets, so an interrupted concurrent publisher
    cannot strand fresh feeds locally.
    """
    fetch = _run(root, ["fetch", remote, branch], check=False)
    if fetch.returncode != 0:
        raise RuntimeError(_safe_error(fetch.stderr.strip()) or "git fetch失敗")

    temporary = Path(tempfile.mkdtemp(prefix="kumamoto-public-data-publish-"))
    added = False
    try:
        worktree = _run(
            root,
            ["worktree", "add", "--detach", str(temporary), f"{remote}/{branch}"],
            check=False,
        )
        if worktree.returncode != 0:
            raise RuntimeError(_safe_error(worktree.stderr.strip()) or "一時公開worktree作成失敗")
        added = True

        for target in targets:
            source = root / target
            destination = temporary / target
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True)
            elif source.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            else:
                raise RuntimeError(f"公開対象が存在しません: {target}")

        _run(temporary, ["add", "--", *targets])
        checked = _run(temporary, ["diff", "--cached", "--check"], check=False)
        if checked.returncode != 0:
            raise RuntimeError(_safe_error(checked.stderr.strip()) or "公開差分検証失敗")
        if not _run(temporary, ["diff", "--cached", "--quiet"], check=False).returncode:
            return
        commit = _run(temporary, ["commit", "-m", message], check=False)
        if commit.returncode != 0:
            raise RuntimeError(_safe_error((commit.stdout + "\n" + commit.stderr).strip()) or "一時公開commit失敗")
        pushed = _run(temporary, ["push", remote, f"HEAD:{branch}"], check=False)
        if pushed.returncode != 0:
            raise RuntimeError(_safe_error(pushed.stderr.strip() or pushed.stdout.strip()) or "一時公開push失敗")
    finally:
        if added:
            _run(root, ["worktree", "remove", "--force", str(temporary)], check=False)
        shutil.rmtree(temporary, ignore_errors=True)


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
            _publish_from_clean_worktree(root, remote, branch, targets, message)
            result["status"] = "pushed_from_clean_worktree"
            return result
        result["status"] = "pushed"
    return result
