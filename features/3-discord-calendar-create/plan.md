# plan: #3 承認ゲート付き書き込み: Discord 承認で Calendar.create を一時解禁する基盤 (v6)

slug: discord-calendar-create
milestone: Phase 1
labels: type:feature, batch:feature

v6 ノート: design レビュー round 5 の指摘 (rejection.md round 5 節) を反映。**feature flag default を `0` (opt-in)** にし、**flag off で import/regex/sweep をすべて skip**、**副作用後検出を `failed_after_side_effect` status に分離**、**approval_handler.handle() に user_id 引数 + 内部認可検証**、**extract_tool_calls input 不可時は常に副作用後検出経路**、**run-claude.sh export の既存 job 影響調査結果を記載**、**bot.py の import 一本化 (script execution 前提)**、**Bash tool 許可挙動を bin/run-claude.sh から具体的に明記**、**CLI contract 表追加**、**ID 衝突時の enqueue retry 仕様**、**executor_job 文字列の集約**、**MCP tool 名定数化**。

## 信頼境界の前提

承認ゲートは「Hermes-lite 自身の LLM が誤って Calendar に書き込まないようにする」防護で、「悪意ある攻撃者から保護する」ものではない。

## LLM executor の副作用後検出について

executor は `claude -p` 経由で MCP `create_event` を呼ぶ。tool 呼び出し件数 / 名前 / input は **claude プロセス完了後の出力 JSON から検証** するため、LLM が違反した場合 (`create_event` を 2 回呼ぶ / 別 tool を呼ぶ / payload と異なる引数で呼ぶ)、検出して `failed_after_side_effect` 遷移はできるが Calendar 側の副作用はすでに発生している。

副作用前失敗と副作用後検出を **status で区別**:
- 副作用前失敗 (`validate` 失敗 / claude `is_error`) → `status='failed'`
- 副作用後検出 (`tool_use_count != 1` / 別 tool / input mismatch / tool_use evidence 取得不能) → `status='failed_after_side_effect'`
- `result_text` に `{"side_effect_detected": true, "event_links": [...]}` を JSON で保存
- `failed_after_side_effect` は自動再試行不可。Calendar 側の余分 event を手動 cleanup してから新規 ID で再起票

## LLM executor vs 代替案 (採用根拠の比較表)

| 案 | 失敗モード保証 | 実装コスト | 採用判断 |
|---|---|---|---|
| **A: 現案 (LLM executor + 事後検証)** | 副作用後検出のみ。違反は手動 cleanup | 中 (sqlite + claude CLI + systemd-run) | **採用**: Phase 1 で最短経路、既存 MCP インフラを使い回せる |
| B: Discord に exact MCP コマンドを貼って人間が手動 create | 副作用前保証 (人間判断) | 小 | 不採用: 「承認 → 自動実行」の自動化ゴール (Issue body) を満たさない |
| C: Google API OAuth client を別途構築して直叩き | 副作用前保証 (deterministic) | 大 (OAuth client / refresh token / scope 管理 / 別 secret 経路) | 不採用: Phase 1 スコープ超過。将来 Issue として `features/.../followups.md` に分離 |
| D: Calendar.create を Phase 1 の対象外にする | — | — | 不採用: ROADMAP Phase 1 の goal (受信→カレンダー半自動登録) を直接ブロックする |

採用案 A の許容するリスク:
- LLM が `create_event` を 2 回呼ぶ → 検出して `failed_after_side_effect` / 余分 event は手動削除
- LLM が summary を改変 → input 検証で検出 (取れる場合) / 取れなければ `failed_after_side_effect` (デフォルト fail-closed)
- LLM が 0 回呼んで終わる → `tool_use_count != 1` で `failed_after_side_effect` (副作用なしだが status は明示)

## In-Scope / Out-of-Scope

