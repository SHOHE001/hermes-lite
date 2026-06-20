#!/usr/bin/env python3
"""hermes-lite skill 使用量集計。

~/.claude/projects/**/*.jsonl を全スキャンし、
~/.claude/skills/hermes-lite/.usage.json を更新する。
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import session_log  # noqa: E402
import skill_io  # noqa: E402
import usage_store  # noqa: E402

PROJECTS_DIR = Path.home() / ".claude" / "projects"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def main() -> int:
    managed = {skill_io.skill_name_from_path(p): p for p in skill_io.list_managed_skills()}
    if not managed:
        print("[usage-tracker] no managed hermes-lite skills, nothing to do")
        return 0

    print(f"[usage-tracker] scanning for {len(managed)} skill(s): {sorted(managed.keys())}")

    last_used: dict[str, str] = {}
    use_count: dict[str, int] = {n: 0 for n in managed}

    jsonl_files = list(PROJECTS_DIR.rglob("*.jsonl"))
    print(f"[usage-tracker] scanning {len(jsonl_files)} jsonl file(s)")

    for jsonl in jsonl_files:
        events = session_log.read_jsonl(jsonl)
        if not events:
            continue
        loaded = set(session_log.list_loaded_skills(events))
        for name in managed:
            if name in loaded or f"hermes-lite/{name}" in loaded:
                last_ts = None
                for e in reversed(events):
                    ts = e.get("timestamp")
                    if ts:
                        last_ts = ts
                        break
                if last_ts is None:
                    last_ts = _iso(jsonl.stat().st_mtime)
                cur = last_used.get(name)
                if cur is None or last_ts > cur:
                    last_used[name] = last_ts
                use_count[name] += 1

    data = usage_store.load()
    for name, skill_md in managed.items():
        entry = data.get(name, {})
        entry.setdefault("created_at", _iso(skill_md.stat().st_mtime))
        entry["last_used_at"] = last_used.get(name)
        entry["use_count"] = use_count[name]
        entry.setdefault("last_patched_at", None)
        entry.setdefault("patch_count", 0)
        entry.setdefault("state", "active")
        entry["agent_created"] = True
        data[name] = entry
    usage_store.save(data)

    print(f"[usage-tracker] wrote {usage_store.USAGE_FILE}")
    for name, entry in sorted(usage_store.load().items()):
        print(
            f"  - {name}: last_used={entry.get('last_used_at')} "
            f"use_count={entry.get('use_count')} state={entry.get('state')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
