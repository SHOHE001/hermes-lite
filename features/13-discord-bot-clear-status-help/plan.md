# plan: #13 Discord bot にスラッシュコマンド機構（/clear /status /help から）

slug: discord-bot-clear-status-help
milestone: Phase 3
labels: type:feature, batch:feature

> Codex design review round 1（blocking 6）+ round 2（blocking 7）を反映済み。反映内容は各セクションに `[R1 …]` `[R2 …]` で明示。棄却は `rejection.md` を参照。

## In-Scope / Out-of-Scope

| In-Scope | Out-of-Scope |
|---|---|
| `on_message` に `/` コマンド分岐を追加（`_strip_mention` 後が `is_command` にマッチすればコマンド、他は従来通り `_handle`） | `/intake` `/compact` `/jobs` `/gloop-status` の実装（別 PR） |
| `commands/` パッケージ（1 コマンド 1 ファイル + `__init__.py` レジストリ + `dispatch`） | Discord ネイティブ slash command（`app_commands`）登録 — 本 Issue は `message.content` プレフィックス方式 |
| MVP 3 コマンド: `/clear` `/status` `/help`（Issue タイトルが明示） | コマンド引数の**解釈**。args は handler まで届けるが MVP コマンドは未使用 |
| 未知コマンドのフォールバック応答 / handler 例外の catch（固定文言） | reaction・thread create など `/` 以外のトリガー |
| ALLOWED_USER_IDS 外の無視（既存 `_should_react` を踏襲） | ヘルプの多言語化 |
| 単体テスト（`tests/test_commands.py`, 標準 unittest, discord 非依存） | `on_message` ルーティング退化の**自動**統合テスト（→ 手動 test-spec で担保。理由は「## 設計方針 › テスト戦略」） |

## Non-Goals

- 拡張コマンド（`/intake` `/compact` `/jobs` `/gloop-status`）は本 Issue では実装しない。
- Discord のネイティブ slash command API（`/` 補完 UI）は使わない。`message.content` のプレフィックス判定方式。
- コマンドの引数解釈は最小限（`parse` が返す args を handler へ渡すのみ、MVP コマンドは未使用）。
- **[R1 migration M4 / R2 全 persona H] コマンド namespace は「`/` + 直後が英字」に限定する**。変更前は `/foo` も `_handle` 経由で claude に渡っていた。変更後、`is_command` にマッチする入力（`/clear` 等）だけを commands namespace として横取りし、未知なら `❓` を返す。**`/tmp/foo` `//comment` `/ 相談` `/?` `/` 単体などマッチしない `/` 始まり入力は従来通り `_handle`（claude）へフォールバック**し、後方互換を保つ（下記 `is_command` 定義とテスト T13 で固定）。エスケープ機構は提供しない。

## 設計方針

### アーキテクチャの核: commands 層 = Discord gateway 専用のローカルコマンド層（discord.py 非依存）

- `gateway/discord/commands/` 配下のコマンドハンドラは **discord.py に一切依存しない同期関数**。入力は `CommandContext` + `args: str`、出力は応答文字列。
- **[R1 architect H2 / R2 architect M2] 責務を狭く定義する**: commands 層は「Discord gateway 専用のローカルコマンド層」であり、汎用 application-service ではない。「純粋関数」でもない（副作用あり）。副作用は `CommandContext` 経由で**注入されたパス**（`sessions_db` / `hermes_home`）に対してのみ発生し、discord オブジェクトや live ハンドルには触れない。将来 application-service へ切り出す候補は `/status` の読み取りロジックのみに限定する。この非依存性により discord 未インストールの system python3 でもテスト可能。
- discord への `send` は `bot.py` の責務。

### 型と定数（`commands/types.py` = 循環しない leaf module）

