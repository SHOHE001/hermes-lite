# Rejection log for #13

## Codex design review round 1 — 棄却した指摘

### contrarian M3: 「commands パッケージは MVP 3 コマンドに過剰設計。単一 commands.py で十分」

**棄却理由**: `commands/` 配下に 1 コマンド 1 ファイル + `__init__.py` レジストリという構成は、**Issue #13 の「決定事項（intake 時点で確定）> 実装場所」でユーザーが明示的に確定した事項**。

> - コマンド本体は `~/hermes-lite/gateway/discord/commands/` 配下に 1 コマンド 1 ファイルで実装（拡張性のため）
> - `commands/__init__.py` にレジストリ（`COMMANDS: dict[str, Command]`）を置き、bot はレジストリ経由で dispatch

CLAUDE.md の推測禁止ルールにより、ユーザーが確定した構成を Codex の一般論（YAGNI）で覆さない。拡張候補（`/intake` `/compact` `/jobs` `/gloop-status`）が Issue に列挙されており、レジストリ方式の拡張性は要件として妥当。

---

## Round 1 採否サマリ（blocking 6 = 3 persona × 2）

**採用（plan.md に反映、`[R1 …]` タグ付き）:**

- architect H1 / contrarian H1 / migration H1「sqlite を to_thread に渡すと壊れる」→ `CommandContext` に live store ではなく `sessions_db: Path` を注入、`/clear` は worker thread 内で新規 `SessionStore` を開く設計に変更（persona の suggestion 通り）。`check_same_thread=False` / WAL / `delete(scope_key)` 実在を実コードで裏取り。
- architect H2「純粋ロジックと副作用の矛盾」→「discord 非依存の application-service 層（副作用は注入パス経由）」と再定義。
- contrarian H2「/help 入力仕様が曖昧」→ 対応入力形式（DM/thread/input-ch は plain、他 guild は `@bot /help`）を明文化。
- migration H2「on_message 退化テストが無い」→ 自動は discord 依存で不可（テスト規約が discord 非依存）と明示し、退化は手動 test-spec + 分岐述語 `is_command` の自動テストで担保。
- 全 persona「args データフロー未定義」→ `handler(ctx, args)` シグネチャ + `frozen` dataclass で確定。
- architect M4 / migration M5「import 衝突/本番 ModuleNotFoundError」→ 既存 bare top-level import 規約 + `WorkingDirectory` + `requirements.txt` を裏取りし整合を明記。
- architect M5 / contrarian M5「/status のログスキーマが弱い」→ `*.json` 限定 + `result` キー必須 + 破損 skip（`.jsonl` 実在を裏取り）。T11/T12 追加。
- migration M4「未知 `/` の挙動変更が未明示」→ Non-Goals に意図的変更として明記。
- architect M6「/status が gloop 内部ファイルに直結」→ 既存 python API 不在を明記、status.py 内で関数分割し将来 service 化余地を残す。
- 全 persona L「例外 reason の Discord 露出」→ 固定文言化 + `log.exception`。T06 を固定文言期待に更新。

**棄却:** contrarian「commands パッケージは過剰設計」（上記の通り Issue 確定事項）。

---

## Round 2 採否サマリ（blocking 7）

**採用（plan.md に `[R2 …]` タグで反映）:**

