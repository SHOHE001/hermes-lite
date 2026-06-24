"""hermes-lite 承認ゲート: sqlite ヘルパー + state machine + CLI モード.

Issue #3 (features/3-discord-calendar-create/plan.md v6) の正本。
state machine / TTL / sweep / ID 衝突 retry / 認可ユーザー読み出し を担当する。

CLI モード (`python3 lib/approvals.py <subcommand>`) の contract は plan.md の
「CLI Contract 表」を参照。
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# 定数 (plan v6)
# ---------------------------------------------------------------------------

ALLOWED_ACTIONS = {"calendar.create"}
ALLOWED_EXECUTORS = {"calendar.create": "calendar-create-executor"}

# 別 MCP server 名 / profile は Out-of-Scope
MCP_CREATE_EVENT = "mcp__claude_ai_Google_Calendar__create_event"

_SCHEMA_VERSION = 1
_DEFAULT_TTL_SEC = int(os.environ.get("HERMES_APPROVAL_TTL_SEC", "86400"))  # 24h
_APPROVED_TTL_SEC = 600    # 10 min
_EXECUTING_TTL_SEC = 1800  # 30 min
_ID_RETRY_MAX = 5

_VALID_STATUSES = {
    "pending", "approved", "rejected", "executing",
    "executed", "expired", "failed", "failed_after_side_effect",
}


def _hermes_home() -> Path:
    """HERMES_HOME を環境変数 → 自己導出の順で決定."""
    env_val = os.environ.get("HERMES_HOME")
    if env_val:
        return Path(env_val)
    return Path(__file__).resolve().parents[1]


def _db_path() -> Path:
    env_val = os.environ.get("HERMES_APPROVALS_DB")
    if env_val:
        return Path(env_val)
    return _hermes_home() / "var" / "approvals.sqlite"


# ---------------------------------------------------------------------------
# sqlite セットアップ
# ---------------------------------------------------------------------------

def _connect() -> sqlite3.Connection:
    db = _db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA user_version")
    row = cur.fetchone()
    current_version = row[0] if row else 0

    if current_version == 0:
        conn.executescript(_SCHEMA_SQL)
        conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        return

    if current_version != _SCHEMA_VERSION:
        raise RuntimeError(
            f"approvals.sqlite schema mismatch: expected user_version={_SCHEMA_VERSION}, "
            f"got {current_version}. backup and recreate (see docs/discord-approval.md)."
        )

    cols = {r[1] for r in conn.execute("PRAGMA table_info(approvals)")}
    required = {
        "id", "proposer_job", "executor_job", "action", "summary",
        "payload_json", "status", "created_at", "expires_at",
        "decided_at", "decided_by", "started_at", "finished_at", "result_text",
    }
    missing = required - cols
    if missing:
        raise RuntimeError(
            f"approvals.sqlite missing columns: {sorted(missing)}; backup and recreate."
        )


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS approvals (
  id           TEXT PRIMARY KEY,
  proposer_job TEXT NOT NULL,
  executor_job TEXT NOT NULL,
  action       TEXT NOT NULL,
  summary      TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status       TEXT NOT NULL,
  created_at   INTEGER NOT NULL,
  expires_at   INTEGER NOT NULL,
  decided_at   INTEGER,
  decided_by   INTEGER,
  started_at   INTEGER,
  finished_at  INTEGER,
  result_text  TEXT
);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
CREATE INDEX IF NOT EXISTS idx_approvals_expires ON approvals(expires_at);
CREATE INDEX IF NOT EXISTS idx_approvals_decided ON approvals(decided_at);
CREATE INDEX IF NOT EXISTS idx_approvals_started ON approvals(started_at);
"""


# ---------------------------------------------------------------------------
# payload 検証
# ---------------------------------------------------------------------------

_PAYLOAD_REQUIRED = {"summary", "start", "end", "timeZone"}
_PAYLOAD_OPTIONAL = {"description", "location"}
_PAYLOAD_ALL = _PAYLOAD_REQUIRED | _PAYLOAD_OPTIONAL