**[R3 architect M(型配置)] 型・定数を leaf module に分離する**。`commands/types.py` は stdlib（`dataclasses` / `pathlib` / `typing`）のみに依存し、`__init__` や各 handler を一切 import しない。これにより「handler が `CommandContext` を型注釈で使う」一方「handler は `__init__` を import しない」という制約が両立する（handler は `from commands.types import CommandContext` = leaf を参照。partially-initialized の `__init__` を触らないので循環しない）。`__init__.py` はこれらを re-export し、`commands.CommandContext` / `commands.COMMAND_ERROR_MESSAGE` の公開 API は維持する。

```python
# commands/types.py （leaf: stdlib のみ import）
UNKNOWN_COMMAND_MESSAGE = "❓ 未知のコマンド。/help で一覧を確認できます"
COMMAND_ERROR_MESSAGE   = "⚠️ コマンド実行に失敗しました（詳細は journalctl 参照）"

@dataclass(frozen=True)
class CommandContext:
    scope_key: str | None      # bot._scope_key(message) の結果（None = セッション継続対象外スコープ）
    author_id: int             # 呼び出しユーザー（将来のコマンド別権限用に受けるだけ）
    sessions_db: Path          # [R1 H1] live store ではなく sqlite ファイルパスを注入
    hermes_home: Path          # /status がファイルを読む基点

@dataclass(frozen=True)
class Command:
    name: str                                       # "clear"（先頭 / なし）
    summary: str                                    # /help 用の一行説明
    handler: Callable[[CommandContext, str], str]   # handler は (ctx, args) を受ける
```

`commands/__init__.py` 冒頭: `from .types import (CommandContext, Command, UNKNOWN_COMMAND_MESSAGE, COMMAND_ERROR_MESSAGE)` で re-export し、`COMMANDS: dict[str, Command]` を組む。

**[R3 architect H2(registry import 堅牢性)] 各 handler モジュールは import 時に副作用・ファイル IO・壊れやすい依存を持たない**（stdlib import + 関数/dataclass 定義のみ。`os`/`json`/`glob`/`pathlib` は正常な python で import 失敗しない）。`/status` の重い処理（glob・pid 確認・json parse）はすべて `status_handler` 実行時＝関数内に閉じ込める。これにより `import commands`（bot 起動時）が status の実行時エラーで巻き添え失敗せず、bot が起動しなくなる事態を防ぐ。dispatch の例外 catch は import 完了後にしか効かないため、この「import 時は安全」制約を設計条件として固定する。

### [R2 architect H1 / contrarian H1 / migration H1] `is_command` / `parse` / `dispatch` の契約（矛盾解消）

round 1 で「Non-Goals は英字限定 / `is_command` は `startswith('/')`」という文書内矛盾を作ってしまった。単一仕様に固定する：

```python
_COMMAND_RE = re.compile(r"^/([A-Za-z][A-Za-z0-9_-]*)(?:\s+(.*))?$", re.DOTALL)

def is_command(stripped: str) -> bool:
    return _COMMAND_RE.match(stripped) is not None

def parse(content: str) -> tuple[str, str] | None:
    m = _COMMAND_RE.match(content)
    if not m:
        return None
    # [R3 migration M] args は strip して返す（"/help   " -> ("help","")、"/status verbose" -> ("status","verbose")）
    return m.group(1), (m.group(2) or "").strip()

def dispatch(content: str, ctx: CommandContext, registry: dict[str, Command] | None = None) -> str:
    registry = registry if registry is not None else COMMANDS   # [R2 migration M] 注入可能 → global 非汚染
    parsed = parse(content)
    if parsed is None:
        # [R4 contrarian M] 契約: bot は is_command 済みの入力のみ dispatch する。
        # ここに来るのは契約違反（内部バグ）なので UNKNOWN ではなく内部エラー扱い。
        log.error("dispatch called with non-command content: %r", content[:80])
        return COMMAND_ERROR_MESSAGE
    name, args = parsed
    cmd = registry.get(name)
    if cmd is None:
        return UNKNOWN_COMMAND_MESSAGE                            # [R4] UNKNOWN は「解析成功だが未登録」に限定
    try:
        return cmd.handler(ctx, args)
    except Exception:
        log.exception("command handler failed: %s", name)        # 詳細は journalctl のみ
        return COMMAND_ERROR_MESSAGE                              # [R2] Discord には固定文言
```

