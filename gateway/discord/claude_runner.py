from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from config import CLAUDE_BIN, TIMEOUT_SEC

log = logging.getLogger("hermes-lite.discord.runner")

# claude-watch/server.py の DISALLOWED_TOOLS を踏襲 (2026-06-20 同期)
DISALLOWED_TOOLS = [
    "mcp__claude_ai_Slack__slack_send_message",
    "mcp__claude_ai_Slack__slack_send_message_draft",
    "mcp__claude_ai_Slack__slack_schedule_message",
    "mcp__claude_ai_Slack__slack_add_reaction",
    "mcp__claude_ai_Gmail__create_draft",
    "mcp__claude_ai_Google_Calendar__create_event",
    "mcp__claude_ai_Google_Calendar__update_event",
    "mcp__claude_ai_Google_Calendar__respond_to_event",
    "mcp__claude_ai_Notion__notion-create-comment",
    "mcp__claude_ai_Notion__notion-create-pages",
    "mcp__claude_ai_Notion__notion-update-page",
    "CronCreate",
    "CronDelete",
    "Bash(rm *)",
    "Bash(sudo *)",
    "Bash(git push*)",
    "Bash(git reset*)",
]


@dataclass
class RunResult:
    ok: bool
    text: str
    session_id: str | None
    exit_code: int
    invalid_resume: bool
    timed_out: bool


def _build_cmd(prompt: str, resume_session_id: str | None) -> list[str]:
    cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "json"]
    if resume_session_id:
        cmd.extend(["--resume", resume_session_id])
    cmd.extend(["--disallowed-tools", *DISALLOWED_TOOLS])
    return cmd


def run_sync(prompt: str, resume_session_id: str | None = None) -> RunResult:
    cmd = _build_cmd(prompt, resume_session_id)
    log.info(
        "running: %s ... (+%d args)%s",
        shlex.join(cmd[:3]),
        len(cmd) - 3,
        f" resume={resume_session_id}" if resume_session_id else "",
    )
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SEC,
            cwd=str(Path.home()),
            env={**os.environ, "CI": "1"},
        )
    except subprocess.TimeoutExpired:
        return RunResult(
            ok=False,
            text=f"⚠️ タイムアウト ({TIMEOUT_SEC}s)",
            session_id=None,
            exit_code=124,
            invalid_resume=False,
            timed_out=True,
        )

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    if proc.returncode != 0:
        err_excerpt = (stderr or stdout).strip()[:400]
        lower = stderr.lower()
        invalid_resume = bool(resume_session_id) and (
            "session" in lower and ("not found" in lower or "invalid" in lower or "no such" in lower)
        )
        return RunResult(
            ok=False,
            text=f"⚠️ exit={proc.returncode}\n```\n{err_excerpt}\n```",
            session_id=None,
            exit_code=proc.returncode,
            invalid_resume=invalid_resume,
            timed_out=False,
        )

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as e:
        return RunResult(
            ok=False,
            text=f"⚠️ JSON parse error: {e}\n```\n{stdout[:400]}\n```",
            session_id=None,
            exit_code=proc.returncode,
            invalid_resume=False,
            timed_out=False,
        )

    session_id = payload.get("session_id")
    if payload.get("is_error"):
        return RunResult(
            ok=False,
            text=f"⚠️ claude error: {payload.get('result', '(no message)')}",
            session_id=session_id,
            exit_code=proc.returncode,
            invalid_resume=False,
            timed_out=False,
        )

    return RunResult(
        ok=True,
        text=payload.get("result", "") or "(空応答)",
        session_id=session_id,
        exit_code=0,
        invalid_resume=False,
        timed_out=False,
    )


async def run(prompt: str, resume_session_id: str | None = None) -> RunResult:
    return await asyncio.to_thread(run_sync, prompt, resume_session_id)
