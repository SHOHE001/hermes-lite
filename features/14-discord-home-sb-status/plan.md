# plan: #14 Discord `/home` で家電状態一覧を返す (sb-status 実行)

slug: discord-home-sb-status
milestone: Phase 3
labels: type:feature, batch:feature

## In-Scope / Out-of-Scope

| In-Scope | Out-of-Scope |
|---|---|
| `gateway/discord/commands/home.py` 新設（sb-status subprocess 実行） | `bin/sb-status` 本体の変更 |
| `commands/__init__.py` の `COMMANDS` レジストリへの `home` 登録 | エアコン状態の取得（SwitchBot 側が状態を持たない） |
| `/home` / `/home --json` の 2 形態 | 単一デバイス指定（`/home <deviceId>`） |
| タイムアウト（20s）・失敗時のエラー整形 | `commands/__init__.py` の `dispatch()` 契約変更（clamp 等は入れない） |
| `gateway/discord/transport.py` 新設（`split_for_discord` 移設 + `send_chunks`、discord 非依存） | claude -p 経由の自然文経路の変更・廃止 |
| bot.py の slash 応答送信を `transport.send_chunks` に乗せ換え + `_split_for_discord` の import 化 | `/home` 連打の rate limit・in-flight 合流（設計方針に不採用根拠を明記） |
| 単体テスト `tests/test_commands_home.py` + `tests/test_transport.py` | 部分失敗時の stdout 併記（Issue 決定事項の失敗フォーマットに従う。改善は follow-up 候補） |

## Non-Goals