- `is_command` にマッチしない `/tmp/foo` `//x` `/ 相談` `/?` `/` は bot 側で `_handle` に流れる（後方互換）。`dispatch` の parse-None 経路は防御（契約違反検出）であって通常経路ではない。
- **[R2 migration M] `registry` 注入**により、例外 handler を差し込むテスト（T06）は global `COMMANDS` を汚染しない。
- **[R2 全 persona] 例外露出なし**: handler 例外は `COMMAND_ERROR_MESSAGE` 固定、詳細は `log.exception`。

### [R2 architect H2 / contrarian H2] /help の循環 import 回避（依存方向を一方向に固定）

- 依存方向は **`__init__.py` → 各 handler モジュール** の一方向のみ。handler モジュールは `__init__`（＝ `COMMANDS`）を **import しない**。
- `commands/help.py` は `render_help(registry: dict[str, Command]) -> str`（registry を引数で受ける純粋関数、package を import しない）だけを持つ。
- `commands/__init__.py` は各 handler を import して `COMMANDS` を組み、help は小アダプタで登録する:

  ```python
  from . import clear, status, help as help_mod   # __init__ → handlers（一方向）
  COMMANDS = {}
  COMMANDS["clear"]  = Command("clear",  "セッションをクリア", clear.clear_handler)
  COMMANDS["status"] = Command("status", "gloop の状態を表示", status.status_handler)
  COMMANDS["help"]   = Command("help",   "コマンド一覧を表示", lambda ctx, args: help_mod.render_help(COMMANDS))
  ```

  help アダプタは `COMMANDS` を**呼び出し時**に参照する（module load 時ではない）ので、load 時の循環も部分初期化 registry も起きない。

### [R1 architect H1 / contrarian H1 / migration H1] sqlite スレッド安全性（最重要指摘の解消・維持）

- **事実1**: `SessionStore.__init__` は `sqlite3.connect(..., isolation_level=None, check_same_thread=False)` + WAL（`gateway/discord/session_store.py:18-19`）。スレッド跨ぎ利用を明示許可、autocommit。
- **事実2**: `store.delete(scope_key)` 実在・冪等（`session_store.py:61`、既存 `bot.py:174` でも使用）。
- **事実3**: 既存 approval も `asyncio.to_thread(_approval_handler.handle, ...)`（`bot.py:337`）で worker thread から DB を触る前例あり。
- **設計**: `CommandContext` に live store ではなく `sessions_db: Path` を入れる。`dispatch` は `asyncio.to_thread` で worker thread 実行し、`/clear` handler は **worker thread 内で `SessionStore(ctx.sessions_db)` を新規に開いて** `delete(scope_key)` する。main thread の接続を共有しないので `ProgrammingError` も並行競合も起きない。WAL なので DELETE は main 接続の次回 read へ即反映。
- **[R2 contrarian M / R4 contrarian M] 接続ライフサイクル = context manager**: `SessionStore` を context manager 化する（`__enter__` は `self` を返し、`__exit__` で `self._db.close()`）。`/clear` は `with SessionStore(ctx.sessions_db) as store:` で短命接続を明示し、bare `try/finally` より簡潔にする。`close()` メソッドも公開するが、`sqlite3.Connection.close()` は二重呼び出し安全なので **`close()` は冪等**（`__exit__` と明示 close の併用でも問題なし）。**[R4 migration M] close は terminal**（close 後の `get/set/delete` は使用しない）。実装は `session_store.py`（implementer 担当）。

### /clear の詳細

```python
def clear_handler(ctx: CommandContext, args: str) -> str:
    if ctx.scope_key is None:
        return "ℹ️ このスコープはセッション継続対象外です"
    from session_store import SessionStore          # [R5 architect H] 遅延 import（clear.py の module top を stdlib のみに）
    with SessionStore(ctx.sessions_db) as store:     # worker thread 内の短命接続（__exit__ で close）
        store.delete(ctx.scope_key)                  # 冪等
    return "✅ セッションをクリアしました（次の発話から新規セッション）"
```