| In-Scope | Out-of-Scope |
|---|---|
| `lib/approvals.py` (sqlite ヘルパー + state machine + schema version check + ID 衝突 retry + 認可ユーザー管理) | 承認 GUI / Discord Interactive Button |
| `lib/approvals_executor.py` (LLM executor + 副作用後検出 + `failed_after_side_effect` 遷移) | Discord 以外の承認チャネル |
| `lib/approvals.sh` | Calendar.create 以外の write action 解禁 |
| `var/approvals.sqlite` | mail-watch (#2) → proposer の自動橋渡し |
| `gateway/discord/bot.py` (flag check → optional import → approval 経路。flag off で完全に skip) | executor 失敗時の自動 retry |
| `gateway/discord/approval_handler.py` (handle(text, user_id) 内部認可検証) | 複数承認者の役割別承認 |
| `gateway/discord/config.py` に HERMES_HOME / APPROVALS_DB / APPROVAL_COMMANDS_ENABLED 追加 | 承認 rollback API |
| `jobs/approval-demo-proposer/{prompt.md, job.env}` (Bash で `python3 -c` 使用、jq 非依存) | DB schema v2 以降への自動 migration |
| `bin/run-claude.sh` に `export HERMES_HOME=...` の 1 行追加 | 短縮 ID / prefix lookup |
| `docs/discord-approval.md` (信頼境界 + 副作用後検出 + failed_after_side_effect 説明 + feature flag opt-in + migration notice + CLI contract) | 重複検知 |
| `tests/test_approvals.py` (Python 標準 unittest) | bot プロセスのリスタート手順自動化 |
| `.gitignore` に `var/*` + `!var/.gitkeep` 追加 | MCP server / Google Calendar API の直接呼び出し |
| `var/.gitkeep` | Calendar 側余分 event の自動 cleanup |
| | 別 MCP server 名 / profile 対応 (MCP tool 名は定数固定) |

## Non-Goals

- **`lib/disallowed-tools.txt` は本 Issue で書き換えない**。Calendar.create は disallowed のまま、executor の `--allowed-tools` だけで一時解禁。
- **`gateway/discord/claude_runner.py` は触らない**。
- **`gateway/discord/requirements.txt` には新規依存を追加しない** (標準ライブラリのみで完結)。
- **MCP server 直接呼び出し / Google Calendar API 直叩き executor は採用しない** (比較表 C 参照)。
- **systemd-run 後の即時失敗観測の自動化はしない** (stale executing / approved の自動 sweep で最終的に整合)。
- **DB schema v2 以降への migration は本 Issue では実装しない**。
- **別 MCP server 名 / 別 profile での Calendar.create 対応はしない** (MCP tool 名は定数固定: `mcp__claude_ai_Google_Calendar__create_event`)。

## 既存環境調査結果 (run-claude.sh export 化の影響)

- 既存 jobs: `mail-watch`, `ping` (2 件)
- `grep -rn HERMES_HOME` の結果: `bin/run-claude.sh` (定義 + 利用) と `gateway/discord/claude_runner.py` (独自定義) のみ
- 既存 jobs の `prompt.md` / `job.env` では `HERMES_HOME` を別意味で使っていない
- → export 化の副作用: subprocess (`claude -p`) に新たに `HERMES_HOME` 環境変数が見えるが、既存 jobs はこれを参照しないので無害
- T17a (ping) / T17b (mail-watch) で smoke test

## bin/run-claude.sh の Bash tool 許可挙動 (proposer の前提)

`bin/run-claude.sh:118-122`:

```bash
if [[ -n "${ALLOWED_TOOLS// /}" ]]; then
  ALLOWED_ARR=(${ALLOWED_TOOLS})
  CLAUDE_ARGS+=(--allowed-tools "${ALLOWED_ARR[@]}")
fi
```

- `ALLOWED_TOOLS=""` のとき条件 false → `--allowed-tools` を一切渡さない → Claude のデフォルト tool set (Bash 含む) が使える
- 同時に `--disallowed-tools` には `lib/disallowed-tools.txt` 全体が渡される
- disallowed-tools.txt には `Bash(rm *)`, `Bash(sudo *)`, `Bash(git push*)`, `Bash(git reset*)` のみで、Bash 自体は禁止していない
- 結果: `ALLOWED_TOOLS=""` の proposer は `Bash(echo *)`, `Bash(python3 *)`, `Bash(date *)`, `Bash(cat *)` を自由に使える

## 設計方針

### 全体アーキテクチャ

```
[proposer ジョブ (LLM が prompt の Bash ブロックを 1 度実行するだけ)]
  ・python3 -c で payload 生成 (jq 非依存)
  ・approvals.py enqueue (CLI)
  ・stdout の id を本文に貼って Discord 通知

[Discord bot]
  ・HERMES_APPROVAL_COMMANDS_ENABLED=1 のときのみ approval 経路を有効化
  ・default=0 (opt-in、既存挙動完全互換)
  ・flag off では approval_handler import / regex / sweep すべて skip
  ・"approval (approve|reject) [#]<8hex>" + ALLOWED_USER_IDS 検証
  ・approvals.decide() (内部で expires_at > now を atomic 検査)
  ・systemd-run で executor 起動 (HERMES_APPROVAL_ID を setenv)
  ・systemd-run 失敗時 fail_before_executor()
  ・1h ごとに sweep_expired / sweep_stale_approved / sweep_stale_executing

[executor: lib/approvals_executor.py]
  ・take(id, executor_job) で executing 遷移 (expires_at > now を atomic 検査)
  ・固定テンプレに payload を fill-in
  ・claude -p (--allowed-tools create_event のみ)
  ・出力 JSON から tool_use evidence 取得
    - 取れる + 件数 1 + name 一致 + input 一致 → done()
    - それ以外 → fail_during_executor() (`failed_after_side_effect`)
  ・Discord 通知 (副作用後検出時は htmlLink リスト + 手動 cleanup 指示)
```

### 重要な構造的決定

1. **書き込み権限の分離**: Calendar.create を allow するのは executor 内の `claude -p` プロセス**のみ**。
2. **proposer は LLM の判断余地最小化**: prompt は「以下の Bash ブロックを **そのまま 1 度だけ** 実行し stdout を最終応答にする」型。
3. **executor の prompt は固定テンプレ**: payload を JSON ブロック注入、自然言語指示は固定。
4. **LLM 裁量の事後検出 (副作用後)**: `tool_use_count == 1` + name + input 完全一致を assert。違反は `failed_after_side_effect` (副作用前失敗 `failed` とは別 status)。
5. **TTL の atomic 検査**: decide() / take() の WHERE に `expires_at > now` 必須。
6. **stale 状態の自動回収 (3 種類)**:
   - `sweep_expired()`: pending → expired (TTL 切れ)
   - `sweep_stale_approved()`: approved → failed (`decided_at < now - 600`、10 min、executor 起動失敗の救済)
   - `sweep_stale_executing()`: executing → failed (`started_at < now - 1800`、30 min)
7. **1 回限り解禁**: take() は atomic UPDATE で affected==1 のときのみ row 返却。
8. **ID 一意指定**: bot は `--setenv=HERMES_APPROVAL_ID=<id>` で systemd-run。
9. **HERMES_HOME 単一決定点**: `config.py` を唯一の決定点。approval_handler は明示的に subprocess env コピー。lib/CLI 経路の fallback は同一アルゴリズム (Path 自己導出) で T13 検証。
10. **feature flag opt-in**: `HERMES_APPROVAL_COMMANDS_ENABLED` default `"0"`。`"1"` で初めて approval 機能を有効化。flag off では module load 時に import すらしない。
11. **handler 不在時の予約語捕捉**: flag on + handler import 失敗時のみ bot 内 regex で予約語を捕捉し `[WARN] approval feature disabled` を返す。flag off では予約語を `_handle` に流す (= 既存挙動)。
12. **bot.py の import 一本化**: script execution 前提 (`/usr/bin/python3 gateway/discord/bot.py` で起動)。`from config import ...` / `import approval_handler` (relative なし)。
13. **executor_job 文字列の集約**: `ALLOWED_EXECUTORS["calendar.create"]` を唯一のソース。
14. **MCP tool 名の定数化**: `MCP_CREATE_EVENT = "mcp__claude_ai_Google_Calendar__create_event"` を `lib/approvals.py` で定義、他モジュールは import 参照。
15. **承認者の認可境界**: bot.py の `_should_react` 前段 + `approval_handler.handle(text, user_id)` の内部検証の二重チェック。
16. **DB に `decided_by` 列追加**: 将来の audit 用、Phase 1 では記録のみ。
17. **承認の状態保持**: sqlite 1 ファイル。`PRAGMA user_version=1` と起動時整合性チェック。
18. **TTL 既定 24h** (`HERMES_APPROVAL_TTL_SEC=86400` で上書き可)。
19. **sweep_loop の重複起動防止**: module-level task 参照。

### 状態遷移表 (v6)

| 現 status | 許可される遷移先 | 遷移を起こす API | atomic な WHERE 条件 | affected != 1 時 |
|---|---|---|---|---|
| pending | approved | `decide(id, "approve", user_id)` | `id=? AND status='pending' AND expires_at > now` | None を返す |
| pending | rejected | `decide(id, "reject", user_id)` | `id=? AND status='pending' AND expires_at > now` | None を返す |
| pending | expired | `sweep_expired()` | `status='pending' AND expires_at < now` | (affected count を return) |
| approved | executing | `take(id, executor_job)` | `id=? AND executor_job=? AND status='approved' AND expires_at > now` | None を返す |
| approved | failed (bot systemd-run 失敗、副作用前) | `fail_before_executor(id)` | `id=? AND status='approved'` | ValueError |
| approved | failed (stale sweep) | `sweep_stale_approved()` | `status='approved' AND decided_at < now - 600` | (count) |
| executing | executed | `done(id)` | `id=? AND status='executing'` | ValueError |
| executing | failed (副作用前: validate/is_error) | `fail_during_executor(id, side_effect=False)` | `id=? AND status='executing'` | ValueError |
| executing | failed_after_side_effect (副作用後検出) | `fail_during_executor(id, side_effect=True)` | `id=? AND status='executing'` | ValueError |
| executing | failed (stale sweep) | `sweep_stale_executing()` | `status='executing' AND started_at < now - 1800` | (count) |
| rejected / executed / failed / failed_after_side_effect / expired | (遷移不可) | — | — | — |

不変条件: `created_at <= expires_at = created_at + ttl_sec`、各 *_at は対応 API でセット。

### sqlite テーブル

```sql
PRAGMA user_version = 1;

CREATE TABLE IF NOT EXISTS approvals (
  id           TEXT PRIMARY KEY,    -- 8 hex (固定長)
  proposer_job TEXT NOT NULL,
  executor_job TEXT NOT NULL,
  action       TEXT NOT NULL,       -- "calendar.create"
  summary      TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status       TEXT NOT NULL,       -- pending / approved / rejected / executing / executed / expired / failed / failed_after_side_effect
  created_at   INTEGER NOT NULL,
  expires_at   INTEGER NOT NULL,
  decided_at   INTEGER,
  decided_by   INTEGER,             -- audit: Discord user_id
  started_at   INTEGER,
  finished_at  INTEGER,
  result_text  TEXT
);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
CREATE INDEX IF NOT EXISTS idx_approvals_expires ON approvals(expires_at);
CREATE INDEX IF NOT EXISTS idx_approvals_decided ON approvals(decided_at);
CREATE INDEX IF NOT EXISTS idx_approvals_started ON approvals(started_at);
```

### payload → MCP `create_event` field 対応表

| payload key | MCP create_event 引数 |
|---|---|
| `summary` (str, 1..256) | `summary` |
| `start` (ISO 8601 with tz) | `start.dateTime` |
| `end` (ISO 8601 with tz) | `end.dateTime` |
| `timeZone` (str, IANA) | `start.timeZone` と `end.timeZone` の両方 |
| `description` (str, ≤2000, optional) | `description` |
| `location` (str, ≤256, optional) | `location` |

validate_payload: `end > start` / `start > now - 30min` / 未知キー禁止 / 必須キー欠落禁止。

### `lib/approvals.py` の API (v6)

```python
from typing import Optional

ALLOWED_ACTIONS = {"calendar.create"}
ALLOWED_EXECUTORS = {"calendar.create": "calendar-create-executor"}
MCP_CREATE_EVENT = "mcp__claude_ai_Google_Calendar__create_event"
_EXECUTING_TTL_SEC = 1800
_APPROVED_TTL_SEC = 600
_ID_RETRY_MAX = 5

# 共通 row schema (get / take / list_rows の返り値要素):
# {
#   "id": str, "proposer_job": str, "executor_job": str, "action": str,
#   "summary": str, "payload": dict, "payload_json": str, "status": str,
#   "created_at": int, "expires_at": int,
#   "decided_at": Optional[int], "decided_by": Optional[int],
#   "started_at": Optional[int], "finished_at": Optional[int],
#   "result_text": Optional[str],
# }

def enqueue(*, proposer_job: str, executor_job: str, action: str,
            summary: str, payload: dict, ttl_sec: Optional[int] = None) -> str:
    """
    検証:
    - action in ALLOWED_ACTIONS
    - executor_job == ALLOWED_EXECUTORS[action] (mismatch は ValueError)
    - validate_payload(action, payload)
    ID 生成: secrets.token_hex(4) を最大 _ID_RETRY_MAX 回試行 (PRIMARY KEY 衝突時)
    全リトライ失敗で RuntimeError (CLI exit 3)
    """

def validate_payload(action: str, payload: dict) -> None: ...
def decide(approval_id: str, decision: str, *, user_id: Optional[int] = None) -> Optional[str]: ...
def take(approval_id: str, executor_job: str) -> Optional[dict]: ...
def done(approval_id: str, *, result_text: str) -> None: ...
def fail_before_executor(approval_id: str, *, result_text: str) -> None: ...
def fail_during_executor(approval_id: str, *, result_text: str, side_effect: bool = False) -> None:
    """side_effect=True なら status='failed_after_side_effect' に遷移"""
def sweep_expired() -> int: ...
def sweep_stale_approved() -> int: ...
def sweep_stale_executing() -> int: ...
def get(approval_id: str) -> Optional[dict]: ...
def list_rows(*, status: Optional[str] = None) -> list: ...
def get_authorized_user_ids() -> set:
    """
    環境変数 HERMES_APPROVAL_AUTHORIZED_USER_IDS (カンマ区切り) を読む。
    未設定/空文字なら HERMES_APPROVAL_ALLOWED_USER_IDS_FALLBACK (カンマ区切り、bot.py 側で
    ALLOWED_USER_IDS を export しておく) を使う。これも未設定なら空集合 (= 拒否)。
    運用者は HERMES_APPROVAL_AUTHORIZED_USER_IDS ⊆ ALLOWED_USER_IDS を保つこと
    (両方設定する場合)。
    """
```

### CLI Contract 表 (v6)

| サブコマンド | 引数 | stdin | stdout (success) | stderr (failure) | exit 0 | exit 1 | exit 2 | exit 3 |
|---|---|---|---|---|---|---|---|---|
| `enqueue` | `--proposer X --executor Y --action Z --summary S [--ttl N]` | payload JSON | 1 行: `<8hex id>` | `ERROR: validate failed: ...` / `ERROR: id collision exhausted` | 成功 | validate 失敗 | — | ID 衝突 5 回超 |
| `decide` | `--id X --decision approve|reject [--user-id N]` | — | 遷移後 status (例: `approved`) | `ERROR: decide failed` | 成功 | None (pending でない / 期限切れ) | — | — |
| `take` | `--id X --executor Y` | — | 共通 row schema JSON 1 行 | `ERROR: no approved row` | 成功 | None | — | — |
| `done` | `--id X --result-text T` | — | (空) | `ERROR: done failed: <理由>` | 成功 | ValueError | — | — |
| `fail-before` | `--id X --result-text T` | — | (空) | `ERROR: fail-before failed` | 成功 | ValueError | — | — |
| `fail-during` | `--id X --result-text T [--side-effect]` | — | (空) | `ERROR: fail-during failed` | 成功 | ValueError | — | — |
| `sweep` | (なし) | — | `swept-expired N` | `ERROR: sweep failed` | 成功 | — | — | — |
| `sweep-stale-approved` | (なし) | — | `swept-stale-approved N` | 同上 | 成功 | — | — | — |
| `sweep-stale-executing` | (なし) | — | `swept-stale-executing N` | 同上 | 成功 | — | — | — |
| `get` | `--id X` | — | 共通 row schema JSON 1 行 | (空) | 成功 | 存在しない | — | — |
| `list` | `[--status pending|approved|...]` | — | 共通 row schema JSON 配列 | (空) | 成功 | — | — | — |

JSON schema: 共通 row schema を json.dumps (ensure_ascii=False, default ISO 8601 はないので unix sec のまま)。

### `lib/approvals_executor.py` の流れ (v6)

```python
def main() -> int:
    aid = os.environ.get("HERMES_APPROVAL_ID")
    if not aid:
        print("ERROR: HERMES_APPROVAL_ID not set", file=sys.stderr)
        return 2

    approvals.sweep_expired()
    row = approvals.take(aid, approvals.ALLOWED_EXECUTORS["calendar.create"])
    if row is None:
        print("[NOOP] approval not in 'approved' state (or expired)", file=sys.stderr)
        return 0

    try:
        approvals.validate_payload(row["action"], row["payload"])
    except ValueError as e:
        # 副作用前失敗
        approvals.fail_during_executor(aid, result_text=f"validate: {e}", side_effect=False)
        notify_discord(f"[approval #{aid}] [FAIL] validate: {e}")
        return 1

    prompt = render_calendar_create_prompt(row["payload"], aid)
    proc_result = invoke_claude_p(prompt)

    # tool_use evidence は is_error/ERROR よりも先に確認する
    # (Calendar 側 event 作成後に Claude 側がエラー応答するケースがあるため)
    # tool_use evidence 取得
    tool_calls = extract_tool_calls(proc_result)
    if tool_calls is None:
        # evidence 取得不能 → fail-closed (副作用後検出経路、event は作られている可能性大)
        msg = "tool_use evidence unavailable (claude CLI output format unsupported)"
        links = extract_event_links(proc_result)
        result_payload = json.dumps({"side_effect_detected": True, "event_links": links, "reason": msg})
        approvals.fail_during_executor(aid, result_text=result_payload, side_effect=True)
        notify_discord(f"[approval #{aid}] [WARN] {msg}\nCreated events (確認要): {links}\n→ Calendar 側で event を確認し、不要なら手動削除")
        return 1

    create_calls = [t for t in tool_calls if t.get("name") == approvals.MCP_CREATE_EVENT]
    other_names = [t.get("name") for t in tool_calls if t.get("name") != approvals.MCP_CREATE_EVENT]

    if len(create_calls) != 1 or other_names:
        msg = f"tool_use violation: create_event={len(create_calls)} other={other_names}"
        links = extract_event_links(proc_result)
        result_payload = json.dumps({"side_effect_detected": True, "event_links": links, "reason": msg})
        approvals.fail_during_executor(aid, result_text=result_payload, side_effect=True)
        notify_discord(f"[approval #{aid}] [WARN] {msg}\nCreated events: {links}\n→ Calendar 側で余分な event を手動削除")
        return 1

    actual_input = create_calls[0].get("input")
    if actual_input is not None:
        expected = expected_create_event_args(row["payload"])
        if actual_input != expected:
            diff = json.dumps({"expected": expected, "actual": actual_input}, ensure_ascii=False)
            links = extract_event_links(proc_result)
            result_payload = json.dumps({"side_effect_detected": True, "event_links": links, "reason": "input mismatch", "diff": diff})
            approvals.fail_during_executor(aid, result_text=result_payload, side_effect=True)
            notify_discord(f"[approval #{aid}] [WARN] input mismatch\n{diff}\nCreated events: {links}")
            return 1

    result_text = proc_result.get("result", "")
    is_err = proc_result.get("is_error") or result_text.startswith("ERROR:")
    if is_err:
        # tool_use を 1 回成功カウントしている = create_event が走っている可能性大 → side_effect=True
        # 0 回 (空 tool_calls) なら確実に副作用なし → side_effect=False
        had_side_effect = len(create_calls) >= 1
        approvals.fail_during_executor(aid, result_text=result_text or "claude is_error", side_effect=had_side_effect)
        tag = "[WARN] side-effect possible" if had_side_effect else "[FAIL]"
        if had_side_effect:
            links = extract_event_links(proc_result)
            notify_discord(f"[approval #{aid}] {tag} {result_text}\nCreated events (要確認): {links}")
        else:
            notify_discord(f"[approval #{aid}] {tag} {result_text}")
        return 1

    approvals.done(aid, result_text=result_text)
    notify_discord(f"[approval #{aid}] [OK] {result_text[:200]}")
    return 0
```

`expected_create_event_args(payload)` は plan v5 と同じ。

#### `extract_tool_calls()` の挙動 (v6)

`Optional[list[dict]]` を返す:

1. `proc_result["tool_uses"]` (リスト of `{name, input}`) → そのまま list[dict]
2. `proc_result["messages"]` 走査で `content[].type == "tool_use"` → list[{name, input}]
3. 上 2 つで取れず `proc_result["usage"]["tool_use_count"]` のみある場合 → **None を返す** (= fail-closed)
4. どれもマッチしない (claude が tool を呼ばなかった場合も含む) → 空リスト `[]`

実装フェーズで `claude -p --output-format json` を試走して構造を確認 → `features/.../claude-cli-tool-use-evidence.md` に保存。

### `gateway/discord/bot.py` の追加ロジック (v6)

#### file 先頭 import (after)

```python
from __future__ import annotations
import asyncio, logging, re
from typing import Optional
from collections import defaultdict
import discord

import claude_runner
from config import (
    ALLOWED_USER_IDS, DISCORD_TOKEN, INPUT_CHANNEL_IDS, MAX_DISCORD_MESSAGE, SESSIONS_DB,
    HERMES_HOME, APPROVALS_DB, APPROVAL_COMMANDS_ENABLED,  # 新規 3 つ
)
from session_store import SessionStore

# 既存ログ設定 ...

# approval 機能は flag check の後に初期化 (flag off では何もロードしない)
_approval_handler = None
_APPROVAL_PATTERN = None
_sweep_task: Optional[asyncio.Task] = None

if APPROVAL_COMMANDS_ENABLED:
    _APPROVAL_PATTERN = re.compile(
        r"^\s*approval\s+(approve|reject)\s+#?[a-f0-9]{8}\s*$",
        re.IGNORECASE,
    )
    try:
        import approval_handler
        _approval_handler = approval_handler
    except Exception:
        log.warning("approval_handler import failed; approval feature disabled (reserved-word capture remains)", exc_info=True)
        _approval_handler = None
```

#### before/after — `on_message`

**before (bot.py:139-148):**

```python
@client.event
async def on_message(message: discord.Message) -> None:
    if not _should_react(message):
        if not message.author.bot and message.author.id not in ALLOWED_USER_IDS:
            log.warning(
                "unauthorized user=%s channel=%s",
                message.author.id, type(message.channel).__name__,
            )
        return
    await _handle(message)
```

**after:**

```python
@client.event
async def on_message(message: discord.Message) -> None:
    if not _should_react(message):
        if not message.author.bot and message.author.id not in ALLOWED_USER_IDS:
            log.warning(
                "unauthorized user=%s channel=%s",
                message.author.id, type(message.channel).__name__,
            )
        return
    stripped = _strip_mention(message.content)
    if APPROVAL_COMMANDS_ENABLED and _APPROVAL_PATTERN is not None and _APPROVAL_PATTERN.match(stripped):
        if _approval_handler is None:
            await message.channel.send("⚠️ [WARN] approval feature disabled (import failed; see journalctl)")
            return
        try:
            reply = await asyncio.to_thread(_approval_handler.handle, stripped, message.author.id)
        except Exception:
            log.exception("approval handler crashed")
            await message.channel.send("⚠️ [WARN] approval 処理で内部エラー (journalctl 参照)")
            return
        await message.channel.send(reply)
        return
    await _handle(message)
```

#### before/after — `on_ready`

**before (bot.py:123-127):**

```python
@client.event
async def on_ready() -> None:
    user = client.user
    log.info("logged in as %s (id=%s)", user, user.id if user else "?")
    log.info("allowed user ids: %s", ALLOWED_USER_IDS)
```

**after:**

```python
@client.event
async def on_ready() -> None:
    global _sweep_task
    user = client.user
    log.info("logged in as %s (id=%s)", user, user.id if user else "?")
    log.info("allowed user ids: %s", ALLOWED_USER_IDS)
    if APPROVAL_COMMANDS_ENABLED and _approval_handler is not None:
        if _sweep_task is None or _sweep_task.done():
            _sweep_task = client.loop.create_task(_approval_sweep_loop())

async def _approval_sweep_loop():
    while True:
        try:
            swept_exp = await asyncio.to_thread(_approval_handler.sweep_expired)
            swept_appr = await asyncio.to_thread(_approval_handler.sweep_stale_approved)
            swept_exec = await asyncio.to_thread(_approval_handler.sweep_stale_executing)
            if swept_exp or swept_appr or swept_exec:
                log.info("approval sweep: %d expired, %d stale-approved, %d stale-executing",
                         swept_exp, swept_appr, swept_exec)
        except Exception:
            log.exception("approval sweep failed")
        await asyncio.sleep(3600)
```

#### `gateway/discord/approval_handler.py` の輪郭 (v6)

```python
import re, sys, time, subprocess, os
from typing import Optional
from pathlib import Path

# config.py を唯一の HERMES_HOME 決定点として参照
from config import HERMES_HOME, APPROVALS_DB

sys.path.insert(0, str(HERMES_HOME / "lib"))
import approvals  # noqa

SYSTEMD_RUN = os.environ.get("HERMES_SYSTEMD_RUN_BIN", "systemd-run")

APPROVAL_RE = re.compile(
    r"^\s*approval\s+(?P<verb>approve|reject)\s+#?(?P<id>[a-f0-9]{8})\s*$",
    re.IGNORECASE,
)

def looks_like_approval(text: str) -> bool:
    return APPROVAL_RE.match(text) is not None

def handle(text: str, user_id: int) -> str:
    # 内部認可検証 (bot.py 側 _should_react と二重化)
    authorized = approvals.get_authorized_user_ids()
    if user_id not in authorized:
        return f"⚠️ [WARN] unauthorized user_id={user_id}"

    m = APPROVAL_RE.match(text)
    assert m is not None
    verb = m.group("verb").lower()
    aid = m.group("id").lower()
    row = approvals.get(aid)
    if row is None:
        return f"⚠️ [WARN] #{aid} は不明 (期限切れ or タイポ)"
    if row["status"] != "pending":
        return f"⚠️ [WARN] #{aid} はすでに {row['status']} (重複承認不可)"
    decision = "approve" if verb == "approve" else "reject"
    after = approvals.decide(aid, decision, user_id=user_id)
    if after is None:
        latest = approvals.get(aid)
        if latest and latest["status"] == "expired":
            return f"⚠️ [WARN] #{aid} は期限切れ"
        return f"⚠️ [WARN] #{aid} の decide に失敗 (直前に他経路で遷移済み)"
    if after == "rejected":
        return f"❌ [REJECTED] #{aid} 却下"

    unit = f"hermes-exec-{aid}-{int(time.time())}"
    cmd = [
        SYSTEMD_RUN, "--user", "--no-block",
        f"--unit={unit}",
        f"--working-directory={HERMES_HOME}",
        f"--setenv=HERMES_APPROVAL_ID={aid}",
        f"--setenv=HERMES_HOME={HERMES_HOME}",
        f"--setenv=HERMES_APPROVALS_DB={APPROVALS_DB}",
        f"--setenv=PATH={os.environ.get('PATH', '')}",
        "/usr/bin/python3", str(HERMES_HOME / "lib" / "approvals_executor.py"),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=10)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
        err = (getattr(e, "stderr", "") or str(e)).strip()
        try:
            approvals.fail_before_executor(aid, result_text=f"systemd-run failed: {err}")
        except Exception:
            pass
        return f"⚠️ [WARN] #{aid} 承認は記録したが executor 起動失敗 → failed に変更\n```\n{err[:400]}\n```"
    return f"✅ [OK] #{aid} 承認 → executor 起動 (unit={unit})"

def sweep_expired() -> int:
    return approvals.sweep_expired()

def sweep_stale_approved() -> int:
    return approvals.sweep_stale_approved()

def sweep_stale_executing() -> int:
    return approvals.sweep_stale_executing()
```

### `jobs/approval-demo-proposer/`

`job.env`:

```bash
ALLOWED_TOOLS=""
MAX_TURNS="3"
TIMEOUT_SEC="60"
MAX_BUDGET_USD="0.50"
MODEL="sonnet"
NOTIFY_RESULT="1"
NOTIFY_ON_ERROR="1"
```

`prompt.md` (v6 = v5 と同じ、jq 非依存 / `python3 -c` で payload 生成)

### `bin/run-claude.sh` の編集 (1 行差分)

**before (bin/run-claude.sh:28):**

```bash
HERMES_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
```

**after:**

```bash
export HERMES_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
```

既存 jobs (ping / mail-watch) は HERMES_HOME を参照しないので無害 (上「既存環境調査結果」参照)。T17a / T17b で smoke test。

### `gateway/discord/config.py` 追加

```python
HERMES_HOME = Path(os.environ.get(
    "HERMES_HOME",
    str(Path(__file__).resolve().parents[2]),
))
APPROVALS_DB = Path(os.environ.get(
    "HERMES_APPROVALS_DB",
    str(HERMES_HOME / "var" / "approvals.sqlite"),
))
APPROVAL_COMMANDS_ENABLED = os.environ.get("HERMES_APPROVAL_COMMANDS_ENABLED", "0") == "1"
```

### docs/discord-approval.md

- アーキテクチャ図
- 信頼境界 (再掲)
- 副作用後検出のリスクと手動 cleanup
- LLM executor vs 代替案 比較表
- DB schema + 状態遷移表
- 承認コマンド: `approval approve <8hex>` / `approval reject <8hex>` (`#` 任意、case-insensitive)
- **feature flag (opt-in)**: default `HERMES_APPROVAL_COMMANDS_ENABLED=0`。有効化手順を明記
- **migration notice (予約語化)**: flag を有効化したとき初めて予約語化される
- TTL / sweep 3 種類 (`pending` 24h / `approved` 10min / `executing` 30min)
- CLI Contract 表
- failure recovery 手順:
  - systemd-run 失敗 → bot が `failed` に落とす → 新規 ID で再起票
  - executor 副作用前失敗 → `failed` → 新規 ID で再起票
  - executor **副作用後検出** → `failed_after_side_effect` → Calendar 側で event 確認 + 不要なら手動削除 → 新規 ID で再起票
  - executor 即時失敗 (import error 等) → `journalctl --user -u hermes-exec-...` で確認。30 min 後に sweep で `failed`
  - DB schema mismatch → `mv var/approvals.sqlite var/approvals.sqlite.bak.<ts>` → bot 再起動 (既存 pending/approved 破棄)
- セキュリティ注意点
- 認可ユーザー設定: `HERMES_APPROVAL_AUTHORIZED_USER_IDS=12345,67890` (環境変数、カンマ区切り)

### .gitignore 追記

```
var/*
!var/.gitkeep
```

## 実装対象

### 新規作成

- `lib/approvals.py`
- `lib/approvals_executor.py`
- `lib/approvals.sh`
- `gateway/discord/approval_handler.py`
- `jobs/approval-demo-proposer/prompt.md`
- `jobs/approval-demo-proposer/job.env`
- `docs/discord-approval.md`
- `tests/test_approvals.py`
- `var/.gitkeep`
- `features/3-discord-calendar-create/claude-cli-tool-use-evidence.md`

### 編集

- `gateway/discord/bot.py`
- `gateway/discord/config.py`
- `bin/run-claude.sh` (1 行差分)
- `.gitignore`

### 触らない (Non-Goal 維持)

- `lib/disallowed-tools.txt`
- `gateway/discord/claude_runner.py`
- `gateway/discord/requirements.txt`

## テスト計画 (v6)

- 自動 (tests/test_approvals.py): state machine + sqlite + ID 衝突 retry + CLI contract
- 手動 (features/.../test-spec.md): E2E (bot / executor / Discord / systemd-run / Calendar)

| ID | 区分 | 内容 | 期待値 |
|---|---|---|---|
| T01_enqueue | 手動 | `bin/run-claude.sh approval-demo-proposer` 起動 | pending row 1 件 + Discord に承認依頼本文 |
| T02_approval_executes | 手動 | (flag=1 で bot 起動後) `approval approve <id>` 投稿 | OK 応答 / systemd unit / create_event 1 回 / row=`executed` |
| T03_approval_rejects | 手動 | `approval reject <id>` | row=`rejected` / executor 起動なし |
| T04_unauth_user | 手動 | ALLOWED_USER_IDS 外ユーザー | unauthorized 警告 / DB 変化なし |
| T05_expire | 自動 | TTL 切れ pending insert → sweep_expired | row=`expired` |
| T06_double_take | 自動 | approved に take 2 回 | 1 回目 row 返却、2 回目 None |
| T07_unknown_id | 手動 | `approval approve deadbeef` (flag=1) | bot WARN / DB 変化なし |
| T08_double_decide | 自動+手動 | pending を approve 後再 approve | WARN / 二重起動なし |
| T09_invalid_payload | 自動 | 未知キー / `end<=start` / 過去日時 / executor mismatch | ValueError + exit 1 |
| T10_disallowed_unchanged | 手動 | `disallowed-tools.txt` sha256 比較 | 完全一致 |
| T11a_question_fallback | 手動 | `yes` / `yes abcd1234` (prefix なし) | claude-runner 経路 |
| T11b_unknown_id_no_fallback | 手動 | `approval approve deadbeef` (flag=1, DB 無し) | bot WARN / claude-runner 流れない |
| T11c_regex_variations | 手動 | `APPROVAL APPROVE  ABCD1234`, `#abcd1234` | 同じ aid 処理 |
| T12_done_state_guard | 自動 | pending に done | ValueError + DB 変化なし |
| T13_db_path_consistency | 手動 | proposer enqueue 直後に CLI get | 同 row / 同 inode |
| T14_systemd_run_failure | 手動 | `HERMES_SYSTEMD_RUN_BIN=/nonexistent` で bot 再起動 + approve | bot WARN / row=`failed` |
| T15_schema_version_mismatch | 自動 | tmpfile DB `user_version=99` → get | RuntimeError |
| T16_tool_use_count_violation | 手動 (mock) | mock claude で create_event 2 回 | row=`failed_after_side_effect` / WARN + links |
| T17a_run_claude_export_ping | 手動 | export 化後 `bin/run-claude.sh ping` | exit 0 / 既存挙動と同等 |
| T17b_run_claude_export_mail_watch | 手動 | export 化後 `bin/run-claude.sh mail-watch` | exit 0 / 既存挙動と同等 |
| T18_stale_executing_sweep | 自動 | `executing` で `started_at=now-1900` → sweep | row=`failed` |
| T19_handler_disabled_reservation | 手動 | (flag=1) approval_handler.py rename + bot 起動 + `approval approve <id>` | bot `[WARN] approval feature disabled` / `_handle` に流れない |
| T20_stale_approved_sweep | 自動 | `approved` で `decided_at=now-700` → sweep | row=`failed` |
| T21_decide_after_expire_atomic | 自動 | pending で `expires_at < now` → decide approve | None / row=pending (sweep 待ち) |
| T22_tool_use_input_mismatch | 手動 (mock) | mock claude で input 改変 1 回 | row=`failed_after_side_effect` / WARN + diff + links |
| T23_enqueue_executor_mismatch | 自動 | `enqueue(executor_job="wrong-job", action="calendar.create", ...)` | ValueError |
| T24_list_cli | 自動 | 各 status 投入 → `list --status pending` 等 | 該当 row 配列 |
| T25_feature_flag_off | 手動 | (default `0` で) bot 起動 + `approval approve <id>` | claude-runner 経路 / approval_handler import すらされない |
| T26_unauth_handler_call | 自動 | `handle("approval approve abcd1234", user_id=999)` (HERMES_APPROVAL_AUTHORIZED_USER_IDS に含まない) | `unauthorized user_id=999` 返却 / DB 変化なし |
| T27_id_collision_retry | 自動 | pre-insert で 1 ID を占有 → enqueue 数百回 | 衝突して別 ID で成功 / 5 回連続なら RuntimeError + exit 3 |
| T28_tool_use_evidence_unavailable | 自動 (mock) | extract_tool_calls が None を返す proc_result | row=`failed_after_side_effect` / "evidence unavailable" 通知 |

## ロールバック方針

1. `gateway/discord/bot.py` の approval 分岐を git revert
2. `bin/run-claude.sh` の `export` を git revert
3. `var/approvals.sqlite` を rename
4. `lib/approvals_executor.py` は残存しても害なし

## Issue body 抜粋

(元 Issue 本文は本 plan の根拠として参照済み。Issue 本文は変更しない)