def validate_payload(action: str, payload: dict) -> None:
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"action not allowed: {action}")
    if not isinstance(payload, dict):
        raise ValueError(f"payload must be dict, got {type(payload).__name__}")

    unknown = set(payload.keys()) - _PAYLOAD_ALL
    if unknown:
        raise ValueError(f"unknown payload keys: {sorted(unknown)}")

    missing = _PAYLOAD_REQUIRED - set(payload.keys())
    if missing:
        raise ValueError(f"missing required keys: {sorted(missing)}")

    summary = payload["summary"]
    if not isinstance(summary, str) or not (1 <= len(summary) <= 256):
        raise ValueError("summary must be str of length 1..256")

    tz = payload["timeZone"]
    if not isinstance(tz, str) or not tz:
        raise ValueError("timeZone must be non-empty str")

    start_raw = payload["start"]
    end_raw = payload["end"]
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        raise ValueError("start / end must be ISO 8601 strings")

    try:
        start_dt = datetime.fromisoformat(start_raw)
        end_dt = datetime.fromisoformat(end_raw)
    except ValueError as e:
        raise ValueError(f"start / end must parse as ISO 8601: {e}") from e

    if start_dt.tzinfo is None or end_dt.tzinfo is None:
        raise ValueError("start / end must include timezone offset")

    if not (end_dt > start_dt):
        raise ValueError("end must be > start")

    now_dt = datetime.now(start_dt.tzinfo)
    if start_dt < now_dt - timedelta(minutes=30):
        raise ValueError("start must be > now - 30min (past event rejected)")

    if "description" in payload:
        d = payload["description"]
        if not isinstance(d, str) or len(d) > 2000:
            raise ValueError("description must be str of length <= 2000")
    if "location" in payload:
        loc = payload["location"]
        if not isinstance(loc, str) or len(loc) > 256:
            raise ValueError("location must be str of length <= 256")


# ---------------------------------------------------------------------------
# row 共通 schema
# ---------------------------------------------------------------------------

def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    payload_json = d.get("payload_json", "{}")
    try:
        d["payload"] = json.loads(payload_json) if payload_json else {}
    except json.JSONDecodeError:
        d["payload"] = {}
    return d


# ---------------------------------------------------------------------------
# 認可ユーザー
# ---------------------------------------------------------------------------

def get_authorized_user_ids() -> set:
    raw = os.environ.get("HERMES_APPROVAL_AUTHORIZED_USER_IDS", "").strip()
    if not raw:
        raw = os.environ.get("HERMES_APPROVAL_ALLOWED_USER_IDS_FALLBACK", "").strip()
    if not raw:
        return set()
    out = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            continue
    return out


# ---------------------------------------------------------------------------
# enqueue
# ---------------------------------------------------------------------------

def enqueue(*, proposer_job: str, executor_job: str, action: str,
            summary: str, payload: dict, ttl_sec: Optional[int] = None) -> str:
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"action not allowed: {action}")
    expected_executor = ALLOWED_EXECUTORS.get(action)
    if expected_executor is None or executor_job != expected_executor:
        raise ValueError(
            f"executor_job mismatch: action={action} requires "
            f"executor_job={expected_executor!r}, got {executor_job!r}"
        )
    validate_payload(action, payload)

    if ttl_sec is None:
        ttl_sec = _DEFAULT_TTL_SEC

    now = int(time.time())
    expires_at = now + ttl_sec
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    last_err = None
    conn = _connect()
    try:
        for _ in range(_ID_RETRY_MAX):
            aid = secrets.token_hex(4)
            try:
                conn.execute(
                    "INSERT INTO approvals "
                    "(id, proposer_job, executor_job, action, summary, payload_json, "
                    " status, created_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                    (aid, proposer_job, executor_job, action, summary,
                     payload_json, now, expires_at),
                )
                return aid
            except sqlite3.IntegrityError as e:
                last_err = e
                continue
        raise RuntimeError(
            f"id collision exhausted after {_ID_RETRY_MAX} attempts: {last_err}"
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# state transitions
# ---------------------------------------------------------------------------

def decide(approval_id: str, decision: str, *, user_id: Optional[int] = None) -> Optional[str]:
    if decision not in ("approve", "reject"):
        raise ValueError(f"decision must be approve/reject, got {decision!r}")
    new_status = "approved" if decision == "approve" else "rejected"
    now = int(time.time())
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE approvals SET status=?, decided_at=?, decided_by=? "
            "WHERE id=? AND status='pending' AND expires_at > ?",
            (new_status, now, user_id, approval_id, now),
        )
        if cur.rowcount != 1:
            return None
        return new_status
    finally:
        conn.close()