- **[R4 architect H1 / R5 architect H] import 時 IO なしを徹底**: `clear.py` の module top は stdlib のみ。`SessionStore` は `clear_handler` 内で**遅延 import** する。これにより `commands/__init__` が `clear` を import する時点で `session_store` に一切依存せず、将来 `session_store.py` に設定読込や DB 初期化が入っても `import commands`（bot 起動）を単一障害点にしない。T16 は registry import（`clear` 含む）が gloop ファイル/DB 不在でも成功することを固定する。

- 旧セッション JSONL には触れない（`delete` は sqlite 行削除のみ）→ Issue の「旧 JSONL を残す」を満たす。

### /status の詳細（読み取り contract と スキーマガード）

**[R2 architect M3] 読み取り contract（このスキーマに依存する。loop 側の内部形式変更で壊れ得る密結合を明示し、各フィールド欠損時の表示を固定）:**

| ファイル | 参照フィールド | 欠損/破損時の表示 |
|---|---|---|
| `features/.loop/state.json` | `cycle`, `recent_cycles[-1].pause_reason` | cycle=`N/A` / 直近 pause=`不明` |
| `features/.loop/tmux-state.json` | `watcher_pid`, `worker_pane_id` | watcher=`unknown` |
| `logs/*/*.json`（mtime 降順・スキーマガード後の最新） | 親ディレクトリ名, mtime, `result` | 直近ジョブ=`N/A` |

- 各セクションは**個別に try で握り**、1 つ壊れても他は表示する（[[project-gloop-state-check]] の方針）。1 セクションの例外が `/status` 全体を落とさない。
- `watcher_pid` 生存は `os.kill(pid, 0)` を try で判定（`ProcessLookupError`→dead, `PermissionError`→alive とみなす）。
- **[R1 architect M5 / contrarian M5] logs スキーマガード**: `logs/*/*.json` を glob（**事実: `logs/discord/2026-07-05.jsonl` が実在**し naive な `json.load` を壊すため `.json` 限定必須。`.stderr`/`.csv` も拡張子で除外）。mtime 降順に見て `json.load` 成功 **かつ** `result` キーを持つ最初のファイルを採用、破損/欠損は skip。
- **[R3 architect M / R4 architect M / R5 architect M] status.py は adapter として型付き DTO を返す**: 読み取りロジックは `_read_loop_state` / `_read_tmux_state` / `_latest_job_log` に分割し、それぞれ **`dataclass(frozen=True)`** の DTO（`commands/status.py` 内 leaf 定義。stdlib のみ）を返す:
  - `LoopStateStatus(cycle: int | None, pause_reason: str | None)`
  - `TmuxStatus(watcher_alive: bool | None, watcher_pid: int | None, worker_pane_id: str | None)`（`watcher_pid` は応答フォーマットの `pid` 表示 + contract 表の参照フィールドと整合。実装時に DTO と表示例の食い違いを解消して追加）
  - `LatestJobStatus(name: str, at: str, result_summary: str) | None`

  `status_handler` は DTO の**属性**だけを見て整形する（生の dict key や gloop ファイルスキーマを知らない）。これにより属性 typo・キー欠損を型で検出でき、将来 `status_service` へ切り出す関数境界が実装単位で固定される。gloop ファイルスキーマへの依存は `_read_*` の 3 関数に閉じる。
- **[R2 contrarian H3 → 棄却]** `/status` を別 PR に分離する案は棄却（Issue タイトルが `/status` を MVP に明示）。ただしリスク緩和として status.py は上記の通り完全に隔離し、per-field フォールバックで status の不具合が dispatch/clear を落とさないことを保証する。詳細は rejection.md。

応答フォーマット（箇条書き）:

```
📊 gloop status
• cycle: 12
• 直近 pause: <reason or なし>
• watcher: alive (pid 3180395) / dead
• 直近ジョブ: <name> (<時刻>) — <result 要約>
```