- 定期実行・キャッシュ（毎回 SwitchBot API を叩く。応答数百 ms で十分）
- 権限の追加ゲート（既存 `ALLOWED_USER_IDS` チェックのみ。副作用なし操作のため）
- Discord embed 等のリッチ表示（コードブロックのみ）
- 分割送信時のコードブロック整形（チャンク境界で ``` が閉じずに表示が乱れることは許容。内容の欠落はない）
- `/home --json` の機械可読契約（**表示専用**。分割送信により内容は欠落しないが、複数メッセージへの跨りやコードブロック崩れがあり得るため、parse 対象としての保証はしない。機械可読が必要なら SSH で `bin/sb-status --json` を直接叩く）

## 設計方針

### project_type 判定に関する注記

`.claude/gloop-config.json` は `project_type: "jobs"` だが、本 repo には unittest ベースの自動テストスイート（`tests/`、56 件 green、実行コマンド `python3 -m unittest discover -s tests`）が Issue #12/#13 で既に存在する。Issue #14 の完了条件（自動化）にも「単体テスト（tests/test_commands_home.py、sb-status はモック）」が明記されているため、**jobs 分岐（手動チェックリストのみ）ではなく python 相当の扱い**（skip 付きスケルトン → 実装 → skip 外し）とする。「完了条件（人間）」チェックリストが残るため、STEP 8 は `hold_for_review=true` の PR 保留分岐に入る想定。

### handler の同期実行で問題ない根拠

`commands` の handler 型は同期 `Callable[[CommandContext, str], str]`（`commands/types.py`）。`bot.py:362` で `dispatch` は `await asyncio.to_thread(...)` 経由で呼ばれるため、handler 内で subprocess を最大 20 秒ブロックしてもイベントループは塞がらない。home.py で独自の非同期化はしない。

### home.py の構造（既存 handler の流儀に合わせる）

- module top は stdlib のみ import。import 時 IO なし（status.py と同じ徹底）
- `TIMEOUT_SEC = 20`（SwitchBot API 3 リクエスト分の余裕、Issue 決定事項）
- sb-status のパスは `ctx.hermes_home / "bin" / "sb-status"`（モジュール定数 `SB_STATUS_REL = ("bin", "sb-status")` から組み立て）
- `subprocess.run([str(path), *extra], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_SEC, cwd=ctx.hermes_home)` で実行。shebang 実行（実行ビットあり・稼働中の実物に合わせる）。`errors="replace"` により子プロセス出力に不正 UTF-8 が混入しても `UnicodeDecodeError` で未捕捉例外にならない

### handler が repo layout（hermes_home 基点）を知る設計判断

`CommandContext.hermes_home` は types.py の docstring どおり「handler がファイルを読む基点」として導入済みの契約であり、`status.py` も `hermes_home / "features" / ".loop" / ...` と repo 相対パスを直接組み立てる前例がある。本 Issue もこの既存契約に乗り、`CommandContext` へのフィールド追加（`sb_status_path` 等）はしない — bot.py 側の構築コード変更が波及し、コマンド 1 個の追加としては過剰なため。sb-status の所在が変わる場合は `home.py` のモジュール定数 1 箇所の変更で追従する。

### import 名前空間と patch 対象の整合（検証済み）

本番 `bot.py` は `import commands as slash_commands`（`bot.py:13`）で、systemd unit の `WorkingDirectory=%h/hermes-lite/gateway/discord` により **トップレベル `commands` パッケージ**として import される。既存テスト（`tests/test_commands.py`）も `sys.path.insert(0, gateway/discord)` の上で `import commands` しており、実行時とテスト時のモジュール名は同一。`gateway.discord.commands` という package import 経路は存在しない（`gateway/` に `__init__.py` なし）ため二重ロードは起きない。よってテストの patch 対象は `patch("commands.home.subprocess.run")` で本番と同一のモジュールオブジェクトに当たる。

### 引数解釈

| args | 動作 |
|---|---|
| `""` | `sb-status` を引数なし実行 |
| `"--json"` | `sb-status --json` を実行 |
| それ以外 | subprocess を実行せず使い方メッセージ `使い方: /home または /home --json` を返す（未知引数をそのまま subprocess に渡さない — 引数注入面の閉塞） |

dispatch の `parse()` が args を strip 済みで渡す契約（`commands/__init__.py:46`）だが、handler 冒頭でも `args = args.strip()` で防御し、dispatch 契約変更に対して壊れないようにする。判定は strip 後の完全一致（`"" ` / `"--json"`）。

### 応答フォーマット（Issue 決定事項どおり）

| 条件 | 応答 |
|---|---|
| exit 0 | ` ```plain\n<stdout>\n``` ` |
| exit != 0 | `⚠️ 家電状態の取得に失敗: <stderr の1行目>`（stdout の有無に関わらずこれのみ。Issue 決定事項の失敗フォーマットに従う） |
| `TimeoutExpired` | `⚠️ 家電状態の取得がタイムアウトしました (20s)` |
| `OSError`（実行ファイル不在等） | `⚠️ 家電状態の取得に失敗: <例外文字列>` |

- 依存する契約は `sb-status` の **CLI 公開契約**（exit code / stdout / stderr）のみ。内部関数構造には依存しない
- ⚠️ 行に埋め込む stderr 1 行目・例外文字列は 200 字で切る（⚠️ 行自体の肥大防御）
- 部分失敗時（sb-status は 1 機器失敗でも成功分を stdout に出して exit 1 する）に stdout を併記する案は design review loop 1 で採用したが、loop 2 の指摘（Issue 決定事項の失敗フォーマットを上書きする拡張であり合意がない）を受けて撤回。改善したければ Issue 側の受け入れ条件を変える follow-up として扱う（Out-of-Scope 表に記載）

### Discord 2000 字上限の保証（責務: transport 層。テスト可能な境界に切り出す）

Discord のメッセージ上限は transport 制約なので、commands 層（dispatch / handler）には一切持ち込まない。**bot.py には既に `_split_for_discord(text, limit=MAX_DISCORD_MESSAGE)`（bot.py:108、`MAX_DISCORD_MESSAGE = 1900`、改行位置優先の分割）が存在し、claude 応答経路（bot.py:275-276）で実績がある**が、slash 経路（bot.py:367）だけが生の `channel.send(reply)` で送っており、長文応答時に `discord.HTTPException` になる既存の穴がある。

bot.py が discord.py 依存で自動テスト対象外である問題（design review loop 4 で 3 persona 一致指摘）に対応するため、送信分割を **discord 非依存の新モジュール `gateway/discord/transport.py`**（stdlib のみ、import 時 IO なし）に切り出す:

```python
# transport.py（新設・全文）
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
    ...  # bot.py:108-123 の _split_for_discord 本体を無修正で移動


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
```

bot.py 側の変更（3 箇所）:

1. import 追加: `import transport`（既存の `import claude_runner` 等と同じモジュール import 流儀、bot.py:12 付近）
2. `_split_for_discord` の関数定義（bot.py:108-123）を削除し、claude 応答経路の呼び出し（bot.py:275）を `transport.split_for_discord(result.text, MAX_DISCORD_MESSAGE)` に置換（`MAX_DISCORD_MESSAGE` は既存 import 済み・値も従来と同一のため挙動不変）
3. slash 送信（bot.py:366-371）の before/after:

```python
# before
        try:
            await message.channel.send(reply)
        except discord.HTTPException:
            # /clear は DB 削除後に send だけ失敗し得る（状態は変更済み）。
            # 既存 compaction notice（bot.py:264-272）と同じく warning を残し journalctl で追える形にする。
            log.warning("could not send slash reply (route=slash)", exc_info=True)

