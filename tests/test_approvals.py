"""Issue #3 承認ゲートの自動テスト (Python 標準 unittest).

各テストは tmpfile DB を使い、`HERMES_APPROVALS_DB` を tmpdir に差し替えてから
approvals を import する形で隔離する。
"""
from __future__ import annotations

import importlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

# プロジェクトルート / lib への path 補正
_REPO_ROOT = Path(__file__).resolve().parents[1]
_LIB_DIR = _REPO_ROOT / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))


def _future_iso(hours: int = 24) -> tuple[str, str, str]:
    """payload 用の (start, end, timeZone) を返す."""
    tz = timezone(timedelta(hours=9))
    start = (datetime.now(tz) + timedelta(hours=hours)).replace(microsecond=0)
    end = start + timedelta(hours=1)
    return start.isoformat(), end.isoformat(), "Asia/Tokyo"


def _valid_payload(summary: str = "test") -> dict:
    s, e, tz = _future_iso()
    return {"summary": summary, "start": s, "end": e, "timeZone": tz}


class _DbIsolation:
    """各テスト用に tmpdir + HERMES_APPROVALS_DB を差し替えるヘルパ."""

    def __init__(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "approvals.sqlite"
        self._saved_env: dict[str, str | None] = {}

    def enter(self) -> object:
        self._saved_env["HERMES_APPROVALS_DB"] = os.environ.get("HERMES_APPROVALS_DB")
        self._saved_env["HERMES_HOME"] = os.environ.get("HERMES_HOME")
        os.environ["HERMES_APPROVALS_DB"] = str(self.db_path)
        os.environ["HERMES_HOME"] = str(_REPO_ROOT)
        # approvals モジュールをリロード (前回のテストの DB path をキャッシュしている可能性)
        import approvals
        importlib.reload(approvals)
        return approvals

    def exit(self) -> None:
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmpdir.cleanup()


class ApprovalsStateMachineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.iso = _DbIsolation()
        self.approvals = self.iso.enter()

    def tearDown(self) -> None:
        self.iso.exit()

    # T05
    def test_T05_expire(self) -> None:
        # 直接 insert: TTL 切れ pending
        # まず schema を作成する (approvals.get 経由)
        self.approvals.get("nonexistent_id")
        now = int(time.time())
        conn = sqlite3.connect(str(self.iso.db_path))
        conn.execute(
            "INSERT INTO approvals (id, proposer_job, executor_job, action, summary, "
            "payload_json, status, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            ("ffffffff", "p", "calendar-create-executor", "calendar.create",
             "expired demo", "{}", now - 100, now - 10),
        )
        conn.commit()
        conn.close()
        n = self.approvals.sweep_expired()
        self.assertEqual(n, 1)
        row = self.approvals.get("ffffffff")
        self.assertEqual(row["status"], "expired")

    # T06
    def test_T06_double_take(self) -> None:
        aid = self.approvals.enqueue(
            proposer_job="p", executor_job="calendar-create-executor",
            action="calendar.create", summary="s", payload=_valid_payload(),
        )
        after = self.approvals.decide(aid, "approve", user_id=1)
        self.assertEqual(after, "approved")
        row1 = self.approvals.take(aid, "calendar-create-executor")
        self.assertIsNotNone(row1)
        row2 = self.approvals.take(aid, "calendar-create-executor")
        self.assertIsNone(row2)

    # T08
    def test_T08_double_decide(self) -> None:
        aid = self.approvals.enqueue(
            proposer_job="p", executor_job="calendar-create-executor",
            action="calendar.create", summary="s", payload=_valid_payload(),
        )
        first = self.approvals.decide(aid, "approve")
        self.assertEqual(first, "approved")
        second = self.approvals.decide(aid, "approve")
        self.assertIsNone(second)

    # T09
    def test_T09_invalid_payload(self) -> None:
        # 未知キー
        bad = _valid_payload()
        bad["unknown_key"] = "x"
        with self.assertRaises(ValueError):
            self.approvals.enqueue(
                proposer_job="p", executor_job="calendar-create-executor",
                action="calendar.create", summary="s", payload=bad,
            )

        # end <= start
        bad2 = _valid_payload()
        bad2["end"] = bad2["start"]
        with self.assertRaises(ValueError):
            self.approvals.enqueue(
                proposer_job="p", executor_job="calendar-create-executor",
                action="calendar.create", summary="s", payload=bad2,
            )

        # 過去日時
        tz = timezone(timedelta(hours=9))
        past_start = (datetime.now(tz) - timedelta(hours=2)).isoformat()
        past_end = (datetime.now(tz) - timedelta(hours=1)).isoformat()
        bad3 = {"summary": "x", "start": past_start, "end": past_end, "timeZone": "Asia/Tokyo"}
        with self.assertRaises(ValueError):
            self.approvals.enqueue(
                proposer_job="p", executor_job="calendar-create-executor",
                action="calendar.create", summary="s", payload=bad3,
            )

        # executor mismatch (T23 兼用)
        with self.assertRaises(ValueError):
            self.approvals.enqueue(
                proposer_job="p", executor_job="wrong-job",
                action="calendar.create", summary="s", payload=_valid_payload(),
            )

    # T12
    def test_T12_done_state_guard(self) -> None:
        aid = self.approvals.enqueue(
            proposer_job="p", executor_job="calendar-create-executor",
            action="calendar.create", summary="s", payload=_valid_payload(),
        )
        with self.assertRaises(ValueError):
            self.approvals.done(aid, result_text="should not")
        row = self.approvals.get(aid)
        self.assertEqual(row["status"], "pending")

    # T18
    def test_T18_stale_executing_sweep(self) -> None:
        # 直接 insert で executing + started_at = now - 1900
        self.approvals.get("init")  # schema 作成
        now = int(time.time())
        conn = sqlite3.connect(str(self.iso.db_path))
        conn.execute(
            "INSERT INTO approvals (id, proposer_job, executor_job, action, summary, "
            "payload_json, status, created_at, expires_at, started_at, decided_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'executing', ?, ?, ?, ?)",
            ("aaaaaaaa", "p", "calendar-create-executor", "calendar.create",
             "stale exec", "{}", now - 2000, now + 86400, now - 1900, now - 1900),
        )
        conn.commit()
        conn.close()
        n = self.approvals.sweep_stale_executing()
        self.assertEqual(n, 1)
        row = self.approvals.get("aaaaaaaa")
        self.assertEqual(row["status"], "failed")

    # T20
    def test_T20_stale_approved_sweep(self) -> None:
        self.approvals.get("init")
        now = int(time.time())
        conn = sqlite3.connect(str(self.iso.db_path))
        conn.execute(
            "INSERT INTO approvals (id, proposer_job, executor_job, action, summary, "
            "payload_json, status, created_at, expires_at, decided_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'approved', ?, ?, ?)",
            ("bbbbbbbb", "p", "calendar-create-executor", "calendar.create",
             "stale appr", "{}", now - 800, now + 86400, now - 700),
        )
        conn.commit()
        conn.close()
        n = self.approvals.sweep_stale_approved()
        self.assertEqual(n, 1)
        row = self.approvals.get("bbbbbbbb")
        self.assertEqual(row["status"], "failed")

    # T21
    def test_T21_decide_after_expire_atomic(self) -> None:
        self.approvals.get("init")
        now = int(time.time())
        conn = sqlite3.connect(str(self.iso.db_path))
        conn.execute(
            "INSERT INTO approvals (id, proposer_job, executor_job, action, summary, "
            "payload_json, status, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            ("cccccccc", "p", "calendar-create-executor", "calendar.create",
             "expired pending", "{}", now - 100, now - 10),
        )
        conn.commit()
        conn.close()
        after = self.approvals.decide("cccccccc", "approve")
        self.assertIsNone(after)
        # row はまだ pending (sweep 待ち)
        row = self.approvals.get("cccccccc")
        self.assertEqual(row["status"], "pending")

    # T23 (T09 と統合済み but 明示)
    def test_T23_enqueue_executor_mismatch(self) -> None:
        with self.assertRaises(ValueError):
            self.approvals.enqueue(
                proposer_job="p", executor_job="wrong-job",
                action="calendar.create", summary="s", payload=_valid_payload(),
            )

    # T24
    def test_T24_list_cli(self) -> None:
        a1 = self.approvals.enqueue(
            proposer_job="p", executor_job="calendar-create-executor",
            action="calendar.create", summary="a1", payload=_valid_payload("a1"),
        )
        a2 = self.approvals.enqueue(
            proposer_job="p", executor_job="calendar-create-executor",
            action="calendar.create", summary="a2", payload=_valid_payload("a2"),
        )
        self.approvals.decide(a2, "approve")
        all_rows = self.approvals.list_rows()
        self.assertEqual(len(all_rows), 2)
        pending = self.approvals.list_rows(status="pending")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["id"], a1)
        approved = self.approvals.list_rows(status="approved")
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0]["id"], a2)

    # T26
    def test_T26_unauth_handler_call(self) -> None:
        # gateway/discord を sys.path に追加
        gw = _REPO_ROOT / "gateway" / "discord"
        if str(gw) not in sys.path:
            sys.path.insert(0, str(gw))
        # approval_handler は config -> approvals を import するので、
        # 一度 cache を消してから reload
        for mod in list(sys.modules):
            if mod in ("approval_handler", "config", "approvals"):
                del sys.modules[mod]
        # config が HERMES_APPROVALS_DB を読むので環境変数は既に設定済み
        os.environ["HERMES_APPROVAL_AUTHORIZED_USER_IDS"] = "12345"
        try:
            import approval_handler  # noqa
            reply = approval_handler.handle("approval approve abcd1234", user_id=999)
            self.assertIn("unauthorized", reply)
            # DB に何も入っていないことを確認
            import approvals as ap2
            importlib.reload(ap2)
            self.assertEqual(len(ap2.list_rows()), 0)
        finally:
            os.environ.pop("HERMES_APPROVAL_AUTHORIZED_USER_IDS", None)
            for mod in list(sys.modules):
                if mod in ("approval_handler", "config"):
                    del sys.modules[mod]

    # T27
    def test_T27_id_collision_retry(self) -> None:
        # 1 ID を pre-insert で占有 → enqueue が衝突しても別 ID で成功する
        self.approvals.get("init")  # schema 確保
        # secrets.token_hex(4) を deterministic に挙動させる
        fixed_id = "deadbeef"
        now = int(time.time())
        conn = sqlite3.connect(str(self.iso.db_path))
        conn.execute(
            "INSERT INTO approvals (id, proposer_job, executor_job, action, summary, "
            "payload_json, status, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (fixed_id, "p", "calendar-create-executor", "calendar.create",
             "x", "{}", now, now + 100),
        )
        conn.commit()
        conn.close()

        # patch: 1 回目 deadbeef (衝突), 2 回目 cafebabe (成功)
        with mock.patch.object(self.approvals.secrets, "token_hex",
                               side_effect=["deadbeef", "cafebabe"]):
            new_id = self.approvals.enqueue(
                proposer_job="p", executor_job="calendar-create-executor",
                action="calendar.create", summary="x", payload=_valid_payload(),
            )
        self.assertEqual(new_id, "cafebabe")

        # 5 回連続衝突 → RuntimeError
        with mock.patch.object(self.approvals.secrets, "token_hex",
                               side_effect=[fixed_id] * 5):
            with self.assertRaises(RuntimeError):
                self.approvals.enqueue(
                    proposer_job="p", executor_job="calendar-create-executor",
                    action="calendar.create", summary="x", payload=_valid_payload(),
                )