### /help の詳細

- `render_help(COMMANDS)` が レジストリの `name` + `summary` から**自動生成**（DRY）。コードブロックで返す。

### [R1 contrarian H2] 入力仕様の明文化

`on_message` 分岐順序は `_should_react` → approval → **slash** → `_handle`。slash は `_should_react` が True のスコープでのみ処理（bot が既に反応するスコープでだけコマンドも受ける＝全チャンネルを横取りしない）。

- **事実**: `_should_react`（`bot.py:87-98`）が True になるのは ALLOWED_USER のユーザーが ①DM ②Thread ③`INPUT_CHANNEL_IDS` チャンネル ④他 guild channel では `@bot` mention 付き、のいずれか。`_strip_mention`（`bot.py:101-104`）が `<@...>` を除去するので `@bot /help` → `/help`。
- **サポート入力形式**: DM/Thread/`INPUT_CHANNEL_IDS` は plain `/help`。他 guild channel は `@bot /help`（mention 無しは無視）。ALLOWED_USER_IDS 外は全スコープで無視（`bot.py:90`）。

### [R1 architect M4 / migration M5 / R2 migration H2] import・config export の整合（本番 ImportError を防ぐ）

- **事実**: `config.py` は `SESSIONS_DB`（`config.py:21`）と `HERMES_HOME`（`config.py:27`）を export 済み。**`bot.py:14-23` は既に両者を import 済み**（`from config import (... SESSIONS_DB, HERMES_HOME ...)`）。よって新規の config 変更や追加 export は不要。slash 分岐は既存 import 済みシンボルだけを使う。
- **事実**: `bot.py` は `import claude_runner` / `import compaction` / `from session_store import SessionStore` と **bare top-level import**（`bot.py:12-24`）。systemd は `WorkingDirectory=%h/hermes-lite/gateway/discord`（`gateway/discord/systemd/discord-gateway.service:8`）。`requirements.txt` は `discord.py==2.4.0` のみ（外部 `commands` 無し）。→ `import commands` は既存規約と一致し本番でも解決。
- **[R4/R5 architect M(名前曖昧さ)] alias とテスト制約で緩和**: ディレクトリ名は Issue 決定で `commands/` を維持しつつ、`bot.py` は `import commands as slash_commands`。テストも `sys.path.insert(0, gateway/discord)`（先頭に固定、外部 `commands` を前提にしない）してから `import commands as slash_commands` と alias を統一。`bot.py`・テスト以外で `import commands` を広げない。`dispatch` / `classify` は **gateway 内部 API**（安定公開 API ではない。呼び出しは bot.py の on_message のみ）。

### [R3 contrarian H1 / migration H2・M] ルーティング順序を discord 非依存の純関数に切り出して自動テストする

round 2〜3 で「on_message の分岐順序（approval 優先・slash・通常文フォールバック）が自動テストされていない」が繰り返し blocking になった。**内容ベースの分岐判定を discord 非依存の純関数へ切り出す**ことで、fake message なしで自動化する:

```python
# commands/__init__.py
from typing import Literal
Route = Literal["approval", "slash", "handle"]

def classify(stripped: str, approval_match: bool) -> Route:
    """_strip_mention 済みの content を route に分類（優先順位: approval > slash > handle）。
    discord 非依存の低レベル route chooser。approval の有効条件は呼び出し側で approval_match に畳む。"""
    if approval_match:               # [R4 contrarian L] 引数を1つに（enabled は approval_match に織込済）
        return "approval"
    if is_command(stripped):
        return "slash"
    return "handle"
```

