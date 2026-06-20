"""~/.claude/projects/*/*.jsonl のパースと直前ターン抽出。"""
from __future__ import annotations

import json
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    """壊れた行は黙ってスキップ。"""
    out: list[dict] = []
    try:
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return out


def _content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content) if content else ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "tool_use":
            name = block.get("name", "?")
            parts.append(f"[tool_use: {name}]")
        elif btype == "tool_result":
            parts.append("[tool_result]")
    return "\n".join(p for p in parts if p)


def _role_of(event: dict) -> str | None:
    msg = event.get("message") or {}
    return msg.get("role") or event.get("type")


def _is_human_user_event(e: dict) -> bool:
    """type=user の中でも tool_result-only ではなく実際に人間が打った発話のみ True。"""
    if _role_of(e) != "user":
        return False
    content = (e.get("message") or {}).get("content")
    if isinstance(content, str) and content.strip():
        return True
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") == "text" for b in content)
    return False


def extract_last_turn(events: list[dict]) -> str:
    """最後の「人間 user 発話」から末尾までを整形して返す。

    tool_use / tool_result / assistant 応答もこの区間に含まれる (= 1ターン分の対話)。
    """
    last_user_idx: int | None = None
    for i in range(len(events) - 1, -1, -1):
        if _is_human_user_event(events[i]):
            last_user_idx = i
            break
    if last_user_idx is None:
        return ""

    parts: list[str] = []
    for e in events[last_user_idx:]:
        role = _role_of(e) or "unknown"
        msg = e.get("message") or {}
        text = _content_to_text(msg.get("content"))
        if text:
            parts.append(f"## {role}\n\n{text}")
    return "\n\n".join(parts)


def list_loaded_skills(events: list[dict]) -> list[str]:
    """セッションで読み込まれた skill 名 (skill_listing attachment から)。"""
    names: set[str] = set()
    for e in events:
        attach = e.get("attachment") or {}
        if attach.get("type") == "skill_listing":
            for n in attach.get("names", []) or []:
                if isinstance(n, str):
                    names.add(n)
    return sorted(names)