- architect H1 / contrarian H1 / migration H1「`is_command` が広すぎ Non-Goals と矛盾」→ `is_command` を正規表現 `^/[A-Za-z][A-Za-z0-9_-]*(?:\s+.*)?$` に固定。`/tmp/foo` `//x` `/ 相談` `/?` `/` は `_handle` フォールバック。T13 追加。
- architect H2 / contrarian H2「/help の循環 import」→ 依存方向を `__init__ → handlers` 一方向に固定。`help.py` は `render_help(registry)` の純粋関数のみ、package を import しない。help はアダプタで呼び出し時に `COMMANDS` 参照。
- contrarian M / migration M「registry テスト注入が global 汚染」→ `dispatch(…, registry=None)` を注入可能に。T06 は custom registry を渡し global 不変を検証。
- architect L / contrarian M / migration M「エラー文言の二重定義」→ `COMMAND_ERROR_MESSAGE` / `UNKNOWN_COMMAND_MESSAGE` を定数化、bot 外側 catch も同一定数。
- contrarian M「SessionStore 接続ライフサイクル未定義」→ `session_store.py` に `close()` 追加、clear_handler は try/finally で close。
- contrarian M「dispatch 非コマンド防御の期待値未定義」→ dispatch は parse None 時も `UNKNOWN_COMMAND_MESSAGE`。
- migration H2「config export 未検証で本番 ImportError の恐れ」→ `config.py:21,27` が `SESSIONS_DB`/`HERMES_HOME` を export 済み・`bot.py:14-23` が既に import 済みを裏取りし明記（追加 config 変更不要）。
- migration M「/clear テストが実 SessionStore API を使うか不明」→ T02 を実 `set()`/`get()` 経由に明記。
- architect M3「/status のスキーマ contract が曖昧」→ 読み取り contract 表を追加、各フィールド欠損時の表示を固定。
- architect M2「commands 層の境界名が曖昧」→「Discord gateway 専用ローカルコマンド層」と責務を狭め、service 化候補を /status 読み取りに限定。

**棄却:**

- contrarian H3「`/status` を別 PR / 軽量 health に分離せよ」→ **棄却**。Issue #13 タイトルが `/clear /status /help から` と `/status` を MVP 3 に明示。round 1 の「過剰設計」棄却と同じく Issue 確定スコープを Codex の一般論で削らない（推測禁止・スコープ尊重）。リスク（dispatch 基盤と status 収集の混在）は status.py の完全隔離 + per-field フォールバックで緩和し、status 不具合が dispatch/clear を落とさないことを設計で保証する。

---

## Round 3 採否サマリ（blocking 6）

**採用（plan.md に `[R3 …]` タグで反映）:**

- architect H2「registry の import が全 handler 依存 → 1 コマンド破損で bot 起動ごと落ちる」→ handler モジュールは import 時 IO・副作用を持たない設計条件を明記（status の重処理は関数内に限定）。
- architect M「`CommandContext` 型参照 と『handler は __init__ を import しない』制約の衝突」→ 型・定数を leaf module `commands/types.py` に分離、handler は leaf を参照（循環しない）。
- contrarian H1 / migration H2・M「on_message 分岐順序が自動テストされない」（round 2〜3 で反復）→ 内容ベース分岐を discord 非依存の純関数 `classify(stripped, approval_enabled, approval_match)` に切り出し、approval>slash>handle を T14 で自動テスト。discord 依存の `_should_react` ゲートのみ手動 test-spec と明示。
- architect M「on_message before/after が抜粋で検証しづらい」→ 該当ブロックを省略なしで before/after 提示。
- migration H「`SessionStore.close()` の既存互換性」→ 追加メソッドで既存呼び出し元不変、long-lived store は close しない、/clear の別接続のみ close（terminal）を明記。
- migration M「`parse` の whitespace 契約」→ args を strip、T15 追加。
- architect M / contrarian M「`commands` 名が汎用すぎ discord.ext.commands と紛らわしい」→ Issue 決定でディレクトリ名 `commands/` は変えず、bot.py で `import commands as slash_commands` と alias。

**棄却:**