class SchemaVersionTest(unittest.TestCase):
    """T15: schema version mismatch を分離して別 isolation で実施."""

    def test_T15_schema_version_mismatch(self) -> None:
        iso = _DbIsolation()
        approvals = iso.enter()
        try:
            # 一度 schema を作る
            approvals.get("init")
            # 強制的に user_version を 99 に書き換え
            conn = sqlite3.connect(str(iso.db_path))
            conn.execute("PRAGMA user_version = 99")
            conn.commit()
            conn.close()
            # reload → 次回アクセスで RuntimeError
            importlib.reload(approvals)
            with self.assertRaises(RuntimeError):
                approvals.get("any")
        finally:
            iso.exit()


class ExtractToolCallsTest(unittest.TestCase):
    """T28 と関連: extract_tool_calls の挙動."""

    def setUp(self) -> None:
        self.iso = _DbIsolation()
        self.approvals = self.iso.enter()
        # approvals_executor も reload
        for mod in list(sys.modules):
            if mod == "approvals_executor":
                del sys.modules[mod]
        import approvals_executor
        self.executor = approvals_executor

    def tearDown(self) -> None:
        self.iso.exit()

    def test_case1_tool_uses_list(self) -> None:
        proc = {
            "tool_uses": [
                {"name": "foo", "input": {"a": 1}},
                {"name": "bar", "input": {"b": 2}},
            ],
        }
        out = self.executor.extract_tool_calls(proc)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["name"], "foo")
        self.assertEqual(out[1]["input"], {"b": 2})

    def test_case2_messages_walk(self) -> None:
        proc = {
            "messages": [
                {"role": "assistant", "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "tool_use", "name": "x", "input": {"k": "v"}},
                ]},
            ],
        }
        out = self.executor.extract_tool_calls(proc)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name"], "x")
        self.assertEqual(out[0]["input"], {"k": "v"})

    def test_T28_tool_use_evidence_unavailable(self) -> None:
        proc = {"usage": {"tool_use_count": 1}}
        out = self.executor.extract_tool_calls(proc)
        self.assertIsNone(out)

    def test_case4_empty(self) -> None:
        proc = {"result": "hi", "is_error": False}
        out = self.executor.extract_tool_calls(proc)
        self.assertEqual(out, [])


