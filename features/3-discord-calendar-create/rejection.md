# Rejection log for #3

## Round 1 (design_loops=1) — 反映方針

3 persona の指摘はほぼ全件採用。重複指摘を統合した結果、設計の核を以下のように改める:

### 採用 (plan v2 に反映)

- **executor を LLM ジョブから固定 Python スクリプトに変更** (architect M / contrarian H1 / migration H2)
  - `lib/approvals_executor.py <approval_id>` を bot.py から `systemd-run` で起動
  - LLM が prompt 内で Calendar.create を呼ぶ構造を廃止
  - `jobs/calendar-create-executor/` 自体を作らない (固定スクリプトで完結)
  - これにより「Calendar.create の制御が prompt 頼み」「LLM の裁量で別予定を作る余地」が構造的に消える

- **payload schema を In-Scope に格上げ** (contrarian H2)
  - 必須キー: `summary` (str, 1..256 chars), `start`, `end` (ISO 8601 with tz), `timeZone` (str, IANA)
  - 任意キー: `description` (str, ≤ 2000 chars), `location` (str, ≤ 256 chars)
  - 未知キー拒否 / `end > start` / `start > now - 30min` (過去すぎる予定拒否) を enqueue() 時 + executor 起動時の両方で検証
  - validation 失敗時は executor が done(success=False) で `failed` 遷移

- **HERMES_HOME 一本化** (architect H2 / migration H3)
  - `lib/approvals.py` は `os.environ.get('HERMES_HOME')` 必須 (未設定なら `Path(__file__).resolve().parents[1]` で導出)
  - `~/hermes-lite` 直書きを撤廃。proposer prompt も `$HERMES_HOME/lib/approvals.py` 経由に
  - `run-claude.sh` が `HERMES_HOME` を必ず export していることを plan に明記 (実装側で確認)

- **approval コマンドに `approval` prefix 必須** (migration H1)
  - 旧: `^(yes|y|approve|no|n|reject)\s+#?<id>$`
  - 新: `^approval\s+(approve|reject)\s+#?<id>$` (case-insensitive)
  - 既存質問応答との衝突を構造的に排除。承認依頼本文も新文法で案内
  - DB miss の場合は bot が `⚠️ #ID は不明` を返す (既存 claude-runner にはフォールバックしない、approval prefix が付いた時点で approval 経路と確定)

- **ID 規格固定** (architect L / contrarian M / migration L)
  - regex を `[a-f0-9]{8}` に固定 (短縮 / 拡張は許可しない)
  - prefix lookup は採用しない

- **take は approval_id 指定のみ** (architect H1)
  - `take(approval_id, executor_job)` の API に統一
  - bot は decide approve 成功時に `systemd-run --user --no-block --setenv=HERMES_APPROVAL_ID=<id> ... approvals_executor.py` で id を渡す
  - executor 起動時は `HERMES_APPROVAL_ID` を読んで take(id, "calendar-create-executor") する
  - これで「最古 approved を勝手に拾う」事故が構造的に消える

- **systemd-run 起動失敗時は `failed` に落とす** (architect M / migration H2)
  - bot.py 内で subprocess.CalledProcessError をキャッチしたら `approvals.fail(id, result_text="systemd-run failed: ...")` を呼ぶ
  - 再試行は新規 proposer 起動で別 ID を起こす (MVP では rollback API なし、Non-Goal 維持)
  - Discord に `⚠️ #ID 承認は記録したが executor 起動失敗 → failed に変更` を返す

- **done() に state guard** (migration M)
  - `UPDATE approvals SET status=?, result_text=? WHERE id=? AND status='executing'` の atomic UPDATE
  - affected rows != 1 なら CLI は exit 1 / Python API は ValueError

- **DB schema version** (migration M)
  - `PRAGMA user_version = 1` を CREATE 時に設定
  - 起動時に `user_version` と必須 column を assert。不一致なら明示エラー (バックアップ + 再作成手順は docs に)

- **bot.py の before/after を plan に追加** (contrarian M / migration M)
  - 既存 on_message のコード断片 + 変更後 snippet を plan v2 に貼る

- **テスト追加** (migration M)
  - T11_existing_question_fallback: `yes #abcd1234` のような approval 風文言 (approval prefix なし) を投稿 → 通常の claude-runner 経路へ流れる (DB は変化なし)
  - T12_done_state_guard: pending row を直接 done(success=True) で叩く → exit 1 + DB は変化なし
  - T13_db_path_consistency: bot 経路と CLI 経路で同一 sqlite ファイル inode を見ていることを確認 (`stat` で inode 比較)

### 棄却 (採用しない)

- contrarian M: 「対立案として `calendar-create-approved.py <id>` を比較表に入れる」
  → 比較表の代わりに、**plan v2 ではそもそも固定スクリプト案を採用** したので、比較表自体が不要 (採用案の根拠として contrarian H1/H2 の指摘を明記する)。

### 影響範囲の変化

- `jobs/calendar-create-executor/{prompt.md, job.env}` を削除 → executor は `lib/approvals_executor.py` 1 ファイル
- `gateway/discord/bot.py` の approval handler は `subprocess.Popen` → `subprocess.run(["systemd-run", ...], check=True)` + try/except で `fail()` 経路
- `lib/approvals.py` に `validate_payload()` / `fail()` / `take(id, executor_job)` / schema version check を追加
- proposer ジョブの prompt も `approval <id> approve` 文法で承認依頼本文を案内

これらを v2 plan に書き直して STEP 3 再 dispatch。

## Round 2 (design_loops=2) — 反映方針

3 persona ともまだ blocking=3。共通指摘 4 件 + 個別の本質的指摘が複数。

### 採用 (plan v3 に反映)

