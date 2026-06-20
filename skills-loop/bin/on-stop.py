#!/usr/bin/env python3
"""Stop hook 本体: 直前ターンをレビューして skill ファイルを更新する。

Claude Code が Stop hook の stdin に渡す JSON (例):
  {
    "session_id": "...",
    "transcript_path": "/home/shohei/.claude/projects/<encoded>/<sid>.jsonl",
    "cwd": "...",
    "hook_event_name": "Stop",
    ...
  }

再帰防止:
  - 環境変数 HERMES_SKILL_REVIEW_RUNNING=1 が立っていれば即終了
  - claude -p は --bare で呼び、hooks/auto-memory/CLAUDE.md/skills を全 disable
緊急停止:
  - HERMES_SKILL_REVIEW_DISABLE=1 で全停止
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import session_log  # noqa: E402
import skill_io  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROMPT_FILE = ROOT / "prompts" / "skill-review.md"
RUNS_DIR = ROOT / "state" / "runs"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", str(Path.home() / ".local" / "bin" / "claude"))
TIMEOUT_SEC = int(os.environ.get("HERMES_SKILL_REVIEW_TIMEOUT_SEC", "600"))


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _now_ts() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _read_hook_event() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _resolve_session(
    session_id: str | None, transcript_path: str | None
) -> tuple[str | None, Path | None]:
    if transcript_path:
        p = Path(transcript_path)
        if p.exists():
            return session_id, p
    if session_id and PROJECTS_DIR.exists():
        for proj_dir in PROJECTS_DIR.iterdir():
            cand = proj_dir / f"{session_id}.jsonl"
            if cand.exists():
                return session_id, cand
    return session_id, None


def _build_prompt(turn_text: str, session_id: str, loaded_skills: list[str]) -> str:
    instructions = PROMPT_FILE.read_text()
    managed = [skill_io.skill_name_from_path(p) for p in skill_io.list_managed_skills()]
    existing = "\n".join(f"- {n}" for n in managed) or "(none yet)"
    loaded = "\n".join(f"- {n}" for n in loaded_skills) or "(none)"
    return f"""# Skill Review — hermes-lite

## 会話 (直前ターン)

{turn_text}

## このセッション

- session_id: `{session_id}`
- 確認時刻: {_now_iso()}

## 既存 hermes-lite skill (agent_created)

{existing}

## このセッションで読み込まれた skill

{loaded}

---

## あなたへの指示

{instructions}
"""


def _run_claude(prompt: str) -> tuple[int, str, str]:
    env = {**os.environ, "HERMES_SKILL_REVIEW_RUNNING": "1", "CI": "1"}
    cmd = [
        CLAUDE_BIN,
        "-p",
        "--bare",
        "--output-format", "json",
        "--add-dir", str(skill_io.HERMES_LITE_ROOT),
        prompt,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SEC,
            cwd=str(Path.home()),
            env=env,
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {TIMEOUT_SEC}s"
    return proc.returncode, proc.stdout, proc.stderr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="プロンプトを stdout に出し claude は呼ばない")
    ap.add_argument("--session-id", help="stdin の代わりに直接指定 (テスト用)")
    ap.add_argument("--transcript", help="stdin の代わりに jsonl パスを指定 (テスト用)")
    args = ap.parse_args()

    if os.environ.get("HERMES_SKILL_REVIEW_RUNNING") == "1":
        print("[on-stop] recursion guard hit (HERMES_SKILL_REVIEW_RUNNING=1)")
        return 0
    if os.environ.get("HERMES_SKILL_REVIEW_DISABLE") == "1":
        print("[on-stop] disabled (HERMES_SKILL_REVIEW_DISABLE=1)")
        return 0

    event = {} if (args.session_id or args.transcript) else _read_hook_event()
    session_id = args.session_id or event.get("session_id")
    transcript_path = args.transcript or event.get("transcript_path")

    session_id, jsonl_path = _resolve_session(session_id, transcript_path)
    if jsonl_path is None:
        print(f"[on-stop] jsonl not found (session_id={session_id} transcript={transcript_path})")
        return 0

    if not session_id:
        session_id = jsonl_path.stem  # jsonl filename = session_id

    events = session_log.read_jsonl(jsonl_path)
    turn_text = session_log.extract_last_turn(events)
    if not turn_text.strip():
        print("[on-stop] empty turn, skip")
        return 0
    loaded_skills = session_log.list_loaded_skills(events)

    prompt = _build_prompt(turn_text, session_id or "(unknown)", loaded_skills)

    if args.dry_run:
        print(prompt)
        return 0

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = RUNS_DIR / f"on-stop-{_now_ts()}.json"

    code, out, err = _run_claude(prompt)

    record = {
        "ran_at": _now_iso(),
        "session_id": session_id,
        "transcript_path": str(jsonl_path),
        "turn_chars": len(turn_text),
        "loaded_skills": loaded_skills,
        "claude_exit_code": code,
        "claude_stdout": out[:50000],
        "claude_stderr": err[:5000],
    }
    log_path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
    print(f"[on-stop] log: {log_path} (claude exit={code})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
