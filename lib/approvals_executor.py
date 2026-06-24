"""LLM executor: 承認済み calendar.create を 1 回だけ実行し副作用を事後検証する.

systemd-run から `HERMES_APPROVAL_ID` を渡されて起動される。
- `take()` で executing 遷移 (1 回限り解禁)
- claude -p に固定テンプレ prompt を渡し MCP create_event を 1 回だけ呼ばせる
- 出力 JSON から tool_use evidence を抽出して payload と完全一致を assert
- 違反/取得不能なら `failed_after_side_effect` に倒して手動 cleanup 指示を Discord 通知

実装根拠: features/3-discord-calendar-create/plan.md v6 § approvals_executor.py
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

# 自モジュール (lib/) を path 追加して approvals を import
_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import approvals  # noqa: E402


_CLAUDE_BIN = os.environ.get("CLAUDE_BIN", str(Path.home() / ".local" / "bin" / "claude"))
_HERMES_HOME = Path(os.environ.get("HERMES_HOME", str(_LIB_DIR.parent)))
_DISALLOWED_FILE = _HERMES_HOME / "lib" / "disallowed-tools.txt"
_DEFAULT_TIMEOUT = int(os.environ.get("HERMES_EXECUTOR_TIMEOUT_SEC", "180"))
_DEFAULT_MODEL = os.environ.get("HERMES_EXECUTOR_MODEL", "sonnet")
_DEFAULT_MAX_BUDGET = os.environ.get("HERMES_EXECUTOR_MAX_BUDGET_USD", "0.50")
_DEFAULT_MAX_TURNS = os.environ.get("HERMES_EXECUTOR_MAX_TURNS", "5")
_DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()


# ---------------------------------------------------------------------------
# disallowed-tools.txt を読み、Calendar.create だけを除外したリストを返す
# ---------------------------------------------------------------------------

def read_disallowed_minus(exclude: str) -> list:
    """disallowed-tools.txt を読み、exclude と一致する行だけを除外して返す.

    disallowed-tools.txt 自体は書き換えず、executor の `--disallowed-tools` 引数を
    組み立てるためだけに使う (Non-Goal: lib/disallowed-tools.txt は不変)。
    """
    out = []
    if not _DISALLOWED_FILE.exists():
        return out
    for line in _DISALLOWED_FILE.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s == exclude:
            continue
        out.append(s)
    return out


# ---------------------------------------------------------------------------
# prompt 組み立て
# ---------------------------------------------------------------------------

def render_calendar_create_prompt(payload: dict, approval_id: str) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    return f"""あなたは hermes-lite の calendar-create-executor です。
承認済み approval #{approval_id} の payload を Google Calendar に登録してください。

## payload (JSON)

```json
{payload_json}
```

## 厳守事項

- 使ってよい tool は `{approvals.MCP_CREATE_EVENT}` の **1 回だけ** です。それ以外の tool は呼ばないでください。
- 上記 payload の値を **そのまま** field に渡してください。要約や言い換えはしないでください。
- mapping:
  - `summary` → `summary`
  - `start` → `start.dateTime`
  - `end` → `end.dateTime`
  - `timeZone` → `start.timeZone` と `end.timeZone` の両方
  - `description` (あれば) → `description`
  - `location` (あれば) → `location`
- 作成後、Calendar から返ってきた htmlLink を含めて 1 行で結果を返してください:
  `[OK approval #{approval_id}] <summary> -> <htmlLink>`
