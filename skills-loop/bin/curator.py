#!/usr/bin/env python3
"""hermes-lite Curator (LLM 不使用、自動状態遷移のみ)。

本家 NousResearch/hermes-agent agent/curator.py :: apply_automatic_transitions の踏襲。
7 日サイクル想定 (cron で起動)。

State transitions:
  - last_used_at が 30 日以内 → active
  - 31 〜 90 日 → stale
  - 91 日以上 → archived (~/.claude/skills/hermes-lite/<name>/ を .archive/<name>/ に mv)
  - 一度 stale でも使われたら active に戻る (reactivation)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import skill_io  # noqa: E402
import usage_store  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
RUNS_DIR = STATE_DIR / "runs"
CURATOR_STATE = STATE_DIR / "curator_state.json"
ARCHIVE_DIR = skill_io.HERMES_LITE_ROOT / ".archive"
USAGE_TRACKER = ROOT / "bin" / "usage-tracker.py"

STALE_DAYS = 30
ARCHIVE_DAYS = 90


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _classify(last_used_at: str | None, fallback: str | None) -> str:
    ts = _parse_iso(last_used_at) or _parse_iso(fallback)
    if ts is None:
        return "active"
    age = _now() - ts
    if age >= timedelta(days=ARCHIVE_DAYS):
        return "archived"
    if age >= timedelta(days=STALE_DAYS):
        return "stale"
    return "active"


def run(dry_run: bool) -> dict:
    if not dry_run:
        subprocess.run([sys.executable, str(USAGE_TRACKER)], check=False)

    data = usage_store.load()
    managed_paths = {skill_io.skill_name_from_path(p): p for p in skill_io.list_managed_skills()}

    transitions: list[dict] = []
    archives: list[dict] = []

    for name, skill_md in managed_paths.items():
        entry = data.get(name, {})
        old_state = entry.get("state", "active")
        new_state = _classify(entry.get("last_used_at"), entry.get("created_at"))
        if new_state != old_state:
            transitions.append({"name": name, "from": old_state, "to": new_state})
        if new_state == "archived":
            archives.append(
                {"name": name, "from": str(skill_md.parent), "to": str(ARCHIVE_DIR / name)}
            )
        if not dry_run:
            entry["state"] = new_state
            data[name] = entry

    if not dry_run:
        usage_store.save(data)
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        for arch in archives:
            src = Path(arch["from"])
            dst = Path(arch["to"])
            if dst.exists():
                dst = dst.with_name(dst.name + "-" + _now().strftime("%Y%m%d%H%M%S"))
                arch["to"] = str(dst)
            try:
                shutil.move(str(src), str(dst))
            except OSError as e:
                arch["error"] = str(e)

    return {
        "ran_at": _now().isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "managed_count": len(managed_paths),
        "transitions": transitions,
        "archives": archives,
    }


def update_state_file(summary: dict) -> None:
    state: dict = {}
    if CURATOR_STATE.exists():
        try:
            state = json.loads(CURATOR_STATE.read_text())
        except json.JSONDecodeError:
            pass
    state["last_run_at"] = summary["ran_at"]
    state["run_count"] = state.get("run_count", 0) + 1
    state["last_run_summary"] = {
        "transitions": len(summary["transitions"]),
        "archives": len(summary["archives"]),
        "managed_count": summary["managed_count"],
    }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CURATOR_STATE.write_text(json.dumps(state, indent=2))


def write_run_log(summary: dict) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ts = summary["ran_at"].replace(":", "").replace("-", "")
    path = RUNS_DIR / f"curator-{ts}.json"
    path.write_text(json.dumps(summary, indent=2))
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    summary = run(dry_run=args.dry_run)

    print(
        f"[curator] managed={summary['managed_count']} "
        f"transitions={len(summary['transitions'])} "
        f"archives={len(summary['archives'])} dry_run={args.dry_run}"
    )
    for tr in summary["transitions"]:
        print(f"  state: {tr['name']}: {tr['from']} -> {tr['to']}")
    for ar in summary["archives"]:
        print(f"  archive: {ar['name']} -> {ar['to']}")

    if not args.dry_run:
        update_state_file(summary)
        log = write_run_log(summary)
        print(f"[curator] log: {log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