# after
        try:
            await transport.send_chunks(message.channel.send, reply, MAX_DISCORD_MESSAGE)
        except discord.HTTPException:
            # /clear は DB 削除後に send だけ失敗し得る（状態は変更済み）。
            # 既存 compaction notice（bot.py:264-272）と同じく warning を残し journalctl で追える形にする。
            log.warning("could not send slash reply (route=slash)", exc_info=True)
```

設計上の性質:

- 切り詰め（clamp）ではなく**分割**。内容保持の契約は「**チャンク境界に選ばれた改行のみ除去され（メッセージ区切りが改行の代替になる）、それ以外の文字は完全に保持される**」（旧 `_split_for_discord` の `lstrip("\n")` 挙動を互換優先でそのまま移設。claude 応答経路の既存挙動を変えない）。JSON 内の文字が切り捨てられることはないが、チャンク境界に当たった改行は失われ得る — `/home --json` が表示専用契約（Non-Goals）である理由の一つ
- `dispatch()` の戻り値契約（handler の文字列をそのまま返す）は不変
- **全 slash コマンド共通の transport 変更として明示する**: 短文（1900 字以下）は従来どおり 1 メッセージで挙動不変（T10 で固定）。長文は複数メッセージ化する（T11 で固定)。途中送信失敗時は先行チャンクのみ投稿済みとなり、既存と同じく warning ログで観測する（T12 で例外伝播を固定。/clear の「DB 削除済みだが send 失敗」と同型の既存許容パターン）
- `split_for_discord` / `send_chunks` は fake send（記録用 async 関数）で unittest 可能（`unittest.IsolatedAsyncioTestCase`）。discord.HTTPException の except 節のみ bot.py に残る（実機確認で担保）

### `/home` 連打時の同時実行制御は入れない（根拠明記）

rate limit / in-flight 合流は実装しない。根拠: (1) 本 bot は `ALLOWED_USER_IDS` で許可された個人ユーザーのみが使う単一ユーザー運用で、想定頻度は 1 日数回・手動入力。(2) sb-status 1 回 = SwitchBot API 3 リクエストで、SwitchBot API の日次上限（10,000 req/日）に対し 3 桁の余裕がある。(3) `asyncio.to_thread` の同時実行があっても各 subprocess は 20 秒で必ず打ち切られ、リソースは自然回収される。連打が実運用で問題化した場合に別 Issue で扱う。

## 実装対象

### 新規: `gateway/discord/commands/home.py`

`home_handler(ctx: CommandContext, args: str) -> str` を上記仕様で実装。

### 編集: `gateway/discord/commands/__init__.py`

import 行から全コマンド登録行までの省略なし before/after（現行 `__init__.py:21-32`）:

before:

```python
from . import clear, status, help as help_mod   # __init__ → handlers（一方向）

