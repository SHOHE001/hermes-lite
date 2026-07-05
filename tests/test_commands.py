"""Issue #13 Discord スラッシュコマンド機構の自動テスト (Python 標準 unittest).

discord 非依存: `gateway/discord` を sys.path に追加し `commands` パッケージを
直接 import する（bot.py 自体は discord.py 依存のためテスト対象外）。
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GATEWAY_DIR = _REPO_ROOT / "gateway" / "discord"
if str(_GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(_GATEWAY_DIR))

import commands as slash_commands  # noqa: E402
from session_store import SessionStore  # noqa: E402


def _ctx(tmp: Path, scope_key: str | None = "dm:1") -> slash_commands.CommandContext:
    return slash_commands.CommandContext(
        scope_key=scope_key,
        author_id=1,
        sessions_db=tmp / "sessions.sqlite",
        hermes_home=tmp,
    )


class DispatchHelpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_T01_dispatch_help(self) -> None:
        reply = slash_commands.dispatch("/help", _ctx(self.tmp))
        self.assertIn("/clear", reply)
        self.assertIn("/status", reply)
        self.assertIn("/help", reply)

    def test_T05_help_lists_all_registry(self) -> None:
        from commands.help import render_help

        reply = render_help(slash_commands.COMMANDS)
        for name in slash_commands.COMMANDS:
            self.assertIn(f"/{name}", reply)


class ClearCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.db_path = self.tmp / "sessions.sqlite"

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_T02_clear_deletes_session(self) -> None:
        scope_key = "dm:42"
        with SessionStore(self.db_path) as store:
            store.set(scope_key, "session-abc")

        with SessionStore(self.db_path) as store:
            self.assertEqual(store.get(scope_key), "session-abc")

        ctx = slash_commands.CommandContext(
            scope_key=scope_key, author_id=42, sessions_db=self.db_path, hermes_home=self.tmp
        )
        reply = slash_commands.dispatch("/clear", ctx)
        self.assertIn("✅", reply)

        with SessionStore(self.db_path) as store:
            self.assertIsNone(store.get(scope_key))

        # 長寿命インスタンス退化: 別接続 delete が WAL 経由で既存の長寿命接続にも反映される
        store_a = SessionStore(self.db_path)
        try:
            store_a.set(scope_key, "session-def")
            self.assertEqual(store_a.get(scope_key), "session-def")
            reply2 = slash_commands.dispatch("/clear", ctx)
            self.assertIn("✅", reply2)
            self.assertIsNone(store_a.get(scope_key))
        finally:
            store_a.close()

    def test_T03_clear_no_scope(self) -> None:
        ctx = slash_commands.CommandContext(
            scope_key=None, author_id=1, sessions_db=self.db_path, hermes_home=self.tmp
        )
        reply = slash_commands.dispatch("/clear", ctx)
        self.assertIn("ℹ️", reply)
        # DB 未変更: そもそも DB ファイルすら作られていないはず
        self.assertFalse(self.db_path.exists())


class UnknownAndErrorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_T04_unknown_command(self) -> None:
        reply = slash_commands.dispatch("/foobar", _ctx(self.tmp))
        self.assertIn("❓", reply)
        self.assertIn("/help", reply)
        self.assertEqual(reply, slash_commands.UNKNOWN_COMMAND_MESSAGE)

    def test_T06_handler_exception_fixed(self) -> None:
        def _boom(ctx, args):
            raise RuntimeError("boom")

        custom_registry = dict(slash_commands.COMMANDS)
        custom_registry["boom"] = slash_commands.Command("boom", "raises", _boom)

        original_keys = set(slash_commands.COMMANDS.keys())
        reply = slash_commands.dispatch("/boom", _ctx(self.tmp), registry=custom_registry)
        self.assertEqual(reply, slash_commands.COMMAND_ERROR_MESSAGE)
        # global COMMANDS は不変
        self.assertEqual(set(slash_commands.COMMANDS.keys()), original_keys)
        self.assertNotIn("boom", slash_commands.COMMANDS)


class StatusCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _write_loop_state(self, cycle: int = 12, pause_reason: str | None = None) -> None:
        loop_dir = self.tmp / "features" / ".loop"
        loop_dir.mkdir(parents=True, exist_ok=True)
        (loop_dir / "state.json").write_text(
            json.dumps(
                {
                    "cycle": cycle,
                    "recent_cycles": [{"cycle": cycle, "pause_reason": pause_reason}],
                }
            ),
            encoding="utf-8",
        )

    def test_T07_status_renders_cycle(self) -> None:
        self._write_loop_state(cycle=12)
        reply = slash_commands.dispatch("/status", _ctx(self.tmp))
        self.assertIn("12", reply)
        self.assertIn("cycle", reply)

    def test_T08_status_missing_files(self) -> None:
        # tmp は空: state.json / tmux-state.json / logs いずれも無し
        reply = slash_commands.dispatch("/status", _ctx(self.tmp))
        self.assertIn("N/A", reply)

    def test_T11_status_skips_broken_json(self) -> None:
        logs_dir = self.tmp / "logs"
        (logs_dir / "x").mkdir(parents=True)
        (logs_dir / "y").mkdir(parents=True)
        broken = logs_dir / "x" / "broken.json"
        broken.write_text("{not valid json", encoding="utf-8")
        good = logs_dir / "y" / "good.json"
        good.write_text(json.dumps({"result": "all good"}), encoding="utf-8")
        # broken を good より新しくして mtime 降順でも good が採用されることを確認
        now = time.time()
        import os

        os.utime(good, (now, now))
        os.utime(broken, (now + 10, now + 10))

        reply = slash_commands.dispatch("/status", _ctx(self.tmp))
        self.assertIn("good", reply)
        self.assertNotIn("N/A", reply.split("直近ジョブ:")[-1])

    def test_T12_status_ignores_jsonl(self) -> None:
        logs_dir = self.tmp / "logs" / "discord"
        logs_dir.mkdir(parents=True)
        (logs_dir / "2026-07-05.jsonl").write_text(
            json.dumps({"result": "should be ignored"}), encoding="utf-8"
        )
        reply = slash_commands.dispatch("/status", _ctx(self.tmp))
        self.assertIn("N/A", reply.split("直近ジョブ:")[-1])


class IsCommandParseTest(unittest.TestCase):
    def test_T09_is_command_true_false(self) -> None:
        self.assertTrue(slash_commands.is_command("/help"))
        self.assertFalse(slash_commands.is_command("hello"))
        self.assertIsNone(slash_commands.parse("hello"))

    def test_T10_parse_slash_with_args(self) -> None:
        self.assertEqual(slash_commands.parse("/status verbose"), ("status", "verbose"))

    def test_T10b_dispatch_passes_args(self) -> None:
        received = {}

        def _echo(ctx, args):
            received["args"] = args
            return "ok"

        registry = dict(slash_commands.COMMANDS)
        registry["echo"] = slash_commands.Command("echo", "echo args", _echo)
        with tempfile.TemporaryDirectory() as tmpdir:
            slash_commands.dispatch("/echo verbose", _ctx(Path(tmpdir)), registry=registry)
        self.assertEqual(received["args"], "verbose")

    def test_T13_slash_namespace_boundary(self) -> None:
        for content in ("/tmp/foo", "//x", "/ 相談", "/?", "/"):
            self.assertFalse(slash_commands.is_command(content), msg=content)
        for content in ("/clear", "/a-b_c"):
            self.assertTrue(slash_commands.is_command(content), msg=content)

    def test_T15_parse_trailing_ws(self) -> None:
        self.assertEqual(slash_commands.parse("/help   "), ("help", ""))
        self.assertEqual(slash_commands.parse("/status  verbose "), ("status", "verbose"))


class ClassifyTest(unittest.TestCase):
    def test_T14_classify_routing_order(self) -> None:
        self.assertEqual(
            slash_commands.classify("approval approve #abcd1234", True), "approval"
        )
        self.assertEqual(slash_commands.classify("/clear", False), "slash")
        self.assertEqual(slash_commands.classify("hello", False), "handle")
        self.assertEqual(slash_commands.classify("/tmp/foo", False), "handle")


class ImportSafetyTest(unittest.TestCase):
    def test_T16_import_safe_no_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            # 任意 cwd / gloop ファイル不在の tmpdir を hermes_home にしても
            # import 自体（= registry 構築）は成功済みであるはずで、/help も返る
            import importlib

            importlib.reload(slash_commands)
            ctx = slash_commands.CommandContext(
                scope_key=None, author_id=1, sessions_db=tmp / "sessions.sqlite", hermes_home=tmp
            )
            reply = slash_commands.dispatch("/help", ctx)
            self.assertIn("/help", reply)


if __name__ == "__main__":
    unittest.main()