- **「固定 Python executor」の言明を撤回し、LLM executor として正直に再定義** (architect H1 / contrarian H1)
  - 根拠: MCP `create_event` は Anthropic 提供の OAuth managed integration で、Hermes-lite から MCP server を直接呼ぶ手段は無い (Claude CLI 経由のみ)。Google Calendar API 直叩きには別 OAuth client 構築が必要で、Phase 1 MVP のスコープを超える。
  - plan v3 では「**LLM executor を用いる**。ただし以下の構造で LLM の裁量を最小化する」と明記
  - 構造的対策:
    - prompt 本文は固定テンプレ
    - payload は JSON ブロックとして渡し、prompt 内で「JSON の値をそのまま field として渡せ」と指示
    - claude -p の `--output-format json` 出力から **`tool_use_count == 1` かつ `tool_name == "mcp__claude_ai_Google_Calendar__create_event"`** を検証 (executor の Python 側で done/fail を判定)
    - これにより「LLM が複数イベント作る / 別 tool を呼ぶ」リスクを構造的に検出
  - prompt injection (contrarian H2): payload.summary/description が natural language を含むこと自体は防げないが、上記の **tool 呼び出し件数チェック** で「LLM が指示を解釈して別操作する」リスクは検出される

- **Non-Goal 矛盾解消: `bin/run-claude.sh` を編集対象から外す** (architect H2 / migration H2)
  - HERMES_HOME は proposer prompt / executor / bot の各箇所で **自己導出** (`Path(__file__).resolve().parents[N]` または環境変数フォールバック)
  - run-claude.sh は触らない (Non-Goal 維持)

- **`.gitignore`** (architect M / contrarian M / migration H1)
  - `var/*` + `!var/.gitkeep` の 2 行で明記

- **approval regex `#` 任意で確定** (architect M / contrarian M / migration M)
  - regex は `#?` のまま (現状の任意)
  - plan 本文 / docs / 通知 / テストすべてで「`#` は任意」と統一表記
  - 「`#` のみ受け付ける」表現は削除

- **権限境界明示** (architect H3)
  - bot プロセスは user systemd unit (現状の `hermes-lite-discord.service`) で動く
  - systemd-run のコマンドラインに以下を明示: `--working-directory=$HERMES_HOME` / `--setenv=HERMES_APPROVAL_ID` / `--setenv=HERMES_HOME` / `--setenv=PATH` (CLAUDE_BIN への parent dir 含む)
  - executor の `claude -p` 起動時は Claude config (`~/.claude/.credentials.json`) と MCP config (`~/.claude/mcp.json` または同等) をユーザー権限で参照する (これは Discord runner と同じ前提)
  - 「悪意ある攻撃者から守る」目的ではない (これは Hermes-lite 全体の信頼境界の前提) と plan に明記

- **schema: `executed_at` → `started_at` / `finished_at` に分割** (architect L)
  - take() で `started_at = now`、done()/fail_during_executor() で `finished_at = now`

- **`fail()` を 2 API に分割** (migration M)
  - `fail_before_executor(id, *, result_text)`: `approved → failed` のみ許可 (bot 専用)
  - `fail_during_executor(id, *, result_text)`: `executing → failed` のみ許可 (executor 専用)
  - これで race の意図が明示される。両方とも affected!=1 で ValueError

- **payload → MCP create_event field 対応表** (architect M)
  - plan v3 に表を追加: `summary → summary`, `start (ISO 8601 with tz) → start.dateTime`, `end → end.dateTime`, `timeZone → start.timeZone, end.timeZone`, `description → description`, `location → location`

- **T11 分割 + テスト追加** (migration H3)
  - T11a_question_fallback_no_prefix: `yes` / `yes abcd1234` を投稿 → 既存 claude-runner 経路 (DB 変化なし)
  - T11b_unknown_id_no_fallback: `approval approve deadbeef` (DB 無し) → bot が「不明」と返す (fallback しない)
  - T11c_case_whitespace: `APPROVAL APPROVE   ABCD1234`, `approval approve #abcd1234` を投稿 → どれも同じ ID として処理される

- **T02 rename** (migration L)
  - T02_yes_executes → T02_approval_executes
  - T03_no_rejects → T03_approval_rejects

- **systemd-run 起動後の即時失敗観測** (contrarian M)
  - systemd-run --no-block は起動依頼の成功 (= main PID fork) しか保証しない
  - 即時失敗 (import error / FileNotFoundError 等) は `journalctl --user -u hermes-exec-<id>-<ts>` で観測可能
  - executor 内で `approvals.take()` を成功 (executing 遷移) するところまで到達できない場合、bot 側からは observable でない
  - MVP では追加観測機構は実装しない (Non-Goal): 実運用で stale `approved` row が残った場合は manual 復旧手順を docs に書く

- **schema mismatch degradation** (migration M)
  - docs に「v1 から将来 v2 に上げる場合: 既存 pending/approved は破棄前提。proposer から新規 ID で再起票する運用」と明記
  - bot が起動時 schema mismatch で例外 → systemd で再起動失敗 → 運用者が journalctl で確認 → backup + 再作成

### 棄却

- contrarian H3: 「より単純な代替案 (MCP server 直接呼び出し / Google Calendar API 直叩き)」
  → 上記の通り、現実的に Hermes-lite が取れる経路ではないため、根拠を plan に明記して採用しない

- migration M (`fail()` race): race 時の期待値曖昧
  → `fail_before_executor()` と `fail_during_executor()` に分けることで「bot 側と executor 側がそれぞれの状態でのみ fail できる」を構造的に明示。同時 race は systemd-run が呼ばれてから executor が executing 遷移するまでの ~100ms 程度で発生し得るが、その場合は bot 側 `fail_before_executor()` (status='approved' check) が affected=0 で例外 → bot は別エラーメッセージを返す。これで意図通り。