log = logging.getLogger("hermes-lite.discord.commands")

_COMMAND_RE = re.compile(r"^/([A-Za-z][A-Za-z0-9_-]*)(?:\s+(.*))?$", re.DOTALL)

COMMANDS: dict[str, Command] = {}
COMMANDS["clear"] = Command("clear", "セッションをクリア", clear.clear_handler)
COMMANDS["status"] = Command("status", "gloop の状態を表示", status.status_handler)
COMMANDS["help"] = Command(
    "help", "コマンド一覧を表示", lambda ctx, args: help_mod.render_help(COMMANDS)
)
```

after:

```python
from . import clear, home, status, help as help_mod   # __init__ → handlers（一方向）

log = logging.getLogger("hermes-lite.discord.commands")

_COMMAND_RE = re.compile(r"^/([A-Za-z][A-Za-z0-9_-]*)(?:\s+(.*))?$", re.DOTALL)

COMMANDS: dict[str, Command] = {}
COMMANDS["clear"] = Command("clear", "セッションをクリア", clear.clear_handler)
COMMANDS["status"] = Command("status", "gloop の状態を表示", status.status_handler)
COMMANDS["home"] = Command("home", "家電状態一覧を表示 (sb-status)", home.home_handler)
COMMANDS["help"] = Command(
    "help", "コマンド一覧を表示", lambda ctx, args: help_mod.render_help(COMMANDS)
)
```

- `home` の挿入位置は `status` の直後・`help` の前（機能コマンド → メタコマンドの順を維持）
- `help` は登録時スナップショットではなく **呼び出し時に lambda が `COMMANDS` 全体を列挙**する構造（`render_help(COMMANDS)`）のため、挿入位置に関わらず `/home` は `/help` に表示される
- 既存テストは help 出力の**存在のみ**検証しており（`test_commands.py::test_T05_help_lists_all_registry` はレジストリ全 name の包含チェック）、順序への期待はない

`dispatch()` 本体・`COMMANDS` 以外の既存関数には手を入れない（clamp 等の追加なし）。

### 編集: `gateway/discord/bot.py`（1 箇所）

slash 応答送信の分割送信化。before/after は設計方針「Discord 2000 字上限の保証」セクションに全文記載。

## テスト計画

`tests/test_commands_home.py`。`unittest.mock.patch("commands.home.subprocess.run")` で sb-status をモックし、実 API は叩かない。既存 `test_commands.py` と同じ sys.path 注入方式。

| ID | 内容 | 期待値 |
|---|---|---|
| T01_home_success | exit 0・stdout あり | ` ```plain ` コードブロックで stdout が返る。呼び出し引数が `[.../bin/sb-status]`・`timeout=20` |
| T02_home_json_flag | args `"--json"` | コマンドリストに `--json` が含まれ、JSON がコードブロックで返る |
| T03_home_failure_stderr | exit 1・stdout 空・stderr 複数行 | `⚠️ 家電状態の取得に失敗:` + stderr の 1 行目のみ |
| T04_home_timeout | `subprocess.TimeoutExpired` 送出 | `⚠️ 家電状態の取得がタイムアウトしました (20s)` |
| T05_home_unknown_args | args `"--verbose"` | subprocess 未実行（mock 未呼び出し）で使い方メッセージ |
| T06_home_registered | レジストリ登録 | `COMMANDS` に `home` があり、`render_help` 出力に `/home` が含まれる |
| T07_home_failure_with_stdout（境界） | exit 1・stdout 非空（部分失敗） | ⚠️ 行のみ（stdout は併記しない — Issue 決定事項の固定） |
| T08_home_args_whitespace | dispatch 経由 `"/home   --json  "` | `--json` 実行に正規化される（dispatch の strip 契約 + handler 防御の統合確認） |
| T09_home_stderr_long_line（境界） | stderr 1 行目が 500 字 | ⚠️ 行内の stderr 部分が 200 字で切られる |