- **[R4 architect H2] `classify` は「route 選択」だけを担う低レベル関数**であり、approval の有効判定（`APPROVAL_COMMANDS_ENABLED` / pattern 存在）は bot.py が `approval_match: bool` に畳んで渡す（「唯一の真実」という過剰主張は取り下げる。分岐の *優先順位* は classify、approval の *成立条件* は bot.py という責務分担を明記）。
- **[R4 architect L / contrarian L] 戻り型は `Literal["approval","slash","handle"]`**（typo・route 追加漏れを型で検出）。引数は `approval_match` の 1 つに統一（`enabled=False, match=True` の不整合ケースを構造的に排除）。
- これで「approval が slash より優先 / 通常文は handle / `/tmp/foo` は handle / `/clear` は slash」を **自動テスト（T14）** で固定できる。
- **discord 依存部（`_should_react` の認可・チャンネルゲート, `_scope_key`）は引き続き手動 test-spec**: これらは `discord.DMChannel` 等の isinstance と `client.user` に依存し import に discord.py が必要。プロジェクトのテスト規約（`test_approvals.py` / `test_switchbot.py`）は system python3 + discord 非依存で統一され、async discord 統合ハーネスは無い。よって「許可外ユーザー無視 / DM plain `/help` / guild `@bot /help`」は手動 `test-spec.md` に置く（自動化の費用対効果が見合わない範囲を明示）。

### テスト戦略まとめ

- **自動（`tests/test_commands.py`, system python3 unittest, discord 非依存）**: `parse` / `is_command` / `classify`（順序）/ `dispatch`（正常・未知・非コマンド防御・例外注入）/ `/clear`（scope あり・None）/ `/status`（正常・欠損・破損 json skip・jsonl 無視）/ `/help`（レジストリ全網羅）。
- **手動（`test-spec.md`, discord 実機）**: `_should_react` 認可ゲート・スコープ別入力形式・systemd 再起動後の疎通。

## 実装対象

### bot.py（`on_message` の該当ブロック全体を省略なしで before/after）

**[R3 architect M(before/after 省略)]** `_should_react` 直後から `_handle` 呼び出しまでを省略せず提示する。

before（現状 = `bot.py:317-349` そのまま）:
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

    # 承認ゲート (flag on のときだけ regex マッチを試す)
    if APPROVAL_COMMANDS_ENABLED and _APPROVAL_PATTERN is not None:
        stripped = _strip_mention(message.content)
        if _APPROVAL_PATTERN.match(stripped):
            if _approval_handler is None:
                await message.channel.send(
                    "⚠️ [WARN] approval feature disabled (import failed; see journalctl)"
                )
                return
            try:
                reply = await asyncio.to_thread(
                    _approval_handler.handle, stripped, message.author.id
                )
            except Exception:
                log.exception("approval handler crashed")
                await message.channel.send(
                    "⚠️ [WARN] approval 処理で内部エラー (journalctl 参照)"
                )
                return
            await message.channel.send(reply)
            return

    await _handle(message)
```

after（`stripped` を承認ゲートの手前で 1 回だけ算出して共有し、`classify` で分岐順序を固定）:
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

    # mention を 1 度だけ剥がし、approval / slash 双方で同じ入力を使う
    stripped = _strip_mention(message.content)
    # approval の成立条件（enabled + pattern 存在 + match）は bot 側で bool に畳む
    approval_match = bool(
        APPROVAL_COMMANDS_ENABLED and _APPROVAL_PATTERN is not None
        and _APPROVAL_PATTERN.match(stripped)
    )
    route = slash_commands.classify(stripped, approval_match)   # [R4] 引数は approval_match の1つ

    if route == "approval":
        if _approval_handler is None:
            await message.channel.send(
                "⚠️ [WARN] approval feature disabled (import failed; see journalctl)"
            )
            return
        try:
            reply = await asyncio.to_thread(
                _approval_handler.handle, stripped, message.author.id
            )
        except Exception:
            log.exception("approval handler crashed")
            await message.channel.send("⚠️ [WARN] approval 処理で内部エラー (journalctl 参照)")
            return
        await message.channel.send(reply)
        return

    if route == "slash":
        ctx = slash_commands.CommandContext(
            scope_key=_scope_key(message),
            author_id=message.author.id,
            sessions_db=SESSIONS_DB,   # [R1 H1] 既存 import 済み。live store ではなくパス
            hermes_home=HERMES_HOME,   # 既存 import 済み
        )
        try:
            reply = await asyncio.to_thread(slash_commands.dispatch, stripped, ctx)
        except Exception:
            log.exception("slash command crashed")
            reply = slash_commands.COMMAND_ERROR_MESSAGE   # dispatch と同一定数（文言統一）
        try:
            await message.channel.send(reply)
        except discord.HTTPException:
            # [R4 migration H(send失敗)] /clear は DB 削除後に send だけ失敗し得る（状態は変更済み）。
            # 既存 compaction notice（bot.py:264-272）と同じく warning を残し journalctl で追える形にする。
            log.warning("could not send slash reply (route=slash)", exc_info=True)
        return

    await _handle(message)   # route == "handle"
```