def take(approval_id: str, executor_job: str) -> Optional[dict]:
    now = int(time.time())
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE approvals SET status='executing', started_at=? "
            "WHERE id=? AND executor_job=? AND status='approved' AND expires_at > ?",
            (now, approval_id, executor_job, now),
        )
        if cur.rowcount != 1:
            return None
        row = conn.execute(
            "SELECT * FROM approvals WHERE id=?", (approval_id,)
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def done(approval_id: str, *, result_text: str) -> None:
    now = int(time.time())
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE approvals SET status='executed', finished_at=?, result_text=? "
            "WHERE id=? AND status='executing'",
            (now, result_text, approval_id),
        )
        if cur.rowcount != 1:
            raise ValueError(f"done failed: id={approval_id} not in 'executing'")
    finally:
        conn.close()


def fail_before_executor(approval_id: str, *, result_text: str) -> None:
    """bot 側: approved -> failed (systemd-run 起動失敗の救済)."""
    now = int(time.time())
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE approvals SET status='failed', finished_at=?, result_text=? "
            "WHERE id=? AND status='approved'",
            (now, result_text, approval_id),
        )
        if cur.rowcount != 1:
            raise ValueError(
                f"fail_before_executor failed: id={approval_id} not in 'approved'"
            )
    finally:
        conn.close()


def fail_during_executor(approval_id: str, *, result_text: str,
                         side_effect: bool = False) -> None:
    """executor 側: executing -> failed / failed_after_side_effect."""
    new_status = "failed_after_side_effect" if side_effect else "failed"
    now = int(time.time())
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE approvals SET status=?, finished_at=?, result_text=? "
            "WHERE id=? AND status='executing'",
            (new_status, now, result_text, approval_id),
        )
        if cur.rowcount != 1:
            raise ValueError(
                f"fail_during_executor failed: id={approval_id} not in 'executing'"
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# sweep
# ---------------------------------------------------------------------------

def sweep_expired() -> int:
    now = int(time.time())
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE approvals SET status='expired', finished_at=? "
            "WHERE status='pending' AND expires_at < ?",
            (now, now),
        )
        return cur.rowcount
    finally:
        conn.close()


def sweep_stale_approved() -> int:
    now = int(time.time())
    threshold = now - _APPROVED_TTL_SEC
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE approvals SET status='failed', finished_at=?, "
            "result_text='stale approved (>{}s)' "
            "WHERE status='approved' AND decided_at < ?".format(_APPROVED_TTL_SEC),
            (now, threshold),
        )
        return cur.rowcount
    finally:
        conn.close()


def sweep_stale_executing() -> int:
    now = int(time.time())
    threshold = now - _EXECUTING_TTL_SEC
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE approvals SET status='failed', finished_at=?, "
            "result_text='stale executing (>{}s)' "
            "WHERE status='executing' AND started_at < ?".format(_EXECUTING_TTL_SEC),
            (now, threshold),
        )
        return cur.rowcount
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------