`tests/test_transport.py`（`unittest.IsolatedAsyncioTestCase`、fake send = 呼び出しを記録する async 関数。config.py は env 未設定でも import 可能なことを確認済み）:

| ID | 内容 | 期待値 |
|---|---|---|
| T10_send_chunks_short | 1900 字以下のテキスト | send が 1 回だけ呼ばれ、内容が完全一致（既存 slash コマンドの挙動不変を固定） |
| T11_send_chunks_long（境界） | 5000 字・改行入りテキスト | send が複数回・順に呼ばれ、各チャンク ≤ limit。内容保持契約の検証: 改行以外の全文字が順序どおり保持され、失われるのはチャンク境界に選ばれた改行のみ（`"".join(chunks)` と元テキストの差分が境界改行に限られること） |
| T12_send_chunks_midway_failure（境界） | 2 チャンク目の send が例外 | 例外がそのまま伝播し、1 チャンク目は送信済み（部分送信の既存許容パターンを固定） |
| T13_split_for_discord_parity | 移設した `split_for_discord` | bot.py 旧実装と同じ分割仕様（改行位置優先・limit 超過時は強制切断・境界改行の lstrip）— 移設のリグレッション防止 |

bot.py に残る差分は「import 置換」と「send_chunks 呼び出し + 既存 except 節」のみで、ロジックは transport.py 側でテストされる。discord.HTTPException の except 経路は人間完了条件の実機確認で担保する。

## Issue body 抜粋

# Discord `/home` で家電状態一覧を返す

## 背景

`bin/sb-status`（Issue #12 で実装済み）を叩けば温湿度計・電気・カーテンの状態が一括で取得できる。Discord から状態確認したいとき、現状は自然文（「家電の状態は？」等）を投げて claude -p が runbook を読んで sb-status を呼ぶ経路になっており、レイテンシと token を消費する。

ユーザーは短いショートカット（`/home`）で家電状態を叩きたい（決定 2026-07-05、"bin とか打ちたくない"）。

## 意図（3 行）

- Discord bot（`gateway/discord/bot.py`）で `/home` を受けたら、claude -p を介さず bot が直接 `bin/sb-status` を subprocess 実行して結果を返す
- 出力はコードブロックに包んで Discord に投稿（人間可読の表形式）
- 応答時間はローカル HTTP → SwitchBot API 数百 ms + Discord API 送信で完結（claude -p 起動不要）

## 決定事項

### 動作

| 入力 | 動作 |
|---|---|
| `/home` | `bin/sb-status` を subprocess 実行、stdout をコードブロックに包んで返す |
| `/home --json` | `bin/sb-status --json` を実行、JSON をコードブロックで返す |

### 実装場所

- Issue #13 のスラッシュコマンド機構（`gateway/discord/commands/`）に乗る
- `gateway/discord/commands/home.py` を新設し、`COMMANDS` レジストリに登録
- subprocess で `~/hermes-lite/bin/sb-status` を実行（cwd=hermes-lite）、`stdout.decode()` を返す
- タイムアウトは 20 秒（SwitchBot API 3 リクエスト分の余裕）

### 応答フォーマット

- 成功: ```plain\n<sb-status の出力>\n```
- 失敗（exit != 0）: `⚠️ 家電状態の取得に失敗: <stderr の1行目>`
- タイムアウト: `⚠️ 家電状態の取得がタイムアウトしました (20s)`

### 権限制御

- 既存 bot と同じ `ALLOWED_USER_IDS` チェックのみ（副作用なしなので追加ゲート不要）