- migration H1「未知 `/英字` は `_handle` にフォールバックすべき（後方互換）」→ **棄却**。Issue #13 本文『応答フォーマット › 不明コマンド — `❓ 未知のコマンド。/help で一覧`』で未知コマンドの `❓` 応答を明示決定済み。`/`+英字 はコマンド namespace（将来 `/intake` `/jobs` 等を追加する前提）として横取りするのが Issue の意図。非英字（`/tmp/foo` 等）は既に `_handle` フォールバックで互換保持済み。推測禁止で intake/Issue body を確認の上、決定事項を優先。
- contrarian H2「`/status` を簡易 health に縮小 / 別 PR」→ **再棄却**（round 2 H3 と同一。Issue が MVP に明示）。
- contrarian M「単一 `bot_commands.py` に縮小」→ **再棄却**（round 1 と同一。Issue 決定で `commands/` パッケージ + `__init__` レジストリ確定）。
- architect H1「/status の gloop ファイル読取を gateway 外の status provider に注入せよ」→ **棄却（裁量）**。MVP で gateway 外に共有 status service を新設するのは scope 拡大（既存に該当 service なし）。architect（層を増やす）と contrarian（層を減らせ）の緊張の中間を取り、読取は status.py に隔離しつつ `_read_*` 関数分割で将来切り出せる形に留める。密結合は contract 表で明示済み。

---

## Round 4 採否サマリ（blocking 6）

**採用（plan.md に `[R4 …]` タグで反映）:**

- architect H2 / contrarian L「`classify` の引数冗長・approval_match 二重・唯一の真実の過剰主張」→ `classify(stripped, approval_match) -> Literal[...]` に単純化。approval 成立条件は bot が bool に畳む責務分担を明記。
- architect L「route が bare string で拡張に弱い」→ `Literal["approval","slash","handle"]` 戻り型。
- contrarian M「dispatch の parse-None 防御が API 境界を曖昧に」→ parse 不能は契約違反＝内部エラー（`COMMAND_ERROR_MESSAGE` + `log.error`）、UNKNOWN は「解析成功だが未登録」に限定。
- contrarian M「close だけ足すのは重い」→ `SessionStore` を context manager 化（`with` 利用）、`close()` は冪等。
- migration H「slash 応答 send 失敗時の挙動未定義（/clear は状態変更済み）」→ send を try/except HTTPException で包み warning（既存 compaction notice と同流儀）。
- migration M「close 済みインスタンス挙動未定義」→ 冪等 + terminal と明記。
- architect H1「import 境界の矛盾（clear/status の依存で bot 起動が単一障害点）」→ handler は import 時 IO なし（class import + stdlib のみ、接続/glob は関数内）を明記、T16「gloop ファイル不在でも `import commands` 成功」を追加。
- architect M「/status の DTO 未定義」→ `_read_*` が small DTO を返す adapter、`status_handler` はスキーマ非依存を明記。

**棄却（persistent judgment calls）:**

- contrarian H「`/status` を placeholder / 別 PR」（4 回目）→ **再棄却**。Issue MVP 明示。リスクは status.py 完全隔離 + per-field フォールバックで緩和済み。
- contrarian M「パッケージ名 `commands` → `local_commands`」/ architect M（同旨）→ **棄却**。Issue 決定でディレクトリ配置 `gateway/discord/commands/` 確定。bot.py alias + テストの sys.path 制約（先頭に `gateway/discord`、外部 `commands` 非前提、bot.py 以外で `import commands` を広げない）で曖昧さを緩和。
- migration H「未知 `/英字` を `_handle` にフォールバック / escape 機構」（3 回目）→ **再棄却**。Issue body で不明コマンド `❓` を明示決定。`/`+英字 = コマンド namespace（将来コマンド追加前提）。非英字は既に `_handle` フォールバックで互換保持。

---

## Round 5 採否サマリ（blocking 6）

**採用（plan.md に反映）:**

- architect H / contrarian H / migration H「T14 が旧 3 引数 `classify(…,True,True)` のまま = 設計とテストの矛盾」→ **本物のバグ**。T14 を 2 引数 `classify(approval文, True)` 等に修正。
- architect H「clear.py の session_store top-level import が import 安全境界を崩す」→ `clear_handler` 内で `SessionStore` を**遅延 import**、clear.py の module top を stdlib のみに。
- architect L / migration M「新規ファイル一覧の close 方針（try/finally）が context manager と不一致」→ `with SessionStore(...)` に表記統一。
- architect M / migration M「status DTO が dict で分離効果が弱い」→ `LoopStateStatus`/`TmuxStatus`/`LatestJobStatus` を `dataclass(frozen=True)` で定義、handler は属性のみ参照。
- migration M「close の長寿命接続影響テストが弱い」→ T02 に長寿命インスタンスでの set→別接続 clear→再 get 反映ケースを追加。
- architect M（名前曖昧さ）→ テストも alias `slash_commands` 統一・`sys.path` 先頭固定・`dispatch`/`classify` は gateway 内部 API と明記。

