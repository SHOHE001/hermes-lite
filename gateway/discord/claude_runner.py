from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from config import CLAUDE_BIN, MODEL, TIMEOUT_SEC

log = logging.getLogger("hermes-lite.discord.runner")

# ~/hermes-lite/ ルート。claude を cwd=ここで起動して CLAUDE.md を自動ロードさせる。
HERMES_HOME = Path(__file__).resolve().parents[2]


# claude -p の生出力を残すログ先。logs/** は gloop guard の allow 対象。
LOG_DIR = HERMES_HOME / "logs" / "discord"


def _log_outcome(
    prompt: str,
    resume_session_id: str | None,
    *,
    stdout: str,
    stderr: str,
    returncode: int,
    timed_out: bool,
    duration: float,
) -> None:
    """claude -p 1 回分の結果を journald へ要約 + logs/discord/<日付>.jsonl へ生出力を残す."""
    session_id = None
    cost_usd = None
    try:
        payload = json.loads(stdout)
        session_id = payload.get("session_id")
        cost_usd = payload.get("total_cost_usd")
    except (json.JSONDecodeError, TypeError):
        pass
    log.info(
        "-p done: rc=%s timed_out=%s dur=%.1fs sid=%s cost=%s stdout=%dB stderr=%dB",
        returncode, timed_out, duration, session_id, cost_usd,
        len(stdout), len(stderr),
    )
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.datetime.now()
        rec = {
            "ts": now.isoformat(timespec="seconds"),
            "resume": resume_session_id,
            "session_id": session_id,
            "returncode": returncode,
            "timed_out": timed_out,
            "duration_sec": round(duration, 1),
            "cost_usd": cost_usd,
            "prompt": prompt[:1000],
            "stdout": stdout,
            "stderr": stderr[:4000],
        }
        with (LOG_DIR / f"{now:%Y-%m-%d}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        log.warning("failed to write -p raw log to %s", LOG_DIR, exc_info=True)

# claude 子プロセスへ渡さない秘密キー（prompt injection 経由の流出を断つ / 秘密の継承カット）。
# lib/approvals_executor.py にも同名の定数がある（gateway と lib の import 独立性のため重複定義）。
_SECRET_ENV_KEYS = frozenset({
    "DISCORD_TOKEN", "DISCORD_WEBHOOK_URL", "ALLOWED_USER_IDS",
    "INPUT_CHANNEL_IDS", "HERMES_APPROVAL_AUTHORIZED_USER_IDS",
    # bot.py が起動時に ALLOWED_USER_IDS のコピーを別名で os.environ に載せるため同様に除外
    "HERMES_APPROVAL_ALLOWED_USER_IDS_FALLBACK",
    # SwitchBot 認証は claude に渡さない。switchbot.py が自力で .env から読む
    # （lib/switchbot.py の _load_dotenv_creds）ため、env で渡す必要がない。
    "SWITCHBOT_TOKEN", "SWITCHBOT_SECRET",
})

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
# SwitchBot 家電操作（Issue #12）: switchbot.py / sb-schedule を headless -p で
# 承認プロンプトなしに叩けるよう prefix allowlist で許可する。
# cwd=~/hermes-lite なので相対パスで呼ぶ前提（SOUL.md / runbook-switchbot.md でその形に誘導）。
ALLOWED_TOOLS = [
    "WebSearch",
    "WebFetch",
    "Bash(python3 lib/switchbot.py:*)",
    "Bash(bin/sb-schedule:*)",
]

# SOUL.md が読めない場合の旧挙動互換用 fallback。
# 中身は旧 APPEND_SYSTEM_PROMPT そのまま（Issue #6 移行時のセーフティネット）。
_DEFAULT_SOUL = (
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

_SOUL_FILE = HERMES_HOME / "SOUL.md"


def _load_soul() -> str:
    try:
        text = _SOUL_FILE.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as e:
        log.warning("SOUL.md not loadable (%s): %s — using built-in default", _SOUL_FILE, e)
        return _DEFAULT_SOUL
    if not text:
        log.warning("SOUL.md is empty (%s) — using built-in default", _SOUL_FILE)
        return _DEFAULT_SOUL
    return text


# 後方互換 alias: 既存 import 互換維持（Issue #6 移行期）
APPEND_SYSTEM_PROMPT = _DEFAULT_SOUL


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
    if MODEL:
        cmd.extend(["--model", MODEL])
    if resume_session_id:
        cmd.extend(["--resume", resume_session_id])
    cmd.extend(["--append-system-prompt", _load_soul()])
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
    # PATH / XDG_RUNTIME_DIR / DBUS_SESSION_BUS_ADDRESS 等は残す（bot 経由ジョブ作成の
    # systemctl --user に必要）。秘密キーだけ denylist で除外する。
    child_env = {k: v for k, v in os.environ.items() if k not in _SECRET_ENV_KEYS}
    child_env["CI"] = "1"
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SEC,
            cwd=str(HERMES_HOME),   # ~/hermes-lite/CLAUDE.md を自動ロードさせる
            env=child_env,
        )
    except subprocess.TimeoutExpired as e:
        _log_outcome(
            prompt, resume_session_id,
            stdout=e.stdout or "", stderr=e.stderr or "",
            returncode=124, timed_out=True,
            duration=time.monotonic() - started,
        )
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
    _log_outcome(
        prompt, resume_session_id,
        stdout=stdout, stderr=stderr,
        returncode=proc.returncode, timed_out=False,
        duration=time.monotonic() - started,
    )

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
