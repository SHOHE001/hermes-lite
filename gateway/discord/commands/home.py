"""`/home` — `bin/sb-status` を subprocess 実行し、家電状態一覧を返す。

module top は stdlib のみ import する（import 時 IO なしを status.py と
同じく徹底する）。依存する契約は sb-status の CLI 公開契約
（exit code / stdout / stderr）のみで、内部関数構造には依存しない。
"""
from __future__ import annotations

import subprocess

from .types import CommandContext

TIMEOUT_SEC = 20
SB_STATUS_REL = ("bin", "sb-status")
_ERR_MAX_LEN = 200

_USAGE_MESSAGE = "使い方: /home または /home --json"


def home_handler(ctx: CommandContext, args: str) -> str:
    args = args.strip()
    if args == "":
        extra: list[str] = []
    elif args == "--json":
        extra = ["--json"]
    else:
        return _USAGE_MESSAGE

    sb_status_path = ctx.hermes_home.joinpath(*SB_STATUS_REL)

    try:
        result = subprocess.run(
            [str(sb_status_path), *extra],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_SEC,
            cwd=ctx.hermes_home,
        )
    except subprocess.TimeoutExpired:
        return "⚠️ 家電状態の取得がタイムアウトしました (20s)"
    except OSError as exc:
        return f"⚠️ 家電状態の取得に失敗: {str(exc)[:_ERR_MAX_LEN]}"

    if result.returncode != 0:
        stderr_first_line = result.stderr.splitlines()[0] if result.stderr else ""
        detail = stderr_first_line[:_ERR_MAX_LEN] or f"exit code {result.returncode}"
        return f"⚠️ 家電状態の取得に失敗: {detail}"

    body = result.stdout.rstrip("\n")
    return f"```plain\n{body}\n```"
