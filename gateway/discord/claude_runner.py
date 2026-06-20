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

# ~/hermes-lite/ ルート。claude を cwd=ここで起動して CLAUDE.md を自動ロードさせる。
HERMES_HOME = Path(__file__).resolve().parents[2]

# claude-watch/server.py の DISALLOWED_TOOLS を踏襲。
# Slack 送信系は しょうへい個人ワークスペース前提でデフォルト許可、
# Gmail / Calendar / Notion 送信系と Cron / 破壊的シェルは禁止維持。
DISALLOWED_TOOLS = [
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

# 明示的に allow したいツール（claude にツール選択を意識させる）
ALLOWED_TOOLS = ["WebSearch", "WebFetch"]

# Discord 用に振る舞いをチューニング:
# - 即興質問は短く直接答える、確認質問は最小化
# - 知らないことは WebSearch
# - 継続実行依頼は ~/hermes-lite/jobs/ にジョブ化（手順は CLAUDE.md）
APPEND_SYSTEM_PROMPT = (
    "あなたは Discord 上のしょうへい専用アシスタントです。"
    "返事は短く、確認質問はできる限りせず、わかる範囲で直接答えてください。"
    "天気・ニュース・最新情報など知らないことを聞かれたら WebSearch を積極的に使ってください。"
    "出力は読みやすい日本語の地の文を優先し、見出しや長いコードブロックは必要なときだけ。"
    "前の発言を覚えていて自然に続けてください。"
    "\n\n"
    "あなたは今 ~/hermes-lite/ ディレクトリにいます。ジョブ作成・修正の依頼を受けたら、"
    "まず ~/hermes-lite/CLAUDE.md を読んで、そこに書かれた手順に従ってください。"
    "\n"
    "判別の目安：「毎朝」「定期的に」「自動で」「いつも」「ジョブ化して」など継続実行を匂わせる依頼は"
    "~/hermes-lite/jobs/<name>/ にファイルを作って systemd timer に登録するジョブ化タスク。"
    "それ以外の単発質問はその場で答えるだけ。迷ったら一度だけ "
    "「ジョブにしておく？それとも今だけ答えるだけにする？」と聞いてください。"
)


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
    cmd.extend(["--append-system-prompt", APPEND_SYSTEM_PROMPT])
    cmd.extend(["--allowed-tools", *ALLOWED_TOOLS])
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
            cwd=str(HERMES_HOME),   # ~/hermes-lite/CLAUDE.md を自動ロードさせる
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