- 何か問題があれば `ERROR: ...` で始まる文字列を返してください。
"""


def expected_create_event_args(payload: dict) -> dict:
    out = {
        "summary": payload["summary"],
        "start": {"dateTime": payload["start"], "timeZone": payload["timeZone"]},
        "end": {"dateTime": payload["end"], "timeZone": payload["timeZone"]},
    }
    if "description" in payload:
        out["description"] = payload["description"]
    if "location" in payload:
        out["location"] = payload["location"]
    return out


# ---------------------------------------------------------------------------
# claude -p 呼び出し
# ---------------------------------------------------------------------------

def invoke_claude_p(prompt: str) -> dict:
    """claude -p を呼んで JSON を辞書として返す.

    返却 dict は claude --output-format json のトップレベル. JSON 解析に失敗した
    場合は `{"is_error": True, "result": "ERROR: claude output not JSON: <excerpt>"}`
    を返す.
    """
    disallowed = read_disallowed_minus(approvals.MCP_CREATE_EVENT)
    cmd = [
        _CLAUDE_BIN,
        "-p", prompt,
        "--output-format", "json",
        "--max-turns", _DEFAULT_MAX_TURNS,
        "--model", _DEFAULT_MODEL,
        "--permission-mode", "default",
        "--max-budget-usd", _DEFAULT_MAX_BUDGET,
        "--allowed-tools", approvals.MCP_CREATE_EVENT,
    ]
    if disallowed:
        cmd.append("--disallowed-tools")
        cmd.extend(disallowed)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT,
            env={**os.environ, "CI": "1"},
            cwd=str(_HERMES_HOME),
        )
    except subprocess.TimeoutExpired:
        return {"is_error": True, "result": f"ERROR: claude timeout ({_DEFAULT_TIMEOUT}s)"}
    except FileNotFoundError as e:
        return {"is_error": True, "result": f"ERROR: claude binary not found: {e}"}

    stdout = proc.stdout or ""
    if proc.returncode != 0 and not stdout.strip():
        err = (proc.stderr or "").strip()[:400]
        return {"is_error": True, "result": f"ERROR: claude exit={proc.returncode}: {err}"}

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        excerpt = stdout[:400].replace("\n", " ")
        return {"is_error": True, "result": f"ERROR: claude output not JSON: {e}: {excerpt}"}


# ---------------------------------------------------------------------------
# tool_use evidence 抽出 (plan v6 §「extract_tool_calls の挙動」)
# ---------------------------------------------------------------------------

def extract_tool_calls(proc_result: dict) -> Optional[list]:
    """claude -p 出力から tool_use 呼び出しを {name, input?} のリストで返す.

    - case 1: top-level `tool_uses: [{name, input}, ...]` を見つけたらそのまま返す
    - case 2: `messages[*].content[*]` を走査して type=='tool_use' を集める
    - case 3: usage.tool_use_count しか取れない場合は **None** を返す (fail-closed)
    - case 4: どれもマッチしない (= claude が tool を呼んでいない) → 空リスト
    """
    if not isinstance(proc_result, dict):
        return None

    # case 1
    tu = proc_result.get("tool_uses")
    if isinstance(tu, list):
        out = []
        for entry in tu:
            if not isinstance(entry, dict):
                continue
            out.append({"name": entry.get("name"), "input": entry.get("input")})
        return out

    # case 2: messages 走査
    messages = proc_result.get("messages")
    if isinstance(messages, list):
        out = []
        found_any_structure = False
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if isinstance(content, list):
                found_any_structure = True
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        out.append({
                            "name": block.get("name"),
                            "input": block.get("input"),
                        })
        if found_any_structure:
            return out

    # case 3: usage.tool_use_count のみ → fail-closed (None)
    usage = proc_result.get("usage")
    if isinstance(usage, dict) and "tool_use_count" in usage:
        return None

    # case 4: tool 呼び出しに関する痕跡が一切ない → 0 件として扱う
    return []


def extract_event_links(proc_result: dict) -> list:
    """proc_result から htmlLink 風の URL を抽出 (best-effort)."""
    import re
    links = []
    seen = set()

    def _walk(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                _walk(v)
        elif isinstance(obj, str):
            for m in re.findall(r"https?://[^\s\"']+", obj):
                if m not in seen:
                    seen.add(m)
                    links.append(m)

    _walk(proc_result)
    return [l for l in links if "calendar" in l.lower() or "google" in l.lower()] or links


# ---------------------------------------------------------------------------
# Discord 通知 (lib/notify.sh と同じ webhook を使う、stdlib のみ)
# ---------------------------------------------------------------------------

def notify_discord(message: str) -> None:
    if not _DISCORD_WEBHOOK:
        print(f"[notify] WARN: DISCORD_WEBHOOK_URL empty, skip: {message[:200]}",
              file=sys.stderr)
        return
    if len(message) > 1900:
        message = message[:1900] + "...(truncated)"
    data = json.dumps({"content": message}).encode("utf-8")
    req = urllib.request.Request(
        _DISCORD_WEBHOOK,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as e:
        print(f"[notify] WARN: Discord post failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    aid = os.environ.get("HERMES_APPROVAL_ID", "").strip()
    if not aid:
        print("ERROR: HERMES_APPROVAL_ID not set", file=sys.stderr)
        return 2

    # 1) 期限切れ row を sweep してから take
    approvals.sweep_expired()
    executor_job = approvals.ALLOWED_EXECUTORS["calendar.create"]
    row = approvals.take(aid, executor_job)
    if row is None:
        print(f"[NOOP] approval #{aid} not in 'approved' state (or expired)", file=sys.stderr)
        return 0

    # 2) payload 再検証 (副作用前失敗)
    try:
        approvals.validate_payload(row["action"], row["payload"])
    except ValueError as e:
        approvals.fail_during_executor(aid, result_text=f"validate: {e}", side_effect=False)
        notify_discord(f"[approval #{aid}] [FAIL] validate: {e}")
        return 1

    # 3) claude -p 起動
    prompt = render_calendar_create_prompt(row["payload"], aid)
    proc_result = invoke_claude_p(prompt)

    # 4) tool_use evidence の検証は is_error より先に行う (副作用検出の優先順)
    tool_calls = extract_tool_calls(proc_result)
    if tool_calls is None:
        msg = "tool_use evidence unavailable (claude CLI output format unsupported)"
        links = extract_event_links(proc_result)
        result_payload = json.dumps(
            {"side_effect_detected": True, "event_links": links, "reason": msg},
            ensure_ascii=False,
        )
        approvals.fail_during_executor(aid, result_text=result_payload, side_effect=True)
        notify_discord(
            f"[approval #{aid}] [WARN] {msg}\n"
            f"Created events (要確認): {links}\n"
            f"-> Calendar 側で event を確認し、不要なら手動削除してください"
        )
        return 1

    create_calls = [t for t in tool_calls if t.get("name") == approvals.MCP_CREATE_EVENT]
    other_names = [t.get("name") for t in tool_calls if t.get("name") != approvals.MCP_CREATE_EVENT]

    if len(create_calls) != 1 or other_names:
        msg = f"tool_use violation: create_event={len(create_calls)} other={other_names}"
        links = extract_event_links(proc_result)
        result_payload = json.dumps(
            {"side_effect_detected": True, "event_links": links, "reason": msg},
            ensure_ascii=False,
        )
        approvals.fail_during_executor(aid, result_text=result_payload, side_effect=True)
        notify_discord(
            f"[approval #{aid}] [WARN] {msg}\n"
            f"Created events: {links}\n"
            f"-> Calendar 側で余分な event を手動削除してください"
        )
        return 1

    # 5) input 完全一致 (取得できる場合のみ)
    actual_input = create_calls[0].get("input")
    if actual_input is not None:
        expected = expected_create_event_args(row["payload"])
        if actual_input != expected:
            diff = json.dumps(
                {"expected": expected, "actual": actual_input},
                ensure_ascii=False,
            )
            links = extract_event_links(proc_result)
            result_payload = json.dumps(
                {"side_effect_detected": True, "event_links": links,
                 "reason": "input mismatch", "diff": diff},
                ensure_ascii=False,
            )
            approvals.fail_during_executor(aid, result_text=result_payload, side_effect=True)
            notify_discord(
                f"[approval #{aid}] [WARN] input mismatch\n"
                f"```\n{diff[:1200]}\n```\n"
                f"Created events: {links}"
            )
            return 1

    # 6) ここで初めて is_error / ERROR result を判定
    #    tool_use evidence の検証より後なので、create_calls 件数で副作用有無を分岐できる
    result_text = proc_result.get("result", "") or ""
    is_err = bool(proc_result.get("is_error")) or result_text.startswith("ERROR:")
    if is_err:
        had_side_effect = len(create_calls) >= 1
        body = result_text or "claude is_error"
        approvals.fail_during_executor(aid, result_text=body, side_effect=had_side_effect)
        if had_side_effect:
            links = extract_event_links(proc_result)
            notify_discord(
                f"[approval #{aid}] [WARN] side-effect possible: {body[:200]}\n"
                f"Created events (要確認): {links}"
            )
        else:
            notify_discord(f"[approval #{aid}] [FAIL] {body[:200]}")
        return 1

    # 7) 正常完了
    approvals.done(aid, result_text=result_text)
    notify_discord(f"[approval #{aid}] [OK] {result_text[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
