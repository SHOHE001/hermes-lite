"""mail-watch ルール調整ハンドラ: 専用チャンネルの自然文 -> var/mail-watch/rules.md.

bot.py から (MAIL_WATCH_CHANNEL_IDS が空でないときだけ) import される。
approval_handler.py と同じ流儀: 同期 handle() を bot 側が asyncio.to_thread で呼び、
内部で認可を再チェックし、Discord に出す文字列を返す。

rules.md は git 管理外 (.gitignore の `var/*`)。これは gloop が毎サイクル末に
`git stash push -u -- . :(exclude)features/` を実行するためで、jobs/ 配下に置くと
bot が書いた学習ルールが次サイクルで stash に吸われて消える (stash -u は ignored を
含まない)。履歴は rules.bak/ と rules-audit.jsonl で代替する。
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import claude_runner
from config import (
    ALLOWED_USER_IDS,
    CLAUDE_BIN,
    HERMES_HOME,
    MAIL_RULES_MODEL,
    MAIL_RULES_TIMEOUT_SEC,
    MAIL_WATCH_CHANNEL_IDS,
    MAIL_WATCH_RULES_PATH,
)

log = logging.getLogger("hermes-lite.discord.mail_rules")

JST = timezone(timedelta(hours=9))

PROMPT_FILE = Path(__file__).with_name("mail_rules_prompt.md")

# rules.md の追記アンカー。claude にはこの行を Edit の old_string にさせる。
SENTINELS = (
    "<!-- APPEND:EXCLUDE -->",
    "<!-- APPEND:INCLUDE -->",
    "<!-- APPEND:STYLE -->",
)

BACKUP_KEEP = 20
MAX_FEEDBACK_CHARS = 1000
# 統合更新で多少縮むのは許容するが、大量削除は検証 NG にする。
SHRINK_TOLERANCE_BYTES = 200

# 実測 (2026-07-29): --allowed-tools だけでは Write も Bash も通ってしまい、
# --disallowed-tools '*' は allowed より優先されて Read すら拒否される。
# よって「allowed で開ける + disallowed で明示的に閉じる」の両方が要る。
# MCP は空 config + --strict-mcp-config でサーバーごと落とす (Gmail/Discord MCP を断つ)。
ALLOWED_TOOLS = ["Read", "Edit"]
DISALLOWED_TOOLS = [
    "Write", "Bash", "Task", "WebFetch", "WebSearch", "NotebookEdit", "Glob", "Grep",
]
MCP_OFF_ARGS = ["--mcp-config", '{"mcpServers":{}}', "--strict-mcp-config"]

TEMPLATE = """# mail-watch 追加ルール（学習分）

Discord の mail-watch 専用チャンネルでのフィードバックから自動追記される。
`jobs/mail-watch/prompt.md` の「重要度の基準」に**上乗せ**して適用される。

手で編集・削除してよい。不要になったエントリはそのまま消せばよい。
`<!-- APPEND:* -->` の行は追記位置のアンカーなので消さないこと。

書式:

    - [YYYY-MM-DD] 通知しない: <対象の特徴>
      - 理由: <1 行>
      - 例外: <あれば>
      - 出典: <短縮 threadId があれば>

## 通知しない（除外を強める）

<!-- APPEND:EXCLUDE -->

## 通知する（拾いを強める）

<!-- APPEND:INCLUDE -->

## 要約・表記の好み

