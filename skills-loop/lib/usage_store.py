"""hermes-lite skills usage sidecar (~/.claude/skills/hermes-lite/.usage.json)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

USAGE_FILE = Path.home() / ".claude" / "skills" / "hermes-lite" / ".usage.json"


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def load() -> dict:
    if not USAGE_FILE.exists():
        return {}
    try:
        return json.loads(USAGE_FILE.read_text())
    except json.JSONDecodeError:
        return {}


def save(data: dict) -> None:
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = USAGE_FILE.with_suffix(USAGE_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))
    tmp.replace(USAGE_FILE)


def upsert(
    name: str,
    *,
    created_at: str | None = None,
    used_at: str | None = None,
    patched_at: str | None = None,
    inc_use: bool = False,
    inc_patch: bool = False,
) -> dict:
    data = load()
    entry = data.setdefault(
        name,
        {
            "created_at": created_at or now_iso(),
            "last_used_at": None,
            "last_patched_at": None,
            "use_count": 0,
            "patch_count": 0,
            "state": "active",
            "agent_created": True,
        },
    )
    if used_at:
        entry["last_used_at"] = used_at
    if inc_use:
        entry["use_count"] = entry.get("use_count", 0) + 1
    if patched_at:
        entry["last_patched_at"] = patched_at
    if inc_patch:
        entry["patch_count"] = entry.get("patch_count", 0) + 1
    save(data)
    return entry


def set_state(name: str, state: str) -> None:
    data = load()
    if name in data:
        data[name]["state"] = state
        save(data)


def delete(name: str) -> None:
    data = load()
    if name in data:
        del data[name]
        save(data)
