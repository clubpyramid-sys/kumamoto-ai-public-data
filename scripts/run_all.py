from __future__ import annotations

import argparse
import os
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_sites import build_site_payloads
from common import append_jsonl, atomic_write_json, copy_tree, load_json, now_iso, prepare_payload
from fetch_note import fetch_note
from fetch_youtube import fetch_youtube
from import_hermes_x import import_hermes_x
from publish_git import publish
from validate import suspicious_drop, validate_public_tree, validate_source_payload, validate_site_payload


def _log_path() -> Path:
    return ROOT / "logs" / (datetime.now().astimezone().strftime("%Y-%m") + ".jsonl")


def _source_update(staging_docs: Path, public_docs: Path, source: dict, payload: dict, safety: dict) -> bool:
    rel = Path(source["output"])
    candidate_path = staging_docs / rel
    existing_path = public_docs / rel
    existing = load_json(existing_path, {})
    drop_error = suspicious_drop(existing, payload, safety)
    if drop_error:
        raise RuntimeError(drop_error)
    prepared, changed = prepare_payload(payload, existing)
    errors = validate_source_payload(prepared)
    if errors:
        raise RuntimeError(" / ".join(errors))
    atomic_write_json(candidate_path, prepared)
    return changed


def _promote(staging_docs: Path, public_docs: Path) -> list[str]:
    changed: list[str] = []
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    backup_root = ROOT / "backups" / timestamp
    staging_files = {p.relative_to(staging_docs): p for p in staging_docs.rglob("*") if p.is_file()}
    for rel, src in staging_files.items():
        dst = public_docs / rel
        if dst.exists() and src.read_bytes() == dst.read_bytes():
            continue
        if dst.exists():
            backup = backup_root / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, backup)
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(f".{dst.name}.promote.tmp")
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
        changed.append(str(rel))
    return changed


def run(dry_run: bool = False, no_push: bool = False) -> int:
    started = now_iso()
    sources = load_json(ROOT / "config" / "sources.json", {})
    x_config = load_json(ROOT / "config" / "x_sources.json", {})
    filters = load_json(ROOT / "config" / "site_filters.json", {})
    manual = load_json(ROOT / "config" / "manual_selections.json", {})
    docs = ROOT / "docs"
    staging = ROOT / "runtime" / "staging_docs"
    runtime_status = ROOT / "runtime" / "status.json"
    copy_tree(docs, staging)

    outcomes: list[dict] = []
    source_changes = 0
    for source in sources.get("note", []):
        if not source.get("enabled", True):
            continue
        try:
            payload = fetch_note(source, sources.get("http", {}))
            changed = _source_update(staging, docs, source, payload, sources.get("safety", {}))
            source_changes += int(changed)
            outcomes.append({"source_id": source["source_id"], "status": "success", "changed": changed})
        except Exception as exc:
            outcomes.append({"source_id": source.get("source_id"), "status": "failed", "error": str(exc)})

    for source in sources.get("youtube", []):
        if not source.get("enabled", True):
            continue
        try:
            payload = fetch_youtube(source, sources.get("http", {}))
            changed = _source_update(staging, docs, source, payload, sources.get("safety", {}))
            source_changes += int(changed)
            outcomes.append({"source_id": source["source_id"], "status": "success", "changed": changed})
        except Exception as exc:
            outcomes.append({"source_id": source.get("source_id"), "status": "failed", "error": str(exc)})

    if x_config.get("enabled", False):
        try:
            payload = import_hermes_x(ROOT, x_config)
            x_source = {"output": x_config.get("output", "x/all_latest.json")}
            changed = _source_update(staging, docs, x_source, payload, sources.get("safety", {}))
            source_changes += int(changed)
            outcomes.append({"source_id": "x-hermes-grok", "status": "success", "changed": changed})
        except Exception as exc:
            outcomes.append({"source_id": "x-hermes-grok", "status": "failed", "error": str(exc)})

    site_payloads = build_site_payloads(staging, filters, manual)
    for site_id, payload in site_payloads.items():
        rel = Path(filters["sites"][site_id]["output"])
        existing = load_json(docs / rel, {})
        prepared, changed = prepare_payload(payload, existing)
        errors = validate_site_payload(prepared)
        if errors:
            raise RuntimeError(f"サイト別JSON検証失敗 {site_id}: {' / '.join(errors)}")
        atomic_write_json(staging / rel, prepared)
        source_changes += int(changed)

    manifest_candidate = {
        "schema_version": "1.0",
        "project": "kumamoto-ai-public-data",
        "public_base_url": "https://clubpyramid-sys.github.io/kumamoto-ai-public-data/",
        "feeds": {
            "note_account": "note/account_latest.json",
            "note_ai_magazine": "note/magazines/m28cf0da750b4.json",
            "youtube_channel": "youtube/channel_latest.json",
            "x_all": "x/all_latest.json",
            "kumamoto_ai_laboratory": "sites/kumamoto_ai_laboratory.json",
            "cosanostra": "sites/cosanostra.json",
            "kumamotoevent": "sites/kumamotoevent.json"
        }
    }
    existing_manifest = load_json(docs / "manifest.json", {})
    manifest, _ = prepare_payload(manifest_candidate, existing_manifest)
    atomic_write_json(staging / "manifest.json", manifest)

    tree_errors = validate_public_tree(staging)
    if tree_errors:
        raise RuntimeError("公開ツリー検証失敗:\n" + "\n".join(tree_errors))

    if dry_run:
        changed_files = []
        git_result = {"status": "dry_run"}
    else:
        changed_files = _promote(staging, docs)
        git_cfg = dict(sources.get("git", {}))
        if no_push:
            git_cfg["auto_push"] = False
        git_result = publish(ROOT, git_cfg) if changed_files else {"status": "no_changes"}

    status = {
        "started_at": started,
        "finished_at": now_iso(),
        "status": "success" if any(o["status"] == "success" for o in outcomes) else "failed",
        "sources": outcomes,
        "changed_files": changed_files,
        "git": git_result,
    }
    atomic_write_json(runtime_status, status)
    append_jsonl(_log_path(), status)
    print("=== 公開データ更新結果 ===")
    for outcome in outcomes:
        print(f"- {outcome['source_id']}: {outcome['status']} changed={outcome.get('changed', False)}")
        if outcome.get("error"):
            print(f"  error: {outcome['error']}")
    print(f"変更ファイル: {len(changed_files)}")
    print(f"Git: {git_result.get('status')}")
    return 0 if status["status"] == "success" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="note・YouTube・X公開JSONを更新")
    parser.add_argument("--dry-run", action="store_true", help="取得・検証のみでdocsを書き換えない")
    parser.add_argument("--no-push", action="store_true", help="commitはするがpushしない")
    args = parser.parse_args()
    try:
        return run(dry_run=args.dry_run, no_push=args.no_push)
    except Exception as exc:
        status = {
            "started_at": now_iso(),
            "finished_at": now_iso(),
            "status": "fatal",
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        atomic_write_json(ROOT / "runtime" / "status.json", status)
        append_jsonl(_log_path(), status)
        print(status["traceback"], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