<!-- APPEND:STYLE -->
"""

_SHOW_RE = re.compile(r"^\s*(rules?|ルール|ルール一覧)\s*$", re.IGNORECASE)
_UNDO_RE = re.compile(r"^\s*(undo|元に戻して|戻して|取り消し)\s*$", re.IGNORECASE)
_ENTRY_RE = re.compile(r"^- \[\d{4}-\d{2}-\d{2}\]", re.MULTILINE)


# ---------------------------------------------------------------------------
# パスまわり
# ---------------------------------------------------------------------------

def _rules_path() -> Path:
    return Path(MAIL_WATCH_RULES_PATH)


def _backup_dir() -> Path:
    return _rules_path().parent / "rules.bak"


def _audit_path() -> Path:
    return _rules_path().parent / "rules-audit.jsonl"


def _read_rules() -> str:
    try:
        return _rules_path().read_text(encoding="utf-8")
    except OSError:
        return ""


def _ensure_rules_file() -> None:
    """rules.md が無ければテンプレートを置く.

    claude には Write を渡さないので、編集対象が存在しないと Edit が失敗する。
    その前提条件をここで作る。
    """
    path = _rules_path()
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE, encoding="utf-8")
    log.info("created rules template at %s", path)


def _backup() -> Path | None:
    """現在の rules.md を rules.bak/<ts>.md へ退避し、古い世代を捨てる."""
    path = _rules_path()
    if not path.exists():
        return None
    bdir = _backup_dir()
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(JST).strftime("%Y%m%d-%H%M%S-%f")
    dest = bdir / f"{stamp}.md"
    try:
        shutil.copy2(path, dest)
    except OSError:
        log.warning("backup failed for %s", path, exc_info=True)
        return None
    olds = sorted(bdir.glob("*.md"))
    for stale in olds[:-BACKUP_KEEP]:
        try:
            stale.unlink()
        except OSError:
            pass
    return dest


def _latest_backup() -> Path | None:
    bdir = _backup_dir()
    if not bdir.is_dir():
        return None
    backups = sorted(bdir.glob("*.md"))
    return backups[-1] if backups else None


def _restore(backup: Path | None) -> bool:
    if backup is None or not backup.exists():
        return False
    try:
        shutil.copy2(backup, _rules_path())
        return True
    except OSError:
        log.exception("restore failed from %s", backup)
        return False


def _count_entries(text: str) -> int:
    return len(_ENTRY_RE.findall(text))


def _validate(size_before: int) -> tuple[bool, str]:
    """claude 実行後の rules.md を決定的に検証する (LLM の善意に依存しない)."""
    path = _rules_path()
    if not path.exists():
        return False, "ファイルが消えている"
    text = _read_rules()
    if not text.strip():
        return False, "中身が空になっている"
    for sentinel in SENTINELS:
        count = text.count(sentinel)
        if count != 1:
            return False, f"アンカー {sentinel} が {count} 個 (1 個であるべき)"
    size_after = len(text.encode("utf-8"))
    if size_after < size_before - SHRINK_TOLERANCE_BYTES:
        return False, f"{size_before - size_after} バイト縮んでいる"
    return True, ""


def _audit(record: dict) -> None:
    try:
        path = _audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        log.warning("failed to write audit log", exc_info=True)


# ---------------------------------------------------------------------------
# claude -p 起動
# ---------------------------------------------------------------------------

def _build_prompt(user_text: str, quoted_text: str | None) -> str:
    template = PROMPT_FILE.read_text(encoding="utf-8")
    today = datetime.now(JST).strftime("%Y-%m-%d")
    return (
        f"{template}\n\n"
        "---\n"
        f"今日の日付: {today}\n"
        f"編集対象: {_rules_path()}\n\n"
        "--- ユーザーからのフィードバック ---\n"
        f"{user_text}\n\n"
        "--- 返信元のメッセージ（Discord の返信で指されていた通知本文） ---\n"
        f"{quoted_text or '(なし)'}\n"
    )


def _run_claude(prompt: str) -> tuple[int, str, str]:
    """(returncode, result_text, stderr) を返す。timeout は rc=124."""
    cmd = [CLAUDE_BIN, "-p", prompt, "--output-format", "json"]
    if MAIL_RULES_MODEL:
        cmd.extend(["--model", MAIL_RULES_MODEL])
    cmd.extend(["--max-turns", "12", "--permission-mode", "default"])
    cmd.extend(MCP_OFF_ARGS)
    cmd.extend(["--allowed-tools", *ALLOWED_TOOLS])
    cmd.extend(["--disallowed-tools", *DISALLOWED_TOOLS])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=MAIL_RULES_TIMEOUT_SEC,
            cwd=str(HERMES_HOME),
            env=claude_runner.build_child_env(),
        )
    except subprocess.TimeoutExpired as e:
        return 124, "", (e.stderr or "")[:2000] if isinstance(e.stderr, str) else ""
    except (OSError, ValueError) as e:
        return 1, "", str(e)[:2000]
    text = ""
    try:
        payload = json.loads(proc.stdout or "{}")
        text = (payload.get("result") or "").strip()
    except (json.JSONDecodeError, AttributeError):
        text = (proc.stdout or "").strip()
    return proc.returncode, text, (proc.stderr or "")[:2000]


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

def handle(
    *,
    user_text: str,
    user_id: int,
    channel_id: int,
    quoted_text: str | None = None,
) -> str:
    """mail-watch 専用チャンネルの発言を処理し、Discord に返す文字列を返す."""
    # 認可の二重チェック (approval_handler と同流儀)。
    # channel_id の再検証が本質: ルーティングのバグで Read/Edit 権限が
    # 他チャンネルへ漏れるのをここで塞ぐ。
    if user_id not in ALLOWED_USER_IDS:
        log.warning("unauthorized mail-rules attempt user_id=%s", user_id)
        return f"⚠️ [WARN] unauthorized user_id={user_id}"
    if channel_id not in MAIL_WATCH_CHANNEL_IDS:
        log.warning("mail-rules called from wrong channel=%s", channel_id)
        return "⚠️ [WARN] このチャンネルでは mail-watch のルールを編集できません"

    text = (user_text or "").strip()
    if not text:
        return "❓ テキストで書いてください（添付だけでは判断できません）"

    _ensure_rules_file()

    # --- claude を起動しないローカルショートカット ---
    if _SHOW_RE.match(text):
        body = _read_rules()
        return f"現在のルール（全 {_count_entries(body)} エントリ）:\n```markdown\n{body}\n```"

    if _UNDO_RE.match(text):
        backup = _latest_backup()
        if backup is None:
            return "⚠️ 戻せるバックアップがありません"
        if not _restore(backup):
            return "⚠️ バックアップからの復元に失敗しました（journalctl 参照）"
        try:
            backup.unlink()   # 消しておくと undo を続けてさらに前へ戻れる
        except OSError:
            pass
        _audit({
            "ts": datetime.now(JST).isoformat(),
            "user_id": user_id, "channel_id": channel_id,
            "action": "undo", "backup": str(backup),
        })
        return f"↩️ 直前の変更を取り消しました（全 {_count_entries(_read_rules())} エントリ）"

    if len(text) > MAX_FEEDBACK_CHARS:
        text = text[:MAX_FEEDBACK_CHARS]

    before = _read_rules()
    size_before = len(before.encode("utf-8"))
    backup = _backup()

    rc, result, stderr = _run_claude(_build_prompt(text, quoted_text))
    after = _read_rules()
    ok, reason = _validate(size_before)
    restored = False
    if not ok:
        restored = _restore(backup)

    backup_used = str(backup) if backup else None
    # 中身が動かなかった実行（❓ で聞き返した / 検証 NG で復元した）のバックアップは捨てる。
    # 残すと undo の「直前」がその無変更時点になり、その前の追加を取り消せなくなる。
    if backup is not None and (restored or (ok and after == before)):
        try:
            backup.unlink()
        except OSError:
            pass

    _audit({
        "ts": datetime.now(JST).isoformat(),
        "user_id": user_id,
        "channel_id": channel_id,
        "action": "feedback",
        "user_text": text,
        "quoted_head": (quoted_text or "")[:300],
        "returncode": rc,
        "claude_result": result[:500],
        "bytes_before": size_before,
        "bytes_after": len(after.encode("utf-8")),
        "validated": ok,
        "invalid_reason": reason,
        "restored": restored,
        "backup": backup_used,
        "stderr_head": stderr[:300],
    })

    if not ok:
        suffix = "バックアップから復元しました" if restored else "復元にも失敗しました"
        return f"⚠️ ルールファイルの検証に失敗（{reason}）。{suffix}"

    if rc == 124:
        return f"⚠️ ルール更新がタイムアウトしました（{MAIL_RULES_TIMEOUT_SEC} 秒）"
    if rc != 0 or not result:
        snippet = (stderr or "(no stderr)")[:400]
        return f"⚠️ ルール更新に失敗しました（exit={rc}）\n```\n{snippet}\n```"

    if result.startswith("ERROR:"):
        return f"⚠️ {result}"
    if result.startswith("❓"):
        return result
    if result.startswith("✅"):
        return f"{result}\n（反映は次回 mail-watch 実行から / 全 {_count_entries(after)} エントリ）"
    # 想定外の形式。ファイル検証は通っているのでそのまま見せる。
    return result
