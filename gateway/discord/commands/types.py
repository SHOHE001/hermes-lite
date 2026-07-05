"""commands パッケージの型・定数（leaf module）。

stdlib のみに依存し、`__init__` や各 handler モジュールを一切 import しない。
これにより handler が `CommandContext` を型注釈で使いつつも `__init__` を
import しない構成が成り立ち、循環 import を起こさない。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

UNKNOWN_COMMAND_MESSAGE = "❓ 未知のコマンド。/help で一覧を確認できます"
COMMAND_ERROR_MESSAGE = "⚠️ コマンド実行に失敗しました（詳細は journalctl 参照）"


@dataclass(frozen=True)
class CommandContext:
    scope_key: str | None      # bot._scope_key(message) の結果（None = セッション継続対象外スコープ）
    author_id: int             # 呼び出しユーザー（将来のコマンド別権限用に受けるだけ）
    sessions_db: Path          # live store ではなく sqlite ファイルパスを注入
    hermes_home: Path          # /status がファイルを読む基点


@dataclass(frozen=True)
class Command:
    name: str                                       # "clear"（先頭 / なし）
    summary: str                                    # /help 用の一行説明
    handler: Callable[["CommandContext", str], str]  # handler は (ctx, args) を受ける