## Round 3 (design_loops=3) — 反映方針

3 persona で blocking 8 件。共通指摘 (HERMES_HOME 脆さ、LLM executor の事後検証性) + 個別本質指摘 (proposer LLM ジョブ自体が信頼境界を侵害、approval_handler の config 経由化、tool_use JSON 構造未検証、stale executing sweep、unit test 追加等)。

### 採用 (plan v4 に反映)

- **`bin/run-claude.sh` の `HERMES_HOME` export 1 行を実装対象に格上げ** (architect H2 / contrarian H2 / migration H1)
  - 旧 plan の「Non-Goal: bin/run-claude.sh は触らない」を撤回
  - 既存の `HERMES_HOME="$(cd ... pwd)"` 局所変数を `export HERMES_HOME=...` に変更する 1 行差分のみ
  - これで proposer の prompt 内 realpath 推測を廃止 → 既存ジョブも HERMES_HOME を subprocess 環境変数として持つ (副作用は微小、既存ジョブで HERMES_HOME を別意味で使う箇所は無い)
  - test として「export 前後で既存 ping/mail-watch ジョブが回ること」を T17 として追加

- **proposer を「Bash 1 行 enqueue」のみのジョブに格下げ** (architect H1)
  - LLM の判断・解釈の余地を完全に消す。prompt.md は「以下の Bash コマンドを順に実行して結果テキストを返せ」型の決定論的レシピ
  - LLM は手順を理解して echo / date / python3 を叩くだけ。承認 payload の生成は CLI 引数で固定値を渡す
  - 将来 mail-watch ベース proposer を作るとき、`enqueue` API に対する allowlist 検証は `validate_payload` と `ALLOWED_ACTIONS/EXECUTORS` で既に強制されている

- **状態遷移表を plan に追加** (architect M)
  - 各 API がどの status 同士の遷移を許すか、affected != 1 のときの挙動を表で明示

- **`HERMES_SYSTEMD_RUN_BIN` env で systemd-run path を上書き可能化** (migration H3)
  - approval_handler.py で `SYSTEMD_RUN = os.environ.get("HERMES_SYSTEMD_RUN_BIN", "systemd-run")`
  - T14 は `HERMES_SYSTEMD_RUN_BIN=/nonexistent` で bot を起動して `approval approve <id>` を投稿することで FileNotFoundError 経路を再現

- **stale executing sweep API 追加** (contrarian M)
  - `_EXECUTING_TTL_SEC = 1800` (30 min)
  - `sweep_stale_executing()`: `UPDATE approvals SET status='failed', result_text='stale executing (>1800s)', finished_at=? WHERE status='executing' AND started_at < ? - 1800`
  - bot の 1h sweep loop で呼ぶ。CLI でも sweep-stale-executing として呼べる
  - T18_stale_executing_sweep を追加

- **approval_handler が config.py 経由で HERMES_HOME / APPROVALS_DB を借用** (architect M)
  - approval_handler.py 冒頭で `from gateway.discord.config import HERMES_HOME, APPROVALS_DB` (相対 import) と `os.environ.setdefault("HERMES_APPROVALS_DB", str(APPROVALS_DB))` を組み合わせる
  - これで「bot 側と CLI 側で必ず同一 sqlite を見る」を構造的に強制

- **`bot.py` の approval_handler import を lazy / try-except** (migration M)
  - bot.py top では import しない。`on_message` 内で `import gateway.discord.approval_handler as approval_handler` を遅延 import
  - ImportError は warn ログのみで bot 自体は普通の質問応答を継続できる
  - T19_lazy_import_resilience を追加

- **get()/take() の return dict schema 明記** (migration M)
  - 共通 schema: `{id, proposer_job, executor_job, action, summary, payload (parsed dict), payload_json (raw str), status, created_at, expires_at, decided_at, started_at, finished_at, result_text}`
  - CLI モードの `get` は `payload` を parsed dict のまま JSON dump
  - `take()` は同じ schema を返す (内部で parse 済み)

- **Claude CLI `--output-format json` の tool_use 構造を plan に書く** (contrarian H3)
  - logs/ が空なので、plan v4 では「**実装時に `claude -p --output-format json` を 1 度走らせて構造を実測する**」+ 「**期待構造の仮説**」を明記
  - 仮説: top-level に `messages: [{role: "assistant", content: [{type: "tool_use", name, input}, ...]}, ...]` または `usage.tool_use_count` 相当
  - 実装者は試走で構造を確認し、`extract_tool_calls()` を書く。仕様の確認結果は `features/.../claude-cli-tool-use-evidence.md` として保存し、PR の根拠とする
  - **このため**、STEP 5.5 (acceptance skeleton) の前に **「claude -p 実行で tool_use JSON 構造を確認する」探索フェーズ** を 1 つ追加 (test-spec.md に書く)

- **既存質問応答との衝突を migration notice として明記** (migration H2)
  - docs/discord-approval.md に「**予約語**: `approval approve <8hex>` および `approval reject <8hex>` (case-insensitive、`#` 任意) は本 Issue 以降 bot コマンドとして扱う。既存の通常会話で同形式を使っていた場合は破壊的変更となる」と明記
  - テスト T11b で「予約語化が意図通りで claude-runner にフォールバックしない」を検証

- **`lib/approvals.py` のみ unit test を tests/test_approvals.py で追加** (contrarian M)
  - project_type=jobs だが、`approvals.py` は state machine + sqlite で unit test しやすい
  - tests/test_approvals.py に pytest または unittest を書き、tmpfile DB で全状態遷移を検証
  - 既存依存に pytest が無ければ Python 標準の `unittest` を使う (依存追加なし)
  - test-spec.md は手動 E2E チェックを残すが、自動化可能な部分は automate