- **[R3 architect M / contrarian M(名前)] alias import で読み手の曖昧さを下げる**: Issue 決定事項でパッケージ配置は `gateway/discord/commands/` に確定しているためディレクトリ名は変えず、bot.py 側で `import commands as slash_commands` と alias する（`discord.ext.commands` との読み違い回避）。`SESSIONS_DB` / `HERMES_HOME` は追加 import 不要（既存 `bot.py:14-23`）。
- `stripped` は承認ゲートの手前で 1 回算出し、approval と slash で同じ入力を使う（before では approval 内でのみ算出していた差分を明示）。
- 二重防御の外側 catch も `slash_commands.COMMAND_ERROR_MESSAGE` を返し、dispatch 内 catch と文言一致。

### 新規ファイル（gateway/discord/commands/）

- `commands/types.py` — leaf module。`CommandContext` / `Command` / 定数（stdlib のみ import、循環なし）
- `commands/__init__.py` — `types` を re-export / `COMMANDS` / `is_command` / `parse` / `classify` / `dispatch(…, registry=None)` / help アダプタ
- `commands/clear.py` — `clear_handler(ctx, args)`（worker thread 内で `with SessionStore(...) as store:` で開き delete）。`SessionStore` は **handler 内で遅延 import**（module top は stdlib のみ）
- `commands/status.py` — `status_handler(ctx, args)` + `_read_loop_state` / `_read_tmux_state` / `_latest_job_log`。**glob/pid/json は関数内のみ（import 時 IO なし）**
- `commands/help.py` — `render_help(registry)`（package 非 import の純粋関数）

### 既存ファイル変更（implementer 担当。orchestrator は編集しない）

- `session_store.py` — context manager 化（`__enter__` → self / `__exit__` → `self._db.close()`）+ 冪等な `close()` 公開
- `bot.py` — 上記 after の分岐 + `import commands as slash_commands`

**[R3 migration H(close 互換)] `SessionStore.close()` 追加の既存互換性**: `close()` は**追加メソッド**であり既存の呼び出し元シグネチャを一切変えない。既存利用箇所は次の通りで、いずれも close を呼ばず従来通り動く:

- `bot.py:38` の module-global `store = SessionStore(SESSIONS_DB)` — プロセス寿命の長寿命接続。close しない（従来通り）。
- `bot.py:154,174,212,215` の `store.get/delete/set` — event loop 上、長寿命接続を使用（従来通り）。

`/clear` が開く**別接続**（worker thread 内、`ctx.sessions_db` から新規）のみ `close()` する。close は terminal（close 後の `get/set/delete` は使用しない）。WAL なので `/clear` の別接続 DELETE は長寿命 `store` の次回 `get` に即反映される（T02 で別インスタンス読み戻し検証）。

## テスト計画（ID 付き）

