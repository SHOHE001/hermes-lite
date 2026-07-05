"""`/clear` — セッションをクリアする（sqlite 行削除のみ、旧 JSONL には触れない）。

module top は stdlib のみ import する（import 時 IO なしを徹底）。
`SessionStore` は `session_store.py` に設定読込や DB 初期化が将来追加されても
`import commands`（bot 起動）を単一障害点にしないよう、handler 内で遅延 import する。
"""
from __future__ import annotations

from .types import CommandContext


def clear_handler(ctx: CommandContext, args: str) -> str:
    if ctx.scope_key is None:
        return "ℹ️ このスコープはセッション継続対象外です"
    from session_store import SessionStore          # 遅延 import（clear.py の module top を stdlib のみに）

    with SessionStore(ctx.sessions_db) as store:     # worker thread 内の短命接続（__exit__ で close）
        store.delete(ctx.scope_key)                  # 冪等
    return "✅ セッションをクリアしました（次の発話から新規セッション）"