- **絵文字と ASCII tag 併記** (migration L)
  - bot 応答: `✅ [OK] #<id> 承認 → executor 起動 (unit=...)`、`❌ [REJECTED] #<id> 却下`、`⚠️ [WARN] #<id> は不明`
  - テストは ASCII tag (`[OK]` / `[REJECTED]` / `[WARN]`) で assert することで Unicode 比較差分を回避

### 棄却

- contrarian H1 (LLM 事後検証では二重作成を防げない):
  → 上記「v3 の Non-Goals」の MCP 直叩き不可根拠を継承し、副作用後検出であることを **正直に plan に明記**。複数作成時の Calendar 手動 cleanup 手順 (Discord 通知に作成された event の htmlLink を含めて、ユーザーが手動で 1 件削除する) を docs に追加。

- contrarian H3 (allowed/disallowed 優先順位):
  → mail-watch ジョブで実際に `claude -p --disallowed-tools <list> --allowed-tools <list>` を併用しており、実運用で動作している前提を plan に明記 (`gateway/discord/claude_runner.py` も同じパターン)。`read_disallowed_minus()` は exact-line 除外で問題ない (テキストファイルの 1 行ずつ tool 名)。

- migration M (DB migration 戦略):
  → MVP では v1 のみで完結。v2 以降は出てきたときに `_migrate_schema()` を実装する方針を plan に明記 (将来 Issue として `features/.../followups.md` に書き出す。本 Issue では破棄+再起票のみ)。

- architect L (line 番号依存):
  → 行番号は plan 検討時のスナップショット。実装フェーズで teammate が必ず現在ファイルを再 Read する旨を plan に明記。

### round 4 で残る可能性のある blocking

- contrarian の「LLM executor は本質的に副作用後検出」は永遠に消えない。次回も同じ指摘が来る可能性大 → **「裁量で残置」する** ことを許容する。max_design_loops=5 まで余裕があるので round 4 を 1 度回し、まだ blocking が contrarian H1 のみなら裁量で先に進む判断とする。

## Round 4 (design_loops=4) — 反映方針

blocking=8 (architect 2 + contrarian 4 + migration 2)。新規本質指摘あり。

### 採用 (plan v5 に反映)

- **`sweep_stale_approved()` 追加** (architect H1)
  - `approved` 状態で `decided_at < now - 600` (10 min) を `failed` に
  - 理由: executor 起動失敗で row が approved のまま残るケースの救済
  - bot の 1h sweep loop で sweep_expired / sweep_stale_executing / sweep_stale_approved の 3 つを呼ぶ
  - 状態遷移表に追記
  - T20_stale_approved_sweep を追加

- **`decide()` / `take()` の WHERE に `expires_at > now` 追加** (contrarian H1)
  - decide(): `UPDATE ... WHERE id=? AND status='pending' AND expires_at > ?` (now)
  - take(): `UPDATE ... WHERE id=? AND executor_job=? AND status='approved' AND expires_at > ?`
  - affected==0 のとき、`get()` で確認して expired ならその status を返す
  - 状態遷移表に「decide() は expired を expire を経由してから処理」を追記
  - T21_decide_after_expire_atomic を追加

- **tool_use input と payload の完全一致検証** (contrarian H2)
  - `extract_tool_calls()` が `{name, input}` を返せる場合、payload から期待される create_event 引数を生成し、input と完全一致を assert
  - 期待引数生成 (`expected_create_event_args(payload)`):
    ```python
    {
        "summary": payload["summary"],
        "start": {"dateTime": payload["start"], "timeZone": payload["timeZone"]},
        "end": {"dateTime": payload["end"], "timeZone": payload["timeZone"]},
        **({"description": payload["description"]} if "description" in payload else {}),
        **({"location": payload["location"]} if "location" in payload else {}),
    }
    ```
  - input が取れない (claude CLI JSON 形式の制約で `tool_use_count` だけしか取れない) 場合は、件数と name の検証のみで進む (副作用後検出制約に格下げ)
  - T22_tool_use_input_mismatch を追加 (mock claude で input を改変)

- **feature flag `HERMES_APPROVAL_COMMANDS_ENABLED`** (migration H2)
  - default `"1"`。`"0"` のとき approval_handler は loaded されても `looks_like_approval` が常に False を返す
  - bot.py 側は flag 有効時のみ approval 経路に流す
  - これで予約語化の段階移行が可能 (初期は無効化、移行通知後に有効化)

- **bot.py に handler 不在時の予約語捕捉 (architect M)**
  - approval_handler import 失敗時でも、bot.py 内の軽量 regex (`_APPROVAL_PATTERN`) で予約語を捕捉し `"⚠️ [WARN] approval feature disabled (import failed; see journalctl)"` を返す
  - これで「予約語化が migration notice と一致する」(handler 不在でも通常 _handle には流れない)
  - T19 を更新: lazy import 失敗時でも予約語は捕捉される

- **`enqueue()` で executor_job 整合性チェック** (migration M)
  - `if executor_job != ALLOWED_EXECUTORS[action]: raise ValueError("executor_job mismatch")`
  - T23_enqueue_executor_mismatch を追加

- **`list` CLI 追加** (migration M)
  - `python3 lib/approvals.py list [--status pending|approved|...]` で row 一覧を JSON 配列で stdout
  - 運用・migration 用 (schema mismatch 時に未処理 ID を確認できる)
  - T24_list_cli を unit test に追加

- **jq 依存撤廃** (architect M / contrarian M / migration M)
  - proposer prompt で payload 生成を `python3 -c "import json, sys; print(json.dumps({...}))"` に置換
  - 既存 Hermes-lite 環境への新規外部依存なし

