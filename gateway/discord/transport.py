"""Discord transport 制約（メッセージ長）まわりの純粋ユーティリティ。

discord.py にも config にも依存しない（stdlib のみ・import 時 IO なし・
fake send で unittest 可能な境界）。実際の limit は呼び出し側 bot.py が
config.MAX_DISCORD_MESSAGE を渡して注入する。
例外ハンドリング（discord.HTTPException 等）は呼び出し側 bot.py の責務。
"""
from __future__ import annotations

from typing import Awaitable, Callable

# config.MAX_DISCORD_MESSAGE と同値のフォールバック。config には依存しない
# （transport を実行環境の env 初期化から切り離すため）。
DEFAULT_MESSAGE_LIMIT = 1900


def split_for_discord(text: str, limit: int = DEFAULT_MESSAGE_LIMIT) -> list[str]:
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    if rest:
        chunks.append(rest)
    return chunks


async def send_chunks(send: Callable[[str], Awaitable[object]], text: str,
                      limit: int = DEFAULT_MESSAGE_LIMIT) -> int:
    """text を分割して send を順に await する。送信したチャンク数を返す。

    途中の send が例外を投げたらそのまま伝播する（部分送信は呼び出し側が
    warning ログで扱う — 既存 slash 経路の except 構造を維持）。
    """
    chunks = split_for_discord(text, limit)
    for chunk in chunks:
        await send(chunk)
    return len(chunks)
