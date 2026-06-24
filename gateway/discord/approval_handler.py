"""Discord 承認ハンドラ: approval コマンド -> decide -> systemd-run executor.

bot.py から (flag on のときだけ) import される。flag off では import すらされない
(plan v6 §10)。
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time
from typing import Optional

# config を唯一の HERMES_HOME 決定点として参照 (plan v6 §15)
from config import HERMES_HOME, APPROVALS_DB

# lib/approvals を import するため sys.path を補正
_LIB_DIR = HERMES_HOME / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import approvals  # noqa: E402

log = logging.getLogger("hermes-lite.discord.approval")

SYSTEMD_RUN = os.environ.get("HERMES_SYSTEMD_RUN_BIN", "systemd-run")

APPROVAL_RE = re.compile(
    r"^\s*approval\s+(?P<verb>approve|reject)\s+#?(?P<id>[a-f0-9]{8})\s*$",
    re.IGNORECASE,
)


def looks_like_approval(text: str) -> bool:
    return APPROVAL_RE.match(text or "") is not None


def handle(text: str, user_id: int) -> str:
    """approval コマンドを処理し Discord に返す文字列を返す.

    内部認可検証: HERMES_APPROVAL_AUTHORIZED_USER_IDS (+ fallback ALLOWED_USER_IDS)
    に含まれない user_id は拒否する (二重チェック)。
    """
    authorized = approvals.get_authorized_user_ids()
    if user_id not in authorized:
        log.warning("unauthorized approval attempt user_id=%s", user_id)
        return f"⚠️ [WARN] unauthorized user_id={user_id}"

    m = APPROVAL_RE.match(text or "")
    if m is None:
        return "⚠️ [WARN] approval コマンド形式エラー"
    verb = m.group("verb").lower()
    aid = m.group("id").lower()

    row = approvals.get(aid)
    if row is None:
        return f"⚠️ [WARN] #{aid} は不明 (期限切れ or タイポ)"
    if row["status"] != "pending":
        return f"⚠️ [WARN] #{aid} はすでに {row['status']} (重複承認不可)"

    decision = "approve" if verb == "approve" else "reject"
    after = approvals.decide(aid, decision, user_id=user_id)
    if after is None:
        latest = approvals.get(aid)
        if latest and latest["status"] == "expired":
            return f"⚠️ [WARN] #{aid} は期限切れ"
        return f"⚠️ [WARN] #{aid} の decide に失敗 (直前に他経路で遷移済み)"

    if after == "rejected":
        return f"❌ [REJECTED] #{aid} 却下"

    # approve -> systemd-run で executor 起動
    unit = f"hermes-exec-{aid}-{int(time.time())}"
    cmd = [
        SYSTEMD_RUN, "--user", "--no-block",
        f"--unit={unit}",
        f"--working-directory={HERMES_HOME}",
        f"--setenv=HERMES_APPROVAL_ID={aid}",
        f"--setenv=HERMES_HOME={HERMES_HOME}",
        f"--setenv=HERMES_APPROVALS_DB={APPROVALS_DB}",
        f"--setenv=PATH={os.environ.get('PATH', '')}",
    ]
    # webhook URL も executor に渡す (Discord 通知のため)
    if os.environ.get("DISCORD_WEBHOOK_URL"):
        cmd.append(f"--setenv=DISCORD_WEBHOOK_URL={os.environ['DISCORD_WEBHOOK_URL']}")
    # executor のチューニング可能な env を bot 環境から透過的に渡す
    # (Codex final review contrarian H2: systemd-run executor の env 渡し不足対応)
    for _key in (
        "CLAUDE_BIN",
        "HERMES_EXECUTOR_MODEL",
        "HERMES_EXECUTOR_TIMEOUT_SEC",
        "HERMES_EXECUTOR_MAX_BUDGET_USD",
        "HERMES_EXECUTOR_MAX_TURNS",
    ):
        _val = os.environ.get(_key)
        if _val:
            cmd.append(f"--setenv={_key}={_val}")
    cmd.extend([
        "/usr/bin/python3",
        str(HERMES_HOME / "lib" / "approvals_executor.py"),
    ])
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=10)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        err = (getattr(e, "stderr", "") or str(e)).strip()
        try:
            approvals.fail_before_executor(aid, result_text=f"systemd-run failed: {err}")
        except Exception:
            log.exception("fail_before_executor crashed")
        return (
            f"⚠️ [WARN] #{aid} 承認は記録したが executor 起動失敗 -> failed に変更\n"
            f"```\n{err[:400]}\n```"
        )

    return f"✅ [OK] #{aid} 承認 -> executor 起動 (unit={unit})"


def sweep_expired() -> int:
    return approvals.sweep_expired()


def sweep_stale_approved() -> int:
    return approvals.sweep_stale_approved()


def sweep_stale_executing() -> int:
    return approvals.sweep_stale_executing()