- **PEP 604 → Optional 統一** (migration H1)
  - 型注釈で `str | None` / `dict | None` を使わず `Optional[str]` / `Optional[dict]` に統一
  - サーバー gen8 は Ubuntu 24.04 で Python 3.12 のはずだが、念のため互換性高めに寄せる
  - 1 行 `from typing import Optional` を全モジュールの先頭に

- **sweep loop 重複起動防止** (contrarian M)
  - module-level global `_sweep_task: asyncio.Task | None = None`
  - `on_ready` で `if _sweep_task is None or _sweep_task.done(): _sweep_task = client.loop.create_task(_approval_sweep_loop())`

- **「module load 時に optional import」と表現修正** (architect L / contrarian M / migration L)
  - plan 本文の「lazy import」表現を「module load 時に optional import (失敗時は無効化)」に書き換え

- **「LLM executor vs より単純な代替」の比較表を plan に追加** (contrarian H4)
  - 案 A: 現案 (LLM executor + 事後検証)
  - 案 B: Discord に exact command を貼ってユーザー手動 create
  - 案 C: Google API OAuth を別途構築して直叩き
  - 案 D: Calendar.create を Phase 1 の対象外にする
  - 各案の pros/cons + 採用根拠

- **状態遷移表に approved → failed (sweep_stale_approved) 追記**

- **HERMES_HOME 決定の一本化** (architect H2)
  - config.py を「唯一の決定点」と明記。approval_handler は config.py の値を読み、env に setdefault するのではなく **subprocess env に明示的にコピー** する
  - lib/approvals.py / approvals_executor.py は env (`HERMES_HOME`, `HERMES_APPROVALS_DB`) を優先、未設定なら Path 自己導出 (ただし executor は systemd-run から env 経由で必ず受け取る前提)

### 棄却

- contrarian H3 (proposer LLM ジョブの判断余地):
  → proposer は CLAUDE.md の規約 (jobs/<name>/{prompt.md, job.env} の 2 ファイル構成) に従う必要があり、shell script に格下げすると hermes-lite のジョブ運用パターンから外れる。**Bash tool は disallowed-tools.txt に入っていないので allow される (CLAUDE.md の規約)** を plan に明記して採用しない。代わりに「prompt 内の Bash ブロックを 1 つだけ実行し、stdout をそのまま最終応答にする」を強制する文言で LLM の編集余地を抑える。

- contrarian H4 (より単純な代替案):
  → 比較表 (上) を plan に追加することで「根拠不足」指摘は fold。実際の採用判断は維持。

### round 5 戦略

- 上記を反映した v5 plan で再 dispatch
- 残った blocking が contrarian H1/H2 (= LLM executor 構造的制約) のみ、もしくは合計 3 件以下なら **裁量で残置** (max_design_loops=5 の制約に従う)
- それ以外の高頻度 blocking が残れば round 6 (= max_design_loops=5 到達) で「裁量で passed」とする (`stop_conditions.ask_user_on_blocking: false` のため自動裁量)

## Round 5 (design_loops=5) — 反映方針

blocking=9 (architect 2 + contrarian 3 + migration 4)。発散傾向だが、新規本質指摘あり。

### 採用 (plan v6 に反映)

- **feature flag default `0` (opt-in)** (migration H2)
  - `HERMES_APPROVAL_COMMANDS_ENABLED` の default を `"0"` に変更
  - 既存 Discord 会話の予約語衝突を default では起こさない
  - docs に「有効化手順: `HERMES_APPROVAL_COMMANDS_ENABLED=1` を bot 起動環境に追加」を明記
  - T01 / T02 / T03 / T07 等の手動テストは `HERMES_APPROVAL_COMMANDS_ENABLED=1` 前提で実施 (test-spec.md に明記)

- **flag off で import / regex / sweep をすべて skip** (migration H1)
  - bot.py の `_try_import_approval_handler()` を flag check の **後** に呼ぶ
  - 旧: module-load-time で常時 import
  - 新: `if APPROVAL_COMMANDS_ENABLED: _approval_handler = _try_import_approval_handler() else: _approval_handler = None`
  - `_APPROVAL_PATTERN` 初期化も同様
  - これで flag off では完全に未ロード (T25 で「approval_handler.py を rename しても bot 通常起動」を検証)

- **副作用後 fail を `failed_after_side_effect` status に分離** (migration H4)
  - `validate_payload` 失敗 / `invoke_claude_p` の `is_error` 等 (**副作用前** の失敗) → `failed`
  - tool_use_count != 1 / 別 tool / input mismatch (**副作用後検出**) → `failed_after_side_effect`
  - 状態遷移表に追加
  - `result_text` に htmlLink リストを JSON 形式で保存 (`{"side_effect_detected": true, "event_links": [...]}` を JSON 文字列として)
  - docs に「`failed_after_side_effect` は自動再試行不可。Calendar 側手動 cleanup 後に新規 ID で再起票」を明記
  - T16 / T22 の期待値を `failed_after_side_effect` に統一

- **approval_handler.handle() に user_id 引数 + 内部認可検証** (contrarian H3)
  - `handle(text, user_id) -> str`
  - 内部で `if user_id not in approvals.get_authorized_user_ids(): return "⚠️ [WARN] unauthorized"`
  - `approvals.get_authorized_user_ids()` は環境変数 `HERMES_APPROVAL_AUTHORIZED_USER_IDS` (カンマ区切り) を読む。fallback で空集合 (= 拒否)
  - DB に `decided_by INTEGER` 列を追加 (将来の audit 用、Phase 1 では記録のみで参照しない)
  - bot.py 側は `message.author.id` を渡す
  - T26_unauth_handler_call を追加

