from __future__ import annotations

import os
from pathlib import Path


def _parse_ids(raw: str) -> list[int]:
    return [int(x) for x in (s.strip() for s in raw.split(",")) if x]


HOME = Path.home()
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "").strip()
ALLOWED_USER_IDS: list[int] = _parse_ids(os.environ.get("ALLOWED_USER_IDS", ""))
# 「指定チャンネルの全メッセージにも反応」モード用。空なら DM/Thread/@mention のみ。
INPUT_CHANNEL_IDS: list[int] = _parse_ids(os.environ.get("INPUT_CHANNEL_IDS", ""))
TIMEOUT_SEC = int(os.environ.get("HERMES_DISCORD_TIMEOUT_SEC", "300"))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", str(HOME / ".local" / "bin" / "claude"))

SESSIONS_DB = Path(__file__).with_name("sessions.sqlite")

MAX_DISCORD_MESSAGE = 1900  # 2000 制限から余白

# --- 承認ゲート (Issue #3) ---
# config.py を HERMES_HOME / APPROVALS_DB の唯一の決定点とする (plan v6)
HERMES_HOME = Path(os.environ.get(
    "HERMES_HOME",
    str(Path(__file__).resolve().parents[2]),
))
APPROVALS_DB = Path(os.environ.get(
    "HERMES_APPROVALS_DB",
    str(HERMES_HOME / "var" / "approvals.sqlite"),
))
# feature flag: default "0" (opt-in)。"1" のときのみ approval 経路を有効化。
APPROVAL_COMMANDS_ENABLED = os.environ.get("HERMES_APPROVAL_COMMANDS_ENABLED", "0") == "1"