| ID | 内容 | 期待値 |
|---|---|---|
| T01_dispatch_help | `dispatch("/help", ctx)` | 応答に `/clear` `/status` `/help` を全て含む |
| T02_clear_deletes_session | 実 `SessionStore.set()` で scope_key を書き、別インスタンスで存在確認後 `dispatch("/clear", ctx)`、さらに別インスタンス `get()`。**加えて長寿命インスタンス退化**: 長寿命 `store_a` で `set` → `/clear`（別接続 delete）→ 同じ `store_a.get()` が `None`（WAL 反映）を確認 | 当該 scope_key が `None`（別・長寿命の両インスタンスで）+ `✅` を含む |
| T03_clear_no_scope（境界） | `scope_key=None` で `dispatch("/clear", ctx)` | DB 未変更 + `ℹ️`（対象外）、例外なし |
| T04_unknown_command | `dispatch("/foobar", ctx)` | `❓` + `/help` 案内（`UNKNOWN_COMMAND_MESSAGE`） |
| T05_help_lists_all_registry | `render_help(COMMANDS)` | `COMMANDS` の全 name を含む（レジストリ DRY 検証） |
| T06_handler_exception_fixed（退化） | 例外 handler を **custom registry** に入れ `dispatch("/boom", ctx, registry=…)` | `COMMAND_ERROR_MESSAGE` を返し例外は伝播せず、**global `COMMANDS` は不変** |
| T07_status_renders_cycle | tmpdir に `features/.loop/state.json`(cycle=12) 等を用意し `/status` | 応答に `12` と `cycle` を含む |
| T08_status_missing_files（境界） | ファイル無しで `/status` | 例外にならず `N/A` 等でフォールバック |
| T09_is_command_true_false（境界） | `is_command("/help")` / `is_command("hello")` / `parse("hello")` | `True` / `False` / `None` |
| T10_parse_slash_with_args | `parse("/status verbose")` + dispatch 経由 | `("status","verbose")`、handler が `args="verbose"` を受ける |
| T11_status_skips_broken_json（境界） | `logs/x/broken.json`(不正) と `logs/y/good.json`(`result` あり) | broken skip・good 採用、例外なし |
| T12_status_ignores_jsonl（境界） | `logs/discord/2026-07-05.jsonl` のみ | `.jsonl` 非候補で 直近ジョブ=`N/A`、例外なし |
| T13_slash_namespace_boundary（境界, R2） | `is_command` で `/tmp/foo` `//x` `/ 相談` `/?` `/` → False、`/clear` `/a-b_c` → True | namespace 境界を固定（`_handle` フォールバック対象の確定） |
| T14_classify_routing_order（退化, R3/R5） | **2 引数**で `classify(approval文, True)`→`"approval"` / `classify("/clear", False)`→`"slash"` / `classify("hello", False)`→`"handle"` / `classify("/tmp/foo", False)`→`"handle"` | approval>slash>handle の順序を固定。approval の enabled/pattern 判定は bot.py 側（classify のテスト対象外）と明記 |
| T15_parse_trailing_ws（境界, R3） | `parse("/help   ")` / `parse("/status  verbose ")` | `("help","")` / `("status","verbose")`（args は strip） |
| T16_import_safe_no_files（退化, R4） | 任意 cwd / gloop ファイル不在の tmpdir で `import commands` → `dispatch("/help", ctx)` | import 例外なし・`/help` 応答が返る（registry の import が単一障害点でないことを固定） |

正常系: T01,T02,T04,T05,T07,T10 / 退化・境界: T03,T06,T08,T09,T11,T12,T13,T14,T15,T16。

## 完了条件（人間）※ STEP 8 で hold_for_review=true

- [ ] DM で plain `/help` を投げてコマンド一覧が返る
- [ ] 通常の guild channel で `@bot /help` でコマンド一覧が返る（mention 無し `/help` は無視も確認）
- [ ] `/clear` → 直後に自然文発話 → 過去会話を忘れている
- [ ] `/status` → 現サイクル情報（cycle / pause / watcher / 直近ジョブ）が正しく返る
- [ ] `/unknown-command` で `❓` の丁寧なエラー応答が返る
- [ ] 通常文（`/` 始まりでない）が従来通り claude 応答（退化なし）
- [ ] `/tmp/foo` のような `/`+非英字 入力が従来通り claude に渡る（横取りされない）
- [ ] `approval approve #xxxx` が従来通り approval 処理される（slash より優先, flag on 時）
- [ ] `systemctl --user restart discord-gateway.service` で bot 再起動後、上記を通し実施