- **extract_tool_calls input 不可時は常に fail** (contrarian H2)
  - case 3 (`usage.tool_use_count` のみ) は実装上「name=unknown を count 回返す」のではなく **`extract_tool_calls()` が常に `None` を返す** に変更
  - `None` を返すと executor は「tool_use evidence unavailable」として常に `failed_after_side_effect` 経路 (Calendar 側 event は作られている可能性があるため WARN + 手動確認指示)
  - これにより「input 不可時は通る」矛盾を解消

- **run-claude.sh export の影響調査** (migration H3)
  - 調査結果を plan に記載:
    - 既存 jobs: `mail-watch`, `ping` (2 つだけ)
    - `grep -rn "HERMES_HOME"` 結果: `bin/run-claude.sh` と `gateway/discord/claude_runner.py` のみ
    - jobs の prompt.md / job.env では HERMES_HOME を別意味で使っていない
    - export 化の影響: subprocess (`claude -p`) に新たに HERMES_HOME 環境変数が見えるが、既存 jobs の prompt.md は HERMES_HOME を参照していないので無害
  - T17 を 2 つに分割: T17a (ping smoke), T17b (mail-watch smoke)

- **bot.py の import を一本化** (architect H2)
  - bot.py は **スクリプト実行** (gateway/discord/bot.py を直接 python3 で起動) 前提を維持
  - `from config import ...` / `import approval_handler` (relative なし) に統一
  - approval_handler.py 側も `from config import HERMES_HOME, APPROVALS_DB` (relative なし、sys.path に gateway/discord を入れる前提)
  - これで config モジュールの二重ロードを防ぐ

- **Bash tool 許可の挙動を bin/run-claude.sh のコードから具体例で plan に明記** (architect H1)
  - `bin/run-claude.sh:118` で `if [[ -n "${ALLOWED_TOOLS// /}" ]]; then` が false → `--allowed-tools` を渡さない → Claude デフォルト動作
  - disallowed-tools.txt には `Bash(rm *)`, `Bash(sudo *)`, `Bash(git push*)`, `Bash(git reset*)` のみで Bash 自体は禁止していない
  - 結果として ALLOWED_TOOLS="" の proposer は Bash を自由に使える
  - これを plan の「proposer job.env」セクションで具体的なコード参照付きで明示

- **CLI contract 表追加** (migration M)
  - 各サブコマンドの: stdout / stderr / exit code / JSON schema を表で定義

- **ID 衝突時の enqueue retry 仕様** (migration M)
  - `enqueue()`: PRIMARY KEY 衝突を最大 5 回までリトライ (`secrets.token_hex(4)` を毎回生成)
  - 6 回連続衝突は確率 ~ (1/2^32)^5 で天文学的に低いが、5 回超で RuntimeError + CLI exit 3 (= 衝突専用 exit code) を返す
  - T27_id_collision_retry を unittest に追加 (PRIMARY KEY を pre-insert で衝突させて確認)

- **executor_job 文字列重複の集約** (architect M)
  - `ALLOWED_EXECUTORS["calendar.create"]` を唯一のソースとする
  - approvals_executor.py 内では `EXECUTOR_JOB = ALLOWED_EXECUTORS["calendar.create"]` のように approvals.py からのみ参照
  - approval_handler.py 内でも同様 (systemd-run コマンドラインは「executor を 1 つ起動」する固定の責務なので、approval_handler が executor_job 文字列を持つ必要がない設計に変更)

- **MCP tool 名を定数化** (architect M)
  - `MCP_CREATE_EVENT = "mcp__claude_ai_Google_Calendar__create_event"` を `lib/approvals.py` で定義
  - executor / approval_handler から `from approvals import MCP_CREATE_EVENT` で参照
  - 別 MCP server / profile 対応は Out-of-Scope に明記

### 棄却

- contrarian H1 (LLM executor 自体が承認ゲートの中核価値を満たさない):
  → 比較表案 A の採用根拠 (MCP 直叩き不可 + Google API 直叩きは Phase 1 超過) を維持。発散ループを避けるため round 5 終了後は contrarian H1 単独残置でも裁量採用

- contrarian M (実装範囲が大きすぎる / 単純化):
  → ROADMAP Phase 1 のゴール (受信→カレンダー半自動登録) を満たすには本案の機能が最小。各機能 (sweep / list / feature flag / DB) はそれぞれ独立した責務で削れない

- contrarian L (feature flag off で予約語通過):
  → default off にすることで自動的に解消 (上記 migration H2 採用)

- architect M (config.py before/after):
  → config.py の現状は plan で参照済み (15 行未満)。実装 phase で teammate が必ず読む前提を明記

- architect M (HERMES_HOME 単一決定点と lib 側 fallback):
  → systemd-run で必ず env を渡すので bot 経由は 1 決定点。CLI 直叩き経路 (`python3 lib/approvals.py ...` を terminal で実行する場合のみ) の fallback は許容。test-spec.md の T13 に「bot 経由と CLI 経由で同一 inode」を明記済み

- migration M (schema mismatch 時の degradation):
  → docs に既に「approval 機能のみ無効化、通常応答は維持」を明記。テストは T19 で十分

- migration M (既存関数 before snippet 重複):
  → plan v4 でも before snippet を直接埋め込んでいる。v5 で `(上 v4 参照)` と省略したのを v6 で再度直接埋め込む

### Round 6 戦略 (max_design_loops=5 到達)

- v6 plan を書いて再 dispatch (= 5 回目の再 dispatch、design_loops=5)
- max_design_loops=5 到達後の指摘は `ask_user_on_blocking: false` のため**裁量で残置 → passed 遷移**
- 残った blocking は rejection.md に「裁量で残置」として転記、commit message に「Codex blocking N 件残置」を明記

