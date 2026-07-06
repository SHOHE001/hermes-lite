"""Issue #14 gateway/discord/transport.py（分割送信ユーティリティ）の自動テスト.

transport.py は discord.py にも config にも依存しない設計（plan.md 参照）。
fake send（呼び出しを記録する async 関数）で unittest.IsolatedAsyncioTestCase により検証する。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GATEWAY_DIR = _REPO_ROOT / "gateway" / "discord"
if str(_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(_GATEWAY_DIR))

import transport  # noqa: E402


class _FakeSend:
    """呼び出しを記録する async 関数（fake send）。"""

    def __init__(self, fail_at: int | None = None) -> None:
        self.calls: list[str] = []
        self._fail_at = fail_at  # 0-origin index。この回の呼び出しで例外を送出する

    async def __call__(self, chunk: str) -> None:
        if self._fail_at is not None and len(self.calls) == self._fail_at:
            self.calls.append(chunk)  # 送信「試行」は記録してから例外にする
            raise RuntimeError("send failed")
        self.calls.append(chunk)


class SendChunksTest(unittest.IsolatedAsyncioTestCase):
    async def test_T10_send_chunks_short(self) -> None:
        """1900 字以下 → send が 1 回だけ呼ばれ内容が完全一致（既存 slash 挙動不変）。"""
        fake = _FakeSend()
        text = "a" * 100
        count = await transport.send_chunks(fake, text, transport.DEFAULT_MESSAGE_LIMIT)

        self.assertEqual(count, 1)
        self.assertEqual(fake.calls, [text])

    async def test_T11_send_chunks_long(self) -> None:
        """境界: 5000 字・改行入り → 複数回・順に send、各チャンク <= limit。

        内容保持契約: 改行以外の全文字が順序どおり保持され、失われるのは
        チャンク境界の改行のみ。
        """
        fake = _FakeSend()
        text = "\n".join(f"line-{i:04d}" for i in range(500))  # 5000+ 字・改行多数
        limit = 1900
        count = await transport.send_chunks(fake, text, limit)

        self.assertEqual(count, len(fake.calls))
        self.assertGreater(count, 1)
        for chunk in fake.calls:
            self.assertLessEqual(len(chunk), limit)

        joined = "".join(fake.calls)
        # 元テキストから改行を全部除いたものと、送信済みチャンクを連結して
        # 改行を除いたものが一致すること（境界改行のみが失われる契約）。
        self.assertEqual(joined.replace("\n", ""), text.replace("\n", ""))

    async def test_T12_send_chunks_midway_failure(self) -> None:
        """境界: 2 チャンク目の send が例外 → 例外伝播、1 チャンク目は送信済み。"""
        text = "\n".join(f"line-{i:04d}" for i in range(500))
        fake = _FakeSend(fail_at=1)

        with self.assertRaises(RuntimeError):
            await transport.send_chunks(fake, text, 1900)

        self.assertEqual(len(fake.calls), 2)  # 1回目成功 + 2回目（失敗した試行）


class SplitForDiscordTest(unittest.TestCase):
    def test_T13_split_for_discord_parity(self) -> None:
        """移設した split_for_discord が bot.py 旧実装と同じ分割仕様であること。

        改行位置優先・limit 超過時は強制切断・境界改行の lstrip。
        """
        # 空文字列
        self.assertEqual(transport.split_for_discord(""), [])

        # limit 以下はそのまま1チャンク
        short = "hello"
        self.assertEqual(transport.split_for_discord(short, limit=10), [short])

        # 改行位置優先の分割
        text = "a" * 5 + "\n" + "b" * 5
        chunks = transport.split_for_discord(text, limit=6)
        self.assertEqual(chunks, ["a" * 5, "b" * 5])

        # 改行が見つからない場合は limit で強制切断
        text2 = "x" * 20
        chunks2 = transport.split_for_discord(text2, limit=6)
        self.assertEqual(chunks2, ["x" * 6, "x" * 6, "x" * 6, "x" * 2])


if __name__ == "__main__":
    unittest.main()