**棄却（persistent judgment calls, 変更なし）:**

- contrarian H / migration H「未知 `/英字` fallback / is_command を既知コマンド限定」（4〜5 回目）→ **再棄却**。Issue body の決定（不明コマンド `❓`）を優先。
- contrarian M「`/status` を stub / 別 PR」（5 回目）→ **再棄却**。Issue MVP。
- contrarian M「dispatch の内部エラー契約が単純でない」→ **棄却**。dispatch は gateway 内部 API（bot のみ呼ぶ、is_command 済み前提）。parse-None は契約違反検出の防御であり通常 UX には出ない。

---

## Round 6 — design_loops=5=max 到達、裁量で passed（残置 findings 転記）

`max_design_loops=5` に到達。`.claude/gloop-config.json` の `stop_conditions.ask_user_on_blocking: false` によりユーザー確認なしで自動裁量採用。round 6 の high 6 件はすべて (a) Issue 決定に基づき棄却済みの判断保留、または (b) 既に plan の after-code で対処済み で、**新規の showstopper なし**。以下に裁量残置として転記する:

- architect H「SessionStore 直 import で依存境界が破れる」/「import 安全性が実行時依存未評価」→ **裁量残置（対処済み）**。R5 で clear.py は `SessionStore` を handler 内遅延 import に変更、status.py は stdlib のみ、help は純関数。`import commands` は DB/gloop ファイル不在でも安全（T16 で固定）。architect の要求水準（handler の一切の実行時依存を設計で評価）は adversarial 最大化であり、MVP の設計健全性は担保済みと判断。
- architect M / contrarian M「package 名 `commands` の曖昧さ / registry・Command dataclass が MVP に重い」→ **裁量残置（棄却）**。Issue 決定でディレクトリ配置・レジストリ方式は確定。alias + テスト制約で緩和済み。
- architect M「classify が commands package に置かれ routing 責務混在」→ **裁量残置（棄却）**。classify は discord 非依存の低レベル route chooser で、bot.py 側の approval 成立判定と責務分離済み。commands package 内配置は test 可能性（discord 非依存）のため。
- contrarian H「bot.py 実ルーティングが自動テストされない」/ migration「on_message 退化」→ **裁量残置（対処済み範囲で棄却）**。内容分岐は classify + T14 で自動化。discord 依存の `_should_react`/`_scope_key` はプロジェクトのテスト規約（discord 非依存 unittest）上、手動 test-spec で担保。
- contrarian H「/status 過剰・別 PR」→ **裁量残置（棄却）**。Issue MVP 明示（6 回目）。
- migration H「未知 `/英字` 横取り・移行パス無し」→ **裁量残置（棄却）**。Issue body で不明コマンド `❓` を明示決定（6 回目）。
- migration H「approval handler import failure 時の既存挙動破壊」→ **裁量残置（対処済み）**。plan after-code は `route=="approval"` 内で `_approval_handler is None` 時に既存の "approval feature disabled" warning を送って return する経路を保持。`approval_match` は handler 可用性に依存しないので、import 失敗時も approval 予約語の捕捉挙動は従来通り。
- その他 medium/low（context manager before/after・close 契約・namespace UX・完了条件文言）→ **裁量残置**。実装（implementer）段階の詳細 or 軽微。STEP 7 最終レビューで再評価する。

commit message（STEP 8）本文に「Codex design blocking 6 件裁量残置（判断保留の再指摘 + 対処済み再確認、新規 showstopper なし）」を明記する。