## Round 6 (design_loops=5、max 到達) — 裁量採用

blocking=8 (architect 3 + contrarian 3 + migration 2)。design_loops=5 で `max_design_loops` に到達。`ask_user_on_blocking: false` のため自動裁量採用。

### plan v6 への最終追加 (1 行レベルの差分のみ)

- **migration H1 採用**: `get_authorized_user_ids()` は `HERMES_APPROVAL_AUTHORIZED_USER_IDS` 未設定時に `HERMES_APPROVAL_ALLOWED_USER_IDS_FALLBACK` (bot.py が ALLOWED_USER_IDS を export しておく) を fallback で使う。docs に「`HERMES_APPROVAL_AUTHORIZED_USER_IDS ⊆ ALLOWED_USER_IDS` を運用者が保つこと」を明記。
- **architect M (executor の is_error 後でも tool_use evidence をまず見る) + migration H2 採用**: executor の `is_error` 判定を tool_use evidence 検証の **後** に移動。`is_error || result.startswith("ERROR:")` かつ `create_calls 0 件` なら `side_effect=False`、`create_calls 1 件以上` なら `side_effect=True` で fail_during_executor。
- **architect H3 (承認者集合の包含関係)**: docs に「`HERMES_APPROVAL_AUTHORIZED_USER_IDS ⊆ ALLOWED_USER_IDS` を保つこと」を明記 (上の migration H1 と同じ docs 行で対処)。

### 裁量で残置する blocking (8 件中、上記反映後の残置)

- **contrarian H1 (LLM executor は承認ゲートの中核目的を満たさない)**: MCP 直叩き不可 + Google API 直叩きは Phase 1 超過 (比較表 C) の根拠を維持。Phase 1 では承認ゲート = 「自動書き込みの自動化 + 副作用後検出 + 手動 cleanup」と定義し、副作用前保証は将来 Issue (Google API OAuth) で実現する方針。
- **contrarian H2 (proposer を CLI に縮小)**: CLAUDE.md 規約 (jobs/<name>/{prompt.md, job.env}) との整合性のため Claude ジョブ形式を維持。proposer の prompt は「Bash ブロックを 1 度だけ実行」型で LLM 編集余地を最小化済み (実装フェーズで teammate が固定文を厳密に書く)。
- **contrarian H3 (executor 起動環境が run-claude.sh と分裂)**: executor は run-claude.sh とは別経路で `claude -p` を呼ぶ意図的な設計。`invoke_claude_p()` の CLI args contract は plan に固定済み (allowed/disallowed/timeout/model/max-budget)。MCP 設定はユーザー権限で `~/.claude/mcp.json` を共有する前提。
- **contrarian M (executor 自動テスト不足)**: `invoke_claude_p` / `notify_discord` を差し替える executor 自動テストを **実装フェーズで teammate に追加させる** (test-spec.md に T29_executor_unit_with_mock として書き込む)。
- **contrarian M (failed_after_side_effect の 0 回呼び出しケース)**: 上の architect M / migration H2 反映で「0 回 → side_effect=False で `failed`、1 回以上 → `failed_after_side_effect`」が明確化された (= 一部解消)。残りは `tool_use evidence 取得不能` 時の `failed_after_side_effect` 表記の docs での説明明確化のみ → docs に「`failed_after_side_effect` は『副作用が検出された』もしくは『tool evidence が取れず副作用が確認できない』」と書く (teammate 実装時)。
- **architect H1 (Calendar.create の許可経路と既存 disallowed-tools 設計の衝突)**: executor は `run-claude.sh` を **使わず** 直接 `claude -p` を呼ぶ。Non-Goal で「`bin/run-claude.sh` は touch するが export のみ」を維持しているのと混同しないよう、docs に「executor は `bin/run-claude.sh` 経路を使わず、`invoke_claude_p()` 内で直接 `claude -p` を起動する。disallowed-tools.txt は **executor が読み込んで `--disallowed-tools` 引数に展開する**」を明記する (teammate 実装時)。
- **architect H2 (HERMES_HOME 単一決定点が config.py と lib に分散)**: 共通モジュール化は後続 Issue で対応。MVP では config.py 経由 (bot 経路) と env 経由 (executor / CLI 経路) の 2 つの fallback で実用上同じ DB を指す (T13 で検証)。実装時に teammate が `lib/approvals.py` の Path 自己導出を `gateway/discord/config.py` と同一アルゴリズムにすることで実質統一する。
- **architect H3 / contrarian M (副作用後 status 名と CLI evidence 依存)**: 上の architect M 反映で 0 回呼び出し時は `failed` (副作用なし) に倒すよう改善。残りは「`failed_after_side_effect` は副作用 **の可能性** を示すもので確定ではない」を docs で説明する (teammate 実装時)。
- **architect M (flag off 完全互換テスト範囲)**: T25 に「flag off で `lib/approvals.py` も import されない、起動ログに approval 関連が一切出ない」を追加 (test-spec.md レベルの追記、teammate が行う)。
- **migration M (CLI exit 2 未使用)**: CLI contract 表から exit 2 列を削除、executor の exit 2 は別契約として docs に明記 (teammate 実装時)。
- **migration M (schema v2 export 手順)**: `list` CLI で十分代替可能 (`python3 lib/approvals.py list > backup.jsonl`)。docs にこの運用を追記 (teammate 実装時)。

### 結論

design_review を **passed (裁量採用)** に。残った blocking のうち実装フェーズで対処すべき項目は **debug-spec.md** に転記して teammate に渡す。commit message には「Codex design blocking 8 件残置 (裁量採用、詳細は features/3-discord-calendar-create/rejection.md)」と明記する。