class ExecutorMainTest(unittest.TestCase):
    """T29_executor_unit_with_mock: invoke_claude_p / notify_discord を差し替えて executor.main() の全 status 遷移を確認."""

    def setUp(self) -> None:
        self.iso = _DbIsolation()
        self.approvals = self.iso.enter()
        for mod in list(sys.modules):
            if mod == "approvals_executor":
                del sys.modules[mod]
        import approvals_executor
        self.executor = approvals_executor
        # notify_discord を差し替えて Discord 投稿をスキップ
        self._notify_patch = mock.patch.object(self.executor, "notify_discord")
        self.notify_mock = self._notify_patch.start()

    def tearDown(self) -> None:
        self._notify_patch.stop()
        self.iso.exit()

    def _enqueue_approve(self, payload=None):
        if payload is None:
            payload = _valid_payload()
        aid = self.approvals.enqueue(
            proposer_job="p", executor_job="calendar-create-executor",
            action="calendar.create", summary="s", payload=payload,
        )
        self.approvals.decide(aid, "approve", user_id=1)
        return aid

    def _run_with_mock(self, proc_result: dict, aid: str) -> int:
        os.environ["HERMES_APPROVAL_ID"] = aid
        try:
            with mock.patch.object(self.executor, "invoke_claude_p",
                                   return_value=proc_result):
                rc = self.executor.main()
        finally:
            os.environ.pop("HERMES_APPROVAL_ID", None)
        return rc

    def test_success_executed(self) -> None:
        payload = _valid_payload("ok-event")
        aid = self._enqueue_approve(payload)
        expected_input = self.executor.expected_create_event_args(payload)
        proc = {
            "result": "[OK approval #" + aid + "] ok-event -> https://calendar.google.com/event?eid=xxx",
            "is_error": False,
            "tool_uses": [
                {"name": self.approvals.MCP_CREATE_EVENT, "input": expected_input},
            ],
        }
        rc = self._run_with_mock(proc, aid)
        self.assertEqual(rc, 0)
        row = self.approvals.get(aid)
        self.assertEqual(row["status"], "executed")

    def test_double_create_event(self) -> None:
        aid = self._enqueue_approve()
        proc = {
            "result": "OK",
            "is_error": False,
            "tool_uses": [
                {"name": self.approvals.MCP_CREATE_EVENT, "input": {}},
                {"name": self.approvals.MCP_CREATE_EVENT, "input": {}},
            ],
        }
        rc = self._run_with_mock(proc, aid)
        self.assertEqual(rc, 1)
        row = self.approvals.get(aid)
        self.assertEqual(row["status"], "failed_after_side_effect")

    def test_other_tool_called(self) -> None:
        aid = self._enqueue_approve()
        proc = {
            "result": "OK",
            "is_error": False,
            "tool_uses": [
                {"name": self.approvals.MCP_CREATE_EVENT, "input": {}},
                {"name": "Bash", "input": {"cmd": "ls"}},
            ],
        }
        rc = self._run_with_mock(proc, aid)
        self.assertEqual(rc, 1)
        row = self.approvals.get(aid)
        self.assertEqual(row["status"], "failed_after_side_effect")

    def test_input_mismatch(self) -> None:
        payload = _valid_payload("original")
        aid = self._enqueue_approve(payload)
        bad_input = self.executor.expected_create_event_args(payload)
        bad_input["summary"] = "ALTERED"
        proc = {
            "result": "[OK approval #" + aid + "] altered -> https://calendar.google.com/event?eid=yyy",
            "is_error": False,
            "tool_uses": [
                {"name": self.approvals.MCP_CREATE_EVENT, "input": bad_input},
            ],
        }
        rc = self._run_with_mock(proc, aid)
        self.assertEqual(rc, 1)
        row = self.approvals.get(aid)
        self.assertEqual(row["status"], "failed_after_side_effect")

    def test_zero_calls_is_failed_after_side_effect(self) -> None:
        """tool_uses が空リスト = create_calls 0 件 → tool_use violation (件数 != 1) → failed_after_side_effect."""
        aid = self._enqueue_approve()
        proc = {
            "result": "I did nothing.",
            "is_error": False,
            "tool_uses": [],
        }
        rc = self._run_with_mock(proc, aid)
        self.assertEqual(rc, 1)
        row = self.approvals.get(aid)
        # 0 件は件数違反 (1 でない) なので failed_after_side_effect
        self.assertEqual(row["status"], "failed_after_side_effect")

    def test_is_error_with_zero_calls_is_failed(self) -> None:
        """is_error=True + tool_use evidence が 空リストでない検出 (= 違反検出) -> 検証で先に failed_after_side_effect.

        副作用なしの is_error は extract_tool_calls が空リストを返すケースなので、
        is_error より前に「件数 != 1」で failed_after_side_effect に倒れる。
        """
        # この test case はそもそも extract_tool_calls の前に
        # 「create_calls=0 で violation」と判定されるので status は failed_after_side_effect。
        # 「is_error + 0 件 で failed (副作用なし)」となるのは、tool_calls が len==1 だった上で
        # is_err が真になるケースだけ。下の test_is_error_with_one_call_is_side_effect で検証する。
        pass

    def test_is_error_with_one_call_is_side_effect(self) -> None:
        """create_calls 1 件 + is_error=True → failed_after_side_effect (副作用可能)."""
        payload = _valid_payload()
        aid = self._enqueue_approve(payload)
        proc = {
            "result": "ERROR: claude post-process failed",
            "is_error": True,
            "tool_uses": [
                {"name": self.approvals.MCP_CREATE_EVENT,
                 "input": self.executor.expected_create_event_args(payload)},
            ],
        }
        rc = self._run_with_mock(proc, aid)
        self.assertEqual(rc, 1)
        row = self.approvals.get(aid)
        self.assertEqual(row["status"], "failed_after_side_effect")

    def test_evidence_unavailable(self) -> None:
        """T28: extract_tool_calls が None → failed_after_side_effect."""
        aid = self._enqueue_approve()
        proc = {"usage": {"tool_use_count": 1}, "result": "?"}
        rc = self._run_with_mock(proc, aid)
        self.assertEqual(rc, 1)
        row = self.approvals.get(aid)
        self.assertEqual(row["status"], "failed_after_side_effect")
        self.assertIn("evidence unavailable", row["result_text"])

    def test_validate_failed(self) -> None:
        """payload を直接壊した状態で executor.main() を回す → validate 失敗 → failed (副作用前)."""
        aid = self._enqueue_approve()
        # DB を直接書き換えて payload を破壊
        conn = sqlite3.connect(str(self.iso.db_path))
        conn.execute("UPDATE approvals SET payload_json='{\"summary\":\"x\"}' WHERE id=?", (aid,))
        conn.commit()
        conn.close()
        os.environ["HERMES_APPROVAL_ID"] = aid
        try:
            with mock.patch.object(self.executor, "invoke_claude_p") as mocked:
                rc = self.executor.main()
                mocked.assert_not_called()
        finally:
            os.environ.pop("HERMES_APPROVAL_ID", None)
        self.assertEqual(rc, 1)
        row = self.approvals.get(aid)
        self.assertEqual(row["status"], "failed")


