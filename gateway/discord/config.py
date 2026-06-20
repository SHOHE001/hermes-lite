from __future__ import annotations

import os
from pathlib import Path


def _parse_ids(raw: str) -> list[int]:
    return [int(x) for x in (s.strip() for s in raw.split(",")) if x]


HOME = Path.home()
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "").strip()
ALLOWED_USER_IDS: list[int] = _parse_ids(os.environ.get("ALLOWED_USER_IDS", ""))
TIMEOUT_SEC = int(os.environ.get("HERMES_DISCORD_TIMEOUT_SEC", "300"))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", str(HOME / ".local" / "bin" / "claude"))

SESSIONS_DB = Path(__file__).with_name("sessions.sqlite")

MAX_DISCORD_MESSAGE = 1900  # 2000 制限から余白