def get(approval_id: str) -> Optional[dict]:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM approvals WHERE id=?", (approval_id,)
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def list_rows(*, status: Optional[str] = None) -> list:
    conn = _connect()
    try:
        if status:
            if status not in _VALID_STATUSES:
                raise ValueError(f"unknown status filter: {status}")
            rows = conn.execute(
                "SELECT * FROM approvals WHERE status=? ORDER BY created_at",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM approvals ORDER BY created_at"
            ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI モード
# ---------------------------------------------------------------------------

def _cli_enqueue(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        print(f"ERROR: payload JSON parse failed: {e}", file=sys.stderr)
        return 1
    try:
        aid = enqueue(
            proposer_job=args.proposer,
            executor_job=args.executor,
            action=args.action,
            summary=args.summary,
            payload=payload,
            ttl_sec=args.ttl,
        )
    except ValueError as e:
        print(f"ERROR: validate failed: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"ERROR: id collision exhausted: {e}", file=sys.stderr)
        return 3
    print(aid)
    return 0


def _cli_decide(args: argparse.Namespace) -> int:
    try:
        after = decide(args.id, args.decision, user_id=args.user_id)
    except ValueError as e:
        print(f"ERROR: decide failed: {e}", file=sys.stderr)
        return 1
    if after is None:
        return 1
    print(after)
    return 0


def _cli_take(args: argparse.Namespace) -> int:
    row = take(args.id, args.executor)
    if row is None:
        print("ERROR: no approved row", file=sys.stderr)
        return 1
    print(json.dumps(row, ensure_ascii=False))
    return 0


def _cli_done(args: argparse.Namespace) -> int:
    try:
        done(args.id, result_text=args.result_text)
    except ValueError as e:
        print(f"ERROR: done failed: {e}", file=sys.stderr)
        return 1
    return 0


def _cli_fail_before(args: argparse.Namespace) -> int:
    try:
        fail_before_executor(args.id, result_text=args.result_text)
    except ValueError as e:
        print(f"ERROR: fail-before failed: {e}", file=sys.stderr)
        return 1
    return 0


def _cli_fail_during(args: argparse.Namespace) -> int:
    try:
        fail_during_executor(args.id, result_text=args.result_text,
                             side_effect=args.side_effect)
    except ValueError as e:
        print(f"ERROR: fail-during failed: {e}", file=sys.stderr)
        return 1
    return 0


def _cli_sweep(args: argparse.Namespace) -> int:
    n = sweep_expired()
    print(f"swept-expired {n}")
    return 0


def _cli_sweep_stale_approved(args: argparse.Namespace) -> int:
    n = sweep_stale_approved()
    print(f"swept-stale-approved {n}")
    return 0


def _cli_sweep_stale_executing(args: argparse.Namespace) -> int:
    n = sweep_stale_executing()
    print(f"swept-stale-executing {n}")
    return 0


def _cli_get(args: argparse.Namespace) -> int:
    row = get(args.id)
    if row is None:
        return 1
    print(json.dumps(row, ensure_ascii=False))
    return 0


def _cli_list(args: argparse.Namespace) -> int:
    rows = list_rows(status=args.status)
    print(json.dumps(rows, ensure_ascii=False))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="approvals", description="hermes-lite approval state machine CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("enqueue", help="payload JSON を stdin から読んで pending row を作る")
    pe.add_argument("--proposer", required=True)
    pe.add_argument("--executor", required=True)
    pe.add_argument("--action", required=True)
    pe.add_argument("--summary", required=True)
    pe.add_argument("--ttl", type=int, default=None)
    pe.set_defaults(func=_cli_enqueue)

    pd = sub.add_parser("decide")
    pd.add_argument("--id", required=True)
    pd.add_argument("--decision", required=True, choices=["approve", "reject"])
    pd.add_argument("--user-id", dest="user_id", type=int, default=None)
    pd.set_defaults(func=_cli_decide)

    pt = sub.add_parser("take")
    pt.add_argument("--id", required=True)
    pt.add_argument("--executor", required=True)
    pt.set_defaults(func=_cli_take)

    pdone = sub.add_parser("done")
    pdone.add_argument("--id", required=True)
    pdone.add_argument("--result-text", dest="result_text", required=True)
    pdone.set_defaults(func=_cli_done)

    pfb = sub.add_parser("fail-before")
    pfb.add_argument("--id", required=True)
    pfb.add_argument("--result-text", dest="result_text", required=True)
    pfb.set_defaults(func=_cli_fail_before)

    pfd = sub.add_parser("fail-during")
    pfd.add_argument("--id", required=True)
    pfd.add_argument("--result-text", dest="result_text", required=True)
    pfd.add_argument("--side-effect", dest="side_effect", action="store_true")
    pfd.set_defaults(func=_cli_fail_during)

    ps = sub.add_parser("sweep")
    ps.set_defaults(func=_cli_sweep)

    psa = sub.add_parser("sweep-stale-approved")
    psa.set_defaults(func=_cli_sweep_stale_approved)

    pse = sub.add_parser("sweep-stale-executing")
    pse.set_defaults(func=_cli_sweep_stale_executing)

    pg = sub.add_parser("get")
    pg.add_argument("--id", required=True)
    pg.set_defaults(func=_cli_get)

    pl = sub.add_parser("list")
    pl.add_argument("--status", default=None)
    pl.set_defaults(func=_cli_list)

    return p


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