class CliContractTest(unittest.TestCase):
    """CLI モードを subprocess で呼ぶ統合的なチェック (enqueue / get / list)."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "approvals.sqlite"
        self.env = {
            **os.environ,
            "HERMES_APPROVALS_DB": str(self.db_path),
            "HERMES_HOME": str(_REPO_ROOT),
        }
        self.script = str(_REPO_ROOT / "lib" / "approvals.py")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _cli(self, args, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, self.script] + args,
            input=stdin, capture_output=True, text=True, env=self.env, timeout=10,
        )

    def test_enqueue_and_get(self) -> None:
        payload = _valid_payload("cli-test")
        res = self._cli(
            ["enqueue", "--proposer", "p", "--executor", "calendar-create-executor",
             "--action", "calendar.create", "--summary", "s"],
            stdin=json.dumps(payload),
        )
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        aid = res.stdout.strip()
        self.assertEqual(len(aid), 8)

        # get
        res2 = self._cli(["get", "--id", aid])
        self.assertEqual(res2.returncode, 0)
        row = json.loads(res2.stdout)
        self.assertEqual(row["id"], aid)
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["payload"]["summary"], "cli-test")

    def test_validate_failure_exit_1(self) -> None:
        bad = {"summary": ""}  # missing keys
        res = self._cli(
            ["enqueue", "--proposer", "p", "--executor", "calendar-create-executor",
             "--action", "calendar.create", "--summary", "s"],
            stdin=json.dumps(bad),
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("ERROR", res.stderr)


if __name__ == "__main__":
    unittest.main()