contrarian の根本主張 (LLM executor は承認ゲートの中核目的を満たさない) は MCP / OAuth 制約上 Phase 1 では解消不能。これを許容するか、Calendar.create を後続 Issue に格下げするかは将来の判断。本 Issue では「副作用後検出付き LLM executor + 手動 cleanup」を Phase 1 のゴールとして採用 (比較表案 A 採用根拠)。

---

## Final Review (codex_loops=1, 2) — 裁量採用

実装後の Codex 最終レビュー 2 round 実施。両 round とも blocking=7 で発散も収束もしない。

### Round 1 → Round 2 で実装した修正

- approval_handler.py に `HERMES_EXECUTOR_*` / `CLAUDE_BIN` を systemd-run の setenv で透過的に渡す (contrarian H2 round 1 対応、12 行追加 commit `46c7a88`)

### 裁量で残置する blocking (round 2 時点 7 件)

1. **claude CLI v2.1.187 で tool_use evidence (name/input) が取れない** (architect H1 / contrarian H1 (critical) / migration H1)
   - 評価: 実測 (`claude-cli-tool-use-evidence.md`) で確認済みの構造的制約。`extract_tool_calls()` は実環境で常に `[]` を返し、executor は常に `failed_after_side_effect` に倒れる
   - 影響: 「承認 → Calendar event 作成成功 → row=executed」の正常系が実環境で到達不能。Calendar には event が作られるが DB は WARN ステータス、ユーザーは毎回 Discord 通知の event link を確認して手動 OK 判定する運用になる
   - 対応: Phase 1 では許容 (LLM executor の構造的制約、fail-closed 設計通り)。将来 Issue で `stream-json` 経路調査 + 切り替えを検討 (`features/3-discord-calendar-create/followups.md` 起票候補)

2. **bot.py の `HERMES_APPROVAL_ALLOWED_USER_IDS_FALLBACK` export が Codex の diff truncation で見えていない** (architect H2 round 1 / migration H2 round 1, 2)
   - 評価: 実装上は bot.py 48-54 行で `if APPROVAL_COMMANDS_ENABLED:` ブロック内で正しく実装済み (確認済み)。Codex は plan v6 snippet のみ参照しているか、diff truncation で見えなかった可能性
   - 対応: 実装は正しい。docs の説明とコードが一致している (実装時に確認済み)

3. **features/.batch/plan.json / .loop/state.json / .dashboard.md / codex-design-*.yaml の混入** (architect M / contrarian H3 / migration M)
   - 評価: これらは gloop loop / batch システムが自動更新するメタデータと、本 Issue の設計議論で生成された Codex review YAML。**gloop の運用設計上、各サイクルごとに更新されて自然にコミットされる**もの
   - 対応: 棄却。gloop の運用パターンに従う。後続サイクルでも同様の commit が続く

4. **contrarian H3 (split_proposal: 1 Issue 詰め込みすぎ)** (round 1)
   - 評価: `loop-split-detector.mjs` (v1.4 機能) が次サイクルで親 Issue に `blocked-by-split` 付与 + 子 Issue 起票する想定。本 Issue は **既に main にマージできる粒度** で実装完了している
   - 対応: 棄却。本 Issue は単一機能 (承認ゲート基盤) として完結。子 Issue 分割は将来必要なら別途

5. **contrarian H2 round 2 (proposer LLM ジョブの過剰さ)**
   - 評価: 設計議論 round 4-5 で議論済み。CLAUDE.md 規約 (jobs/<name>/{prompt.md, job.env}) に従う形式維持。LLM の判断余地は「Bash ブロック 1 つを実行するだけ」に最小化済み
   - 対応: 棄却。設計上の判断維持

6. **architect M round 2 (HERMES_HOME 分散)**
   - 評価: 設計議論 round 4 で議論済み。env 経由で全 entrypoint が同一 DB を指すことを T13 で検証する設計
   - 対応: 棄却

7. **architect M round 2 (flag off で config 追加の起動時影響)**
   - 評価: config.py の Path/env 追加は ~5 行で、副作用は env を読むだけ。bot 起動への実害なし
   - 対応: 棄却 (test-spec.md T25 で flag off 時の bot 通常起動を確認)

8. **contrarian M round 2 (failed_unverified に分離)**
   - 評価: 設計議論 round 5 で `failed_after_side_effect` 統一に決定済み。result_text に JSON で `side_effect_detected` / `reason` を保存する形で情報は残している
   - 対応: 棄却

### 結論 (final review)

`final_review` を **passed (裁量採用)** に。

- 実装は plan v6 通り (28 自動テスト全 pass、disallowed-tools.txt 不変、ping smoke OK、py_compile OK)
- 残った blocking は構造的制約 (claude CLI) と Codex の誤読 (bot.py FALLBACK 実装済みだが diff truncation で見えず) と gloop 運用上自然なファイル混入
- 実装フェーズで対処可能な指摘 (env forwarding) は round 1→2 の間に実装済み

commit message には以下を明記:
- 「Codex final blocking 7 件残置 (裁量採用、詳細は features/3-discord-calendar-create/rejection.md)」
- 「known limitation: claude CLI v2.1.187 では tool_use evidence が取れず、承認後の正常系は実環境で常に failed_after_side_effect に倒れる (fail-closed)。手動 cleanup 前提運用」

### 将来 Issue 起票候補 (followups)

- `stream-json` 経路による tool_use evidence 取得 + executor の正常系到達
- mail-watch (#2) → approval-proposer の自動橋渡し (本 Issue の利用想定)
- Notion update / Gmail send 等の write action への汎用化 (本 Issue の Calendar.create 限定スコープを拡張)
- Google Calendar API 直叩き executor (deterministic で副作用前保証、Phase 1 超過案)






