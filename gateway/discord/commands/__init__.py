"""gateway/discord 専用のローカルコマンド層。

依存方向は `__init__.py` → 各 handler モジュールの一方向のみ。
handler モジュールは本 `__init__`（＝ `COMMANDS`）を import しない。

`dispatch` / `classify` は gateway 内部 API（安定公開 API ではない）。
呼び出しは bot.py の on_message のみを想定する。
"""
from __future__ import annotations

import logging
import re
from typing import Literal

from .types import (
    CommandContext,
    Command,
    UNKNOWN_COMMAND_MESSAGE,
    COMMAND_ERROR_MESSAGE,
)
from . import clear, status, help as help_mod, home   # __init__ → handlers（一方向）

log = logging.getLogger("hermes-lite.discord.commands")

_COMMAND_RE = re.compile(r"^/([A-Za-z][A-Za-z0-9_-]*)(?:\s+(.*))?$", re.DOTALL)

COMMANDS: dict[str, Command] = {}
COMMANDS["clear"] = Command("clear", "セッションをクリア", clear.clear_handler)
COMMANDS["status"] = Command("status", "gloop の状態を表示", status.status_handler)
COMMANDS["home"] = Command("home", "家電の状態一覧", home.home_handler)
COMMANDS["help"] = Command(
    "help", "コマンド一覧を表示", lambda ctx, args: help_mod.render_help(COMMANDS)
)

Route = Literal["approval", "slash", "handle"]


def is_command(stripped: str) -> bool:
    return _COMMAND_RE.match(stripped) is not None


def parse(content: str) -> tuple[str, str] | None:
    m = _COMMAND_RE.match(content)
    if not m:
        return None
    # args は strip して返す（"/help   " -> ("help",""), "/status verbose" -> ("status","verbose")）
    return m.group(1), (m.group(2) or "").strip()


def classify(stripped: str, approval_match: bool) -> Route:
    """_strip_mention 済みの content を route に分類（優先順位: approval > slash > handle）。

    discord 非依存の低レベル route chooser。approval の有効条件は呼び出し側で
    approval_match に畳む。
    """
    if approval_match:
        return "approval"
    if is_command(stripped):
        return "slash"
    return "handle"


def dispatch(content: str, ctx: CommandContext, registry: dict[str, Command] | None = None) -> str:
    registry = registry if registry is not None else COMMANDS   # 注入可能 → global 非汚染
    parsed = parse(content)
    if parsed is None:
        # 契約: bot は is_command 済みの入力のみ dispatch する。
        # ここに来るのは契約違反（内部バグ）なので UNKNOWN ではなく内部エラー扱い。
        log.error("dispatch called with non-command content: %r", content[:80])
        return COMMAND_ERROR_MESSAGE
    name, args = parsed
    cmd = registry.get(name)
    if cmd is None:
        return UNKNOWN_COMMAND_MESSAGE                            # UNKNOWN は「解析成功だが未登録」に限定
    try:
        return cmd.handler(ctx, args)
    except Exception:
        log.exception("command handler failed: %s", name)        # 詳細は journalctl のみ
        return COMMAND_ERROR_MESSAGE                              # Discord には固定文言
