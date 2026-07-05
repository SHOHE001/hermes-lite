"""`/help` — レジストリからコマンド一覧を自動生成する。

package (`commands/__init__.py`) を import しない純粋関数のみを持つ
（`__init__` → `help` の一方向依存を守り、循環 import を避ける）。
"""
from __future__ import annotations

from .types import Command


def render_help(registry: dict[str, Command]) -> str:
    lines = [f"/{cmd.name} — {cmd.summary}" for cmd in registry.values()]
    body = "\n".join(lines)
    return f"利用可能なコマンド:\n```\n{body}\n```"
