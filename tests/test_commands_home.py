"""Issue #14 `/home`（sb-status 実行）コマンドの自動テスト (Python 標準 unittest).

discord 非依存: `gateway/discord` を sys.path に追加し `commands` パッケージを
直接 import する（既存 test_commands.py と同方式）。
`bin/sb-status` は実行しない — `commands.home.subprocess.run` をモックする。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GATEWAY_DIR = _REPO_ROOT / "gateway" / "discord"
if str(_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(_GATEWAY_DIR))

import commands as slash_commands  # noqa: E402
from commands.help import render_help  # noqa: E402


def _ctx(tmp: Path) -> slash_commands.CommandContext:
    return slash_commands.CommandContext(
        scope_key="dm:1",
        author_id=1,
        sessions_db=tmp / "sessions.sqlite",
        hermes_home=tmp,
    )


class HomeCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_T01_home_success(self) -> None:
        """exit 0・stdout あり → ```plain コードブロックで stdout が返る。

        subprocess.run の呼び出し引数が [.../bin/sb-status]・timeout=20 であること。
        """
        with patch("commands.home.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="OK: all devices\n", stderr=""
            )
            reply = slash_commands.dispatch("/home", _ctx(self.tmp))

        self.assertEqual(reply, "```plain\nOK: all devices\n```")
        args, kwargs = mock_run.call_args
        self.assertEqual(args[0], [str(self.tmp / "bin" / "sb-status")])
        self.assertEqual(kwargs["timeout"], 20)

    def test_T02_home_json_flag(self) -> None:
        """args "--json" → コマンドリストに --json が含まれ、JSON がコードブロックで返る。"""
        with patch("commands.home.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout='{"ok": true}\n', stderr=""
            )
            reply = slash_commands.dispatch("/home --json", _ctx(self.tmp))

        args, kwargs = mock_run.call_args
        self.assertEqual(args[0], [str(self.tmp / "bin" / "sb-status"), "--json"])
        self.assertIn('{"ok": true}', reply)
        self.assertTrue(reply.startswith("```plain\n"))

    def test_T03_home_failure_stderr(self) -> None:
        """exit 1・stdout 空・stderr 複数行 → ⚠️ 行 + stderr の 1 行目のみ。"""
        with patch("commands.home.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="line1 error\nline2 detail\n"
            )
            reply = slash_commands.dispatch("/home", _ctx(self.tmp))

        self.assertEqual(reply, "⚠️ 家電状態の取得に失敗: line1 error")

    def test_T04_home_timeout(self) -> None:
        """subprocess.TimeoutExpired → ⚠️ 家電状態の取得がタイムアウトしました (20s)。"""
        with patch("commands.home.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="sb-status", timeout=20)
            reply = slash_commands.dispatch("/home", _ctx(self.tmp))

        self.assertEqual(reply, "⚠️ 家電状態の取得がタイムアウトしました (20s)")

    def test_T05_home_unknown_args(self) -> None:
        """args "--verbose" → subprocess 未実行（mock 未呼び出し）で使い方メッセージ。"""
        with patch("commands.home.subprocess.run") as mock_run:
            reply = slash_commands.dispatch("/home --verbose", _ctx(self.tmp))

        mock_run.assert_not_called()
        self.assertEqual(reply, "使い方: /home または /home --json")

    def test_T06_home_registered(self) -> None:
        """COMMANDS に home が登録され、render_help 出力に /home が含まれる。"""
        self.assertIn("home", slash_commands.COMMANDS)
        reply = render_help(slash_commands.COMMANDS)
        self.assertIn("/home", reply)

    def test_T07_home_failure_with_stdout(self) -> None:
        """境界: exit 1・stdout 非空（部分失敗）→ ⚠️ 行のみ（stdout は併記しない）。"""
        with patch("commands.home.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="device A: ok\n",
                stderr="device B: timeout\n",
            )
            reply = slash_commands.dispatch("/home", _ctx(self.tmp))

        self.assertEqual(reply, "⚠️ 家電状態の取得に失敗: device B: timeout")
        self.assertNotIn("device A", reply)

    def test_T08_home_args_whitespace(self) -> None:
        """dispatch 経由 "/home   --json  " → --json 実行に正規化される。"""
        with patch("commands.home.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="{}\n", stderr=""
            )
            slash_commands.dispatch("/home   --json  ", _ctx(self.tmp))

        args, kwargs = mock_run.call_args
        self.assertEqual(args[0], [str(self.tmp / "bin" / "sb-status"), "--json"])

    def test_T09_home_stderr_long_line(self) -> None:
        """境界: stderr 1 行目が 500 字 → ⚠️ 行内の stderr 部分が 200 字で切られる。"""
        long_line = "e" * 500
        with patch("commands.home.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr=long_line + "\nmore\n"
            )
            reply = slash_commands.dispatch("/home", _ctx(self.tmp))

        expected = "⚠️ 家電状態の取得に失敗: " + ("e" * 200)
        self.assertEqual(reply, expected)

    def test_T10_home_oserror(self) -> None:
        """OSError（sb-status 不在・実行権限なし等）→ ⚠️ 行にエラー明細。"""
        with patch("commands.home.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Permission denied")
            reply = slash_commands.dispatch("/home", _ctx(self.tmp))

        self.assertTrue(reply.startswith("⚠️ 家電状態の取得に失敗: "))
        self.assertIn("Permission denied", reply)

    def test_T11_home_failure_empty_stderr(self) -> None:
        """境界: exit 非ゼロ・stdout/stderr とも空 → exit code を fallback 表示。"""
        with patch("commands.home.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=3, stdout="", stderr=""
            )
            reply = slash_commands.dispatch("/home", _ctx(self.tmp))

        self.assertEqual(reply, "⚠️ 家電状態の取得に失敗: exit code 3")

    def test_T12_home_decoding_kwargs(self) -> None:
        """subprocess.run に encoding=utf-8 / errors=replace が渡る（不正 UTF-8 で未捕捉例外にしない）。"""
        with patch("commands.home.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok\n", stderr=""
            )
            slash_commands.dispatch("/home", _ctx(self.tmp))

        args, kwargs = mock_run.call_args
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertEqual(kwargs["errors"], "replace")


if __name__ == "__main__":
    unittest.main()
