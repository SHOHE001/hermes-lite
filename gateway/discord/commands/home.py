"""`/home` — 家電の状態一覧を返す（bin/sb-status を subprocess で実行）。

claude -p を介さず bot が直接 CLI を叩くため、応答は SwitchBot API のレイテンシ
（数百 ms × 3 リクエスト）のみで完結する。Issue #14。

引数:
    `/home`         人間可読で全機器
    `/home --json`  JSON でまとめて（機械処理向け）

タイムアウトは 20 秒（SwitchBot API 3 リクエスト分の余裕）。
"""
from __future__ import annotations

import logging
import shlex
import subprocess

from .types import CommandContext

log = logging.getLogger("hermes-lite.discord.commands.home")

_TIMEOUT_SEC = 20
_ALLOWED_ARGS = {"", "--json"}


def home_handler(ctx: CommandContext, args: str) -> str:
    arg = args.strip()
    if arg not in _ALLOWED_ARGS:
        return "❓ 使い方: `/home` または `/home --json`"

    cmd = [str(ctx.hermes_home / "bin" / "sb-status")]
    if arg:
        cmd += shlex.split(arg)

    try:
        proc = subprocess.run(
            cmd,
            cwd=ctx.hermes_home,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return f"⚠️ 家電状態の取得がタイムアウトしました ({_TIMEOUT_SEC}s)"
    except FileNotFoundError:
        log.error("bin/sb-status not found at %s", cmd[0])
        return "⚠️ 家電状態の取得に失敗: bin/sb-status が見つかりません"

    if proc.returncode != 0:
        first_err = (proc.stderr or "").splitlines()[0] if proc.stderr else "(no stderr)"
        return f"⚠️ 家電状態の取得に失敗: {first_err[:200]}"

    out = (proc.stdout or "").rstrip()
    if not out:
        return "⚠️ 家電状態の取得に失敗: 出力が空でした"
    return f"```\n{out}\n```"
