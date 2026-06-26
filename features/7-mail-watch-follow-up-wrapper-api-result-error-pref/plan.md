# plan: #7 mail-watch follow-up: wrapper API 整理（空 result 抑止 / ERROR: prefix の opt-in 化）

slug: mail-watch-follow-up-wrapper-api-result-error-pref
milestone: Phase 2
labels: type:chore
flow: light

## In-Scope / Out-of-Scope

| In-Scope | Out-of-Scope |
|---|---|
| `bin/run-claude.sh` に新変数 `SUPPRESS_EMPTY_RESULT` (既定 `"0"`) を追加。`"1"` のとき空 `RESULT_TEXT` で Discord 投稿スキップ | `(no result text)` 固定文字列の廃止（既定挙動は維持） |
| `bin/run-claude.sh` に新変数 `RESULT_ERROR_PREFIX` (既定 `"ERROR:"`) を追加。空文字で FAIL prefix 検出を無効化 | ERROR prefix の体系的リネーム。既定はそのまま `"ERROR:"` を維持 |
| `bin/run-claude.sh` の prefix 一致判定は **substring 比較 `[[ "${RESULT_TEXT:0:${#RESULT_ERROR_PREFIX}}" == "$RESULT_ERROR_PREFIX" ]]`** に変更（literal 保証を bash 仕様の挙動論理に依存させず明示） | `case` 置換などその他の判定構文変更 |
| stderr ログ文言 `FAIL via ERROR: prefix in result` を **維持**（既存 grep 互換）。カスタム prefix 利用時のみ末尾に `("$RESULT_ERROR_PREFIX")` を追記 | stderr 文言の全面書き換え |
| `docs/jobs-mail-watch.md` の「通知漏れ回復」説明を実態（Gmail 上の `hermes-lite/done` を手動確認）に書き換え | prompt 側で stderr に thread ID を出すような通知漏れ自動回復機能の実装 |
| `docs/wrapper-api.md`（新規）を作成し、`job.env` で **サポート対象として文書化する** 変数 10 個を一覧化 + 許容値仕様を明示。「公式 API として固定」ではなく「現時点でサポート対象」と表現 | wrapper 内部の job.env parser 書き換え / 公開変数の検証・正規化 |
| `bin/run-claude.sh` 先頭コメント (13-22 行) の上書き可能変数リストを `docs/wrapper-api.md` と同じ並びに同期 | `prompt.md` への wrapper 変数名露出（責務分離: prompt は出力契約のみ） |
| `features/.../test/` に **本体 `bin/run-claude.sh` を実際に実行する integration harness** を作る（stub claude binary + stub notify_discord で payload を観測） | wrapper を関数化して lib/ に切り出すリファクタ |

## Non-Goals

- **既存全 4 job (mail-watch / goals-nudge / approval-demo-proposer / interview-mail-proposer) + ping の挙動を一切変えない**（後方互換 100%）
- `jobs/mail-watch/job.env` の更新は **本 Issue では行わない**。docs/wrapper-api.md に「mail-watch で SUPPRESS_EMPTY_RESULT=1 を opt-in する際の手順例」を載せるだけにとどめる
  - 理由: contrarian 指摘 2「空 result が malformed success を無通知化する懸念」が、mail-watch 利用ケースに対する適用根拠調査（空 result が正常 NOOP 経路でも発生するか、Claude パース失敗ケースの発生頻度）を必要としており、wrapper API の追加とは分離して検証すべき。本 Issue は wrapper API 整備に集中し、mail-watch 適用は別 Issue で扱う
- `notify_discord` 関数（`lib/notify.sh`）の API 変更
- 通知本文の再送 / 自動リトライ機構
- prompt 側の thread ID stderr 出力
- `jobs/<name>/prompt.md` への wrapper 変数追記
- 既存 stderr ログ文言の互換性破壊（grep 互換維持）

## 設計方針

### なぜ wrapper API 整備が必要か

Issue #7 本文が「wrapper API として整理する価値あり」と明示。現状 `bin/run-claude.sh` は `ERROR:*` 判定を 4 job (mail-watch / goals-nudge / approval-demo-proposer / interview-mail-proposer) で **既に共通プロトコル化**（grep 確認済み）しており、job が「業務本文として `ERROR:` を返したい」「空 result を投稿したくない」と要求するたびに wrapper を直す状況。API 整備の追加コストは「変数 2 つ + docs 1 ファイル」と最小で、長期保守上の収益が大きい。

contrarian の「過剰設計」指摘に対する弱化対応: docs/wrapper-api.md は「**公式 API として固定**」ではなく「**現時点でサポート対象として文書化**」という表現に弱める。実装上 `source "$JOB_ENV"` で任意変数が流入する性質は変えず、内部変数と公開変数を docs 上で区別するだけにとどめる。

### 後方互換を最優先（既定値運用）

新変数 2 つはどちらも **既定値で動く既存挙動と完全一致**:

- `SUPPRESS_EMPTY_RESULT="0"` (既定): 空 result でも `(no result text)` を投稿する従来挙動
- `RESULT_ERROR_PREFIX="ERROR:"` (既定): 現状の `RESULT_TEXT == ERROR:*` 判定を維持

**既存全 4 job + ping の job.env を一切変更しない**ので、Discord 通知 payload・stderr ログ文言・exit code は完全一致。

### 既存 stderr 文言の grep 互換維持

`grep -rn 'FAIL via ERROR' .` の repo 内ヒットを確認した結果: **`bin/run-claude.sh` 内の自己参照 1 件のみ**で、他コード・テスト・docs から参照されていない（前提調査済み）。したがって文言変更しても運用影響は無いが、本 Issue では将来の保険として既定文言 `FAIL via ERROR: prefix in result` を **維持**する。

カスタム prefix 利用時のみ末尾に prefix 値を `printf %q` で shell-safe quote した形で併記:

```
FAIL via ERROR: prefix in result (<printf %q した値>)
```

例: `RESULT_ERROR_PREFIX='[ERR]'` の場合は `FAIL via ERROR: prefix in result (\[ERR\])` のように bash quote 形式で出る。これで prefix に `"`, 改行, 制御文字を含めても stderr ログが壊れず、既定挙動の grep `FAIL via ERROR:` は引き続きヒットする。

### prefix 判定の literal 保証（substring 比較）

bash の `[[ "$str" == "$pat"* ]]` は quoted 変数を literal 扱いするが、これは bash 仕様の挙動論理に依存する。実機検証コストを避け、より明示的な substring 比較に切り替える:

```bash
if [[ -n "$RESULT_ERROR_PREFIX" \
    && "${RESULT_TEXT:0:${#RESULT_ERROR_PREFIX}}" == "$RESULT_ERROR_PREFIX" ]]; then
  _starts_with_error_prefix=1
fi
```

`${str:0:N}` で先頭 N 文字を切り出し、prefix と完全文字列比較する。glob メタ文字も literal として扱われる（pattern matching ではなく純粋な文字列比較）。

### ERR_SNIPPET データフローの分離

FAIL 経路で Discord 通知本文に `RESULT_TEXT` を入れる判定は、prefix 由来の昇格時 (`_starts_with_error_prefix`) **か、または旧来通り `RESULT_TEXT` が `ERROR:` で始まる時** に使う。後者を残すことで、`RESULT_ERROR_PREFIX=""` でも prefix=`ERROR:` 由来の従来 `RESULT_TEXT` 採用が維持され、prefix 無効化と通知データフローが独立する:

```bash
if [[ "$_starts_with_error_prefix" -eq 1 || "$RESULT_TEXT" == ERROR:* ]]; then
  ERR_SNIPPET="$RESULT_TEXT"
elif [[ -s "$ERR_LOG" ]]; then
  ERR_SNIPPET=$(tail -c 500 "$ERR_LOG")
fi
```

### CLAUDE_BIN / HERMES_HOME の境界整理

`CLAUDE_BIN` と `HERMES_HOME` は **「プロセス環境からサポートする実行制御変数」** として docs/wrapper-api.md に独立セクションで明記する。「job.env でサポートする設定変数 (10 個)」とは別カテゴリ:

- `job.env でサポートする変数`: 10 個（上記）
- `プロセス環境変数からサポートする実行制御変数`: `CLAUDE_BIN`, `HERMES_HOME`, `DISCORD_WEBHOOK_URL`
- `内部実装変数`: `JOB_NAME`, `LOG_DIR`, `RESULT_TEXT`, `COST_USD`, `EXIT_CODE` ほか

これで harness が `CLAUDE_BIN=stub` を使う設計と docs の境界が整合する。

### 変数仕様（サポート対象として文書化）

| 変数 | 既定 | 真値判定 | 不正値扱い | 備考 |
|---|---|---|---|---|
| `SUPPRESS_EMPTY_RESULT` | `"0"` | `"1"` のみ true | `"0"` `""` `"2"` `"yes"` `"true"` 等すべて false（silent） | 空 result + 正常終了でのみ動作 |
| `RESULT_ERROR_PREFIX` | `"ERROR:"` | 空文字 = 検出無効化、それ以外 = literal prefix | 値内の `[` `*` `?` 等は literal 扱い（引用変数の bash 仕様）。**先頭・末尾空白も literal**（quote 必須） | `RESULT_ERROR_PREFIX=" ERROR:"` は半角スペース込みで一致判定する |

不正値扱いは silent false（warn 出力しない）。これは bash の慣習に合わせる選択。docs に明記する。

### `RESULT_ERROR_PREFIX=""` の適用条件

これを使う前に prompt 側で `ERROR:` を fail シグナルとして使っていないことを確認する必要がある（既存 4 job はすべて `ERROR:` を fail シグナルとして使っているので、これら job に `RESULT_ERROR_PREFIX=""` を設定するのは禁止）。docs/wrapper-api.md に適用条件を明記。

### docs/wrapper-api.md の対象変数（job.env サポート: 既存 8 + 新 2 = 10）

`bin/run-claude.sh` 13-22 行のヘッダーコメントと一致させる:

1. `ALLOWED_TOOLS`
2. `MAX_TURNS`
3. `TIMEOUT_SEC`
4. `MAX_BUDGET_USD`
5. `MODEL`
6. `NOTIFY_RESULT`
7. `NOTIFY_ON_ERROR`
8. `SUPPRESS_RESULT_IF`
9. **`SUPPRESS_EMPTY_RESULT`** (新規)
10. **`RESULT_ERROR_PREFIX`** (新規)

「これ以外の `bin/run-claude.sh` 内変数 (`JOB_NAME`, `LOG_DIR`, `RESULT_TEXT` ほか) は内部実装。job.env で上書きできても **未定義動作**」と docs に明記。

### Integration harness 設計（本体を実行する形）

3 persona の共通 high 指摘（harness が本体を実行しないと退行検出にならない）を受けて、`features/.../test/` 配下に **`bin/run-claude.sh` を実際に実行する harness** を作る。構造:

```
features/7-mail-watch-follow-up-wrapper-api-result-error-pref/test/
  run-harness.sh         # メインエントリ。各 T-ID を順に実行 → 結果集約
  fixtures/
    hermes-home/         # HERMES_HOME として与える隔離 dir
      .env               # DISCORD_WEBHOOK_URL=https://stub.invalid（実際には呼ばれない）
      bin/run-claude.sh  # symlink → ../../../../../bin/run-claude.sh（本体）
      lib/
        notify.sh        # **stub 版**。notify_discord は payload を $STUB_DISCORD_LOG に append
        disallowed-tools.txt  # symlink → ../../../../../lib/disallowed-tools.txt
      jobs/
        t02-empty/       # 空 result を返す
          prompt.md
          job.env        # SUPPRESS_EMPTY_RESULT=1
        t03-empty-default/
          prompt.md
          job.env        # SUPPRESS_EMPTY_RESULT 未設定
        t04-error-default/
          prompt.md
          job.env        # 何もカスタムしない
        t05-error-disabled/
          prompt.md
          job.env        # RESULT_ERROR_PREFIX=""
        t06-error-custom/
          prompt.md
          job.env        # RESULT_ERROR_PREFIX="[ERR]"
        t09-suppress-bad-value/
          prompt.md
          job.env        # SUPPRESS_EMPTY_RESULT="2"（不正値は silent false）
    stub-claude.sh       # CLAUDE_BIN 用 stub。引数 -p の中身から fixture を返す
```

harness 実行手順:

1. `STUB_DIR=$(mktemp -d)` で隔離された一時ディレクトリを作成、`trap "rm -rf $STUB_DIR" EXIT` で cleanup を保証
2. `STUB_DISCORD_LOG="$STUB_DIR/discord.log"`、`STUB_CLAUDE_JOB_FILE="$STUB_DIR/current-job"` を export
3. 各 T-ID ループの先頭で `echo "$T_ID" > "$STUB_CLAUDE_JOB_FILE"`
4. `CLAUDE_BIN=$FIXTURES/stub-claude.sh HERMES_HOME=$FIXTURES/hermes-home STUB_CLAUDE_JOB_FILE=$STUB_CLAUDE_JOB_FILE STUB_DISCORD_LOG=$STUB_DISCORD_LOG` で本体 `bin/run-claude.sh <t-id>` を起動
5. stderr を `$STUB_DIR/<t-id>.stderr` に保存
6. 期待値検証:
   - stderr の特定文字列を `grep -F`
   - `$STUB_DISCORD_LOG` の有無 / 内容を `diff` で文字列比較

`stub-claude.sh` は環境変数 `STUB_CLAUDE_JOB_FILE` でジョブ名を受け取って固定 JSON を返す:

```bash
#!/usr/bin/env bash
# stub-claude.sh — 本物の claude の代わりに、env 経由の job 名に応じた固定 JSON response を返す
JOB_ID=$(cat "${STUB_CLAUDE_JOB_FILE:-/dev/null}" 2>/dev/null || echo unknown)
case "$JOB_ID" in
  t02-empty|t03-empty-default|t09-suppress-bad-value) RESULT='' ;;
  t04-error-default|t05-error-disabled) RESULT='ERROR: stub fail' ;;
  t06-error-custom) RESULT='[ERR] stub fail' ;;
  *) RESULT='ok' ;;
esac
jq -n --arg r "$RESULT" \
  '{type:"result", result:$r, total_cost_usd:0, usage:{input_tokens:0,output_tokens:0}, is_error:false}'
```

prompt 内容の parsing は使わない（architect 指摘 6）。env 経由・mktemp 配下に閉じた side channel で並列実行・残骸衝突を防ぐ（architect/contrarian/migration medium 指摘）。

注: stub の `notify.sh` は **同名関数 `notify_discord` を上書き定義**し、message を `$STUB_DISCORD_LOG` に echo するだけ。本体 wrapper の `source "$HERMES_HOME/lib/notify.sh"` 時に stub 版が読まれる。

drift mitigation: harness 実行手順は `features/.../test/README.md` にも明記し、`bin/run-claude.sh` を変更したら harness を再実行する規律を README に書く。

## 実装対象

### 1. `bin/run-claude.sh`

#### 1-A. ヘッダーコメント (13-22 行) — 2 行追加

before:

```bash
# job.env で上書きできる変数:
#   ALLOWED_TOOLS    ... 空白区切り。disallowed と被ったらこちらが優先（claude CLI 仕様）
#   MAX_TURNS        ... 既定 DEFAULT_MAX_TURNS
#   TIMEOUT_SEC      ... 既定 DEFAULT_TIMEOUT_SEC
#   MAX_BUDGET_USD   ... 既定 DEFAULT_MAX_BUDGET_USD（Max サブスク利用時は実害なし、保険）
#   MODEL            ... 既定 DEFAULT_MODEL
#   NOTIFY_RESULT    ... 1 にすると正常終了時に result を Discord 投稿
#   NOTIFY_ON_ERROR  ... 1 にすると失敗時に概要を Discord 投稿（既定 1）
#   SUPPRESS_RESULT_IF ... 最終応答が完全一致したら Discord 投稿をスキップ（opt-in）
```

after:

```bash
# job.env で上書きできる変数（詳細仕様は docs/wrapper-api.md 参照）:
#   ALLOWED_TOOLS         ... 空白区切り。disallowed と被ったらこちらが優先（claude CLI 仕様）
#   MAX_TURNS             ... 既定 DEFAULT_MAX_TURNS
#   TIMEOUT_SEC           ... 既定 DEFAULT_TIMEOUT_SEC
#   MAX_BUDGET_USD        ... 既定 DEFAULT_MAX_BUDGET_USD（Max サブスク利用時は実害なし、保険）
#   MODEL                 ... 既定 DEFAULT_MODEL
#   NOTIFY_RESULT         ... 1 にすると正常終了時に result を Discord 投稿
#   NOTIFY_ON_ERROR       ... 1 にすると失敗時に概要を Discord 投稿（既定 1）
#   SUPPRESS_RESULT_IF    ... 最終応答が完全一致したら Discord 投稿をスキップ（opt-in）
#   SUPPRESS_EMPTY_RESULT ... 1 にすると空 result の "(no result text)" 投稿もスキップ（既定 0）
#   RESULT_ERROR_PREFIX   ... RESULT_TEXT がこの prefix で始まる場合 FAIL 経路扱い（既定 "ERROR:"、空で無効化）
```

#### 1-B. デフォルト宣言 (72 行付近) — 2 変数追加

before:

```bash
# 最終応答が完全一致したら Discord 投稿をスキップしたいジョブ向け（opt-in）。
# 例: mail-watch は 0 件時に "[NOOP]" を返すので、job.env で SUPPRESS_RESULT_IF="[NOOP]" を設定する。
SUPPRESS_RESULT_IF=""

if [[ -f "$JOB_ENV" ]]; then
```

after:

```bash
# 最終応答が完全一致したら Discord 投稿をスキップしたいジョブ向け（opt-in）。
# 例: mail-watch は 0 件時に "[NOOP]" を返すので、job.env で SUPPRESS_RESULT_IF="[NOOP]" を設定する。
SUPPRESS_RESULT_IF=""

# 空 RESULT_TEXT のときの "(no result text)" 投稿を抑止するか。"1" のみ true（opt-in）。
SUPPRESS_EMPTY_RESULT="0"

# RESULT_TEXT がこの prefix で始まる場合に FAIL 経路扱いとする。
# 既定 "ERROR:" は 4 job (mail-watch / goals-nudge / approval-demo-proposer / interview-mail-proposer) の既存契約。
# 空文字に設定すれば検出を無効化できる。値内の [, *, ? 等のメタ文字は literal 扱い。
RESULT_ERROR_PREFIX="ERROR:"

if [[ -f "$JOB_ENV" ]]; then
```

#### 1-C. 通知分岐 (155-183 行) — 完全 before/after

before (全文):

```bash
# --- 通知 ---
# RESULT_TEXT が "ERROR:" で始まる場合は claude プロセス自体は正常終了でも
# 失敗扱いにする (例: prompt 側の fail-fast でラベル不在等)。
if [[ "$EXIT_CODE" -eq 0 && "$IS_ERROR" != "true" && "$RESULT_TEXT" != ERROR:* ]]; then
  echo "[run-claude] OK exit=0 cost=${COST_USD:-?} in=${INPUT_TOKENS:-?} out=${OUTPUT_TOKENS:-?}" >&2
  if [[ "$NOTIFY_RESULT" == "1" ]]; then
    if [[ -n "${SUPPRESS_RESULT_IF:-}" && "$RESULT_TEXT" == "$SUPPRESS_RESULT_IF" ]]; then
      echo "[run-claude] result matched SUPPRESS_RESULT_IF — skipping Discord post" >&2
    elif [[ -z "$RESULT_TEXT" ]]; then
      notify_discord "[$JOB_NAME] (no result text)"
    else
      notify_discord "[$JOB_NAME] $RESULT_TEXT"
    fi
  fi
else
  if [[ "$RESULT_TEXT" == ERROR:* && "$EXIT_CODE" -eq 0 && "$IS_ERROR" != "true" ]]; then
    echo "[run-claude] FAIL via ERROR: prefix in result" >&2
  else
    echo "[run-claude] FAIL exit=$EXIT_CODE is_error=${IS_ERROR:-?}" >&2
  fi
  if [[ "$NOTIFY_ON_ERROR" == "1" ]]; then
    ERR_SNIPPET=""
    if [[ "$RESULT_TEXT" == ERROR:* ]]; then
      ERR_SNIPPET="$RESULT_TEXT"
    elif [[ -s "$ERR_LOG" ]]; then
      ERR_SNIPPET=$(tail -c 500 "$ERR_LOG")
    fi
    notify_discord "[$JOB_NAME] FAIL exit=$EXIT_CODE\n\`\`\`\n${ERR_SNIPPET:-(no stderr)}\n\`\`\`"
  fi
fi
```

after (全文):

```bash
# --- 通知 ---
# RESULT_TEXT が RESULT_ERROR_PREFIX で始まる場合は claude プロセス自体は正常終了でも
# 失敗扱いにする (例: prompt 側の fail-fast でラベル不在等)。
# RESULT_ERROR_PREFIX が空のときはこの判定を無効化する。
# substring 比較で literal 一致を保証（pattern matching に依存しない）。
_starts_with_error_prefix=0
if [[ -n "$RESULT_ERROR_PREFIX" \
    && "${RESULT_TEXT:0:${#RESULT_ERROR_PREFIX}}" == "$RESULT_ERROR_PREFIX" ]]; then
  _starts_with_error_prefix=1
fi

if [[ "$EXIT_CODE" -eq 0 && "$IS_ERROR" != "true" && "$_starts_with_error_prefix" -eq 0 ]]; then
  echo "[run-claude] OK exit=0 cost=${COST_USD:-?} in=${INPUT_TOKENS:-?} out=${OUTPUT_TOKENS:-?}" >&2
  if [[ "$NOTIFY_RESULT" == "1" ]]; then
    if [[ -n "${SUPPRESS_RESULT_IF:-}" && "$RESULT_TEXT" == "$SUPPRESS_RESULT_IF" ]]; then
      echo "[run-claude] result matched SUPPRESS_RESULT_IF — skipping Discord post" >&2
    elif [[ -z "$RESULT_TEXT" && "$SUPPRESS_EMPTY_RESULT" == "1" ]]; then
      echo "[run-claude] empty result + SUPPRESS_EMPTY_RESULT=1 — skipping Discord post" >&2
    elif [[ -z "$RESULT_TEXT" ]]; then
      notify_discord "[$JOB_NAME] (no result text)"
    else
      notify_discord "[$JOB_NAME] $RESULT_TEXT"
    fi
  fi
else
  if [[ "$_starts_with_error_prefix" -eq 1 && "$EXIT_CODE" -eq 0 && "$IS_ERROR" != "true" ]]; then
    if [[ "$RESULT_ERROR_PREFIX" == "ERROR:" ]]; then
      echo "[run-claude] FAIL via ERROR: prefix in result" >&2
    else
      printf '[run-claude] FAIL via ERROR: prefix in result (%q)\n' "$RESULT_ERROR_PREFIX" >&2
    fi
  else
    echo "[run-claude] FAIL exit=$EXIT_CODE is_error=${IS_ERROR:-?}" >&2
  fi
  if [[ "$NOTIFY_ON_ERROR" == "1" ]]; then
    ERR_SNIPPET=""
    # 旧来 ERROR: prefix 互換: prefix を無効化していても RESULT_TEXT を採用する（データフロー分離）
    if [[ "$_starts_with_error_prefix" -eq 1 || "$RESULT_TEXT" == ERROR:* ]]; then
      ERR_SNIPPET="$RESULT_TEXT"
    elif [[ -s "$ERR_LOG" ]]; then
      ERR_SNIPPET=$(tail -c 500 "$ERR_LOG")
    fi
    notify_discord "[$JOB_NAME] FAIL exit=$EXIT_CODE\n\`\`\`\n${ERR_SNIPPET:-(no stderr)}\n\`\`\`"
  fi
fi
```

**Discord 投稿 payload 互換性表**:

| シナリオ | before payload | after payload | 互換 |
|---|---|---|---|
| OK + 通常本文 | `[<job>] <text>` | 同一 | ✅ |
| OK + SUPPRESS_RESULT_IF 一致 | (投稿なし) | 同一 | ✅ |
| OK + 空 result + 既定 (SUPPRESS_EMPTY_RESULT=0) | `[<job>] (no result text)` | 同一 | ✅ |
| OK + 空 result + opt-in (SUPPRESS_EMPTY_RESULT=1) | `[<job>] (no result text)` | (投稿なし) | ⚠️ opt-in 時のみ |
| FAIL via ERROR: prefix (既定) | `[<job>] FAIL exit=0\n\`\`\`\nERROR: ...\n\`\`\`` | 同一 | ✅ |
| FAIL via custom prefix ([ERR]) | (該当なし) | `[<job>] FAIL exit=0\n\`\`\`\n[ERR] ...\n\`\`\`` | ✅ 新規 |
| RESULT_ERROR_PREFIX="" + ERROR: 本文 | (FAIL 通知) | OK 経路として `[<job>] ERROR: ...` | ⚠️ opt-out 時のみ |
| FAIL via exit != 0 / is_error=true | `[<job>] FAIL exit=N\n\`\`\`\n<stderr tail>\n\`\`\`` | 同一 | ✅ |

stderr ログ文言:

| シナリオ | before stderr | after stderr |
|---|---|---|
| FAIL via 既定 ERROR: prefix | `[run-claude] FAIL via ERROR: prefix in result` | 同一（grep 互換維持） |
| FAIL via custom prefix [ERR] | (該当なし) | `[run-claude] FAIL via ERROR: prefix in result (\[ERR\])`（`printf %q` 出力） |

**既存全 4 job + ping の job.env を変更しないので、運用環境では before == after**。

### 2. `docs/jobs-mail-watch.md` 修正

- 122-127 行 "順序とトレードオフ" の `.result や stderr で発見可能。Gmail 側で hermes-lite/done を hermes-lite に戻せば次サイクルで再通知できる` を以下に書き換え:

  > **ラベル変更後・通知前にプロセスが死ぬ → 通知漏れ**。最終応答返却前に死んだ場合は `.result` にも残らないため、ログからの自動検知は不可。発見方法: Gmail 上で `hermes-lite/done` に新規付与された thread が前回起動以降に増えていないか確認する。再通知したい場合は Gmail 上で当該 thread のラベルを `hermes-lite/done` → `hermes-lite` (未読化) に戻すと次サイクルで拾われる。

- トラブルシュート表に 1 行追加:

  | 症状 | 確認 |
  |---|---|
  | `hermes-lite/done` には付いているのに Discord に通知が来ていない | ラベル変更後・通知前にプロセスが死んだ可能性。Gmail 上で該当 thread を `hermes-lite` ラベルに戻すと次サイクルで再通知される |

### 3. `docs/wrapper-api.md` (新規)

セクション構成:

1. **概要** — `bin/run-claude.sh` が `claude -p` を無人で安全に呼ぶラッパー。job.env を「現時点でサポート対象の」設定インターフェースとして文書化する旨。「公式 API として固定」ではなく「現状サポート対象」表現
2. **サポート対象変数（10 個）** — 表（変数名 / 既定値 / 説明 / 設定例 / 真値判定 / 不正値扱い）
3. **`RESULT_ERROR_PREFIX="" の適用条件`** — prompt 側で ERROR prefix を fail シグナルとして使っていないこと。既存 4 job はすべて該当するので無効化禁止
4. **`SUPPRESS_EMPTY_RESULT=1` の opt-in 例（mail-watch ケース）** — 設定手順 + ロールバック手順 (`SUPPRESS_EMPTY_RESULT=0` に戻すか job.env から行を削除) + 空 result の痕跡確認先 (`logs/<job>/<ts>.json` の `.result` と `cost.csv`) + 期待される stderr 文言 (`empty result + SUPPRESS_EMPTY_RESULT=1 — skipping Discord post`)。**実適用は本 Issue では行わない旨も注記**
5. **内部変数 vs 公開変数** — `JOB_NAME`, `LOG_DIR`, `RESULT_TEXT`, `COST_USD`, `INPUT_TOKENS`, `OUTPUT_TOKENS`, `IS_ERROR`, `CLAUDE_BIN`, `EXIT_CODE` 等は内部実装。job.env で上書きできても未定義動作
6. **harness を本体と同期して更新する規律** — `bin/run-claude.sh` を変更したら `features/.../test/run-harness.sh` も再実行・必要なら追従 (drift mitigation)

## テスト計画（手動チェックリスト / project_type=jobs）

light flow だが、Codex 共通指摘を受けて T02-T06 + T09 を **integration harness で実実行** に格上げする。

| ID | 内容 | 実装方法 | 期待値 | 実行 |
|---|---|---|---|---|
| T01_default_compat | harness で `t01-default-compat` (空ではない fixture `ok` を返す、job.env で `NOTIFY_RESULT=1` のみ設定) を実行 | integration harness | stderr に `OK exit=0`。`$STUB_DISCORD_LOG` に `[t01-default-compat] ok` の 1 行（既存挙動の文字列比較） | 実実行 |
| T02_empty_suppress | harness で `t02-empty` (job.env で `SUPPRESS_EMPTY_RESULT=1`、空 result fixture) を実行 | integration harness | stderr に `empty result + SUPPRESS_EMPTY_RESULT=1 — skipping Discord post`。`$STUB_DISCORD_LOG` 空 | 実実行 |
| T03_empty_default | harness で `t03-empty-default` (空 result fixture、`SUPPRESS_EMPTY_RESULT` 未設定) | integration harness | `$STUB_DISCORD_LOG` に `[t03-empty-default] (no result text)` が **1 行ある** | 実実行 |
| T04_error_default | harness で `t04-error-default` (`ERROR: stub fail` fixture、`RESULT_ERROR_PREFIX` 未設定) | integration harness | stderr に `FAIL via ERROR: prefix in result` (末尾 `(...)` なし)。`$STUB_DISCORD_LOG` に FAIL payload | 実実行 |
| T05_error_disabled | harness で `t05-error-disabled` (`ERROR: stub fail` fixture、`RESULT_ERROR_PREFIX=""`) | integration harness | stderr に `OK exit=0`。`$STUB_DISCORD_LOG` に `[t05-error-disabled] ERROR: stub fail` | 実実行 |
| T06_error_custom_prefix | harness で `t06-error-custom` (`[ERR] stub fail` fixture、`RESULT_ERROR_PREFIX="[ERR]"`) | integration harness | stderr に `FAIL via ERROR: prefix in result (` を含む（`printf %q` 出力で prefix 値が `\[ERR\]` のように shell-safe quote される）。`$STUB_DISCORD_LOG` に FAIL payload (`[ERR] stub fail` 含む) | 実実行 |
| T07_mail_watch_dryrun | `jobs/mail-watch/` を変更しないことを確認 | `git diff main -- jobs/mail-watch/` | 差分なし | 実実行 |
| T08_docs_review | `docs/jobs-mail-watch.md` と `docs/wrapper-api.md` を git diff で目視 | `git diff main -- docs/` + grep | 「ログから回復」記述が消えている／wrapper-api.md に 10 変数が記載（grep で各変数名検出） | 実実行 |
| T09_suppress_bad_value | harness で `t09-suppress-bad-value` (空 result fixture、`SUPPRESS_EMPTY_RESULT="2"`) | integration harness | `"2"` は不正値 → silent false。`$STUB_DISCORD_LOG` に `[t09-suppress-bad-value] (no result text)` が来る | 実実行 |
| T10_grep_compat | 既存 grep 文字列と新変数の既存衝突確認 | (1) `grep -rn 'FAIL via ERROR' --include='*.md' --include='*.sh' --include='*.py' --include='*.mjs' --include='*.js' .` で `bin/run-claude.sh` 以外（`docs/` `features/` を除く）のヒット 0 件、 (2) `grep -rE '^(SUPPRESS_EMPTY_RESULT\|RESULT_ERROR_PREFIX)=' jobs/ features/` で既存設定との衝突 0 件（本 Issue で追加した `features/7-.../` 配下を除く） | (1)(2) ともに 0 件 | 実実行 |

「dry-run」項目は無し（Codex 共通指摘への対応）。

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| `RESULT_ERROR_PREFIX=""` 利用時に prompt 側の `ERROR:` fail シグナルが silent OK 化する | docs/wrapper-api.md に適用条件を明記。既存 4 job では使用禁止と注記 |
| 不正値 (`SUPPRESS_EMPTY_RESULT="2"` 等) が silent false で気付かれない | docs に「`"1"` のみ true」と明記。T09 で動作確認 |
| harness 実装が `bin/run-claude.sh` 本体と drift する | harness は symlink + stub override 構成で本体ロジックを実走する設計。`docs/wrapper-api.md` 末尾と `features/.../test/README.md` に「本体変更時は harness 再実行必須」を明記 |
| 既存 stderr 文言 grep が外部から参照されている可能性 | T10 で repo 内参照確認 + 既定文言維持で外部影響なし |
| カスタム prefix 利用時の stderr 末尾追記 `("$RESULT_ERROR_PREFIX")` が、prefix に `"` を含む値で quote 壊れする | docs/wrapper-api.md に「prefix に `"` を含めないこと」と注記。T06 では `[ERR]` だけ実証 |

## 関連ファイル

- `bin/run-claude.sh` — 主実装
- `docs/jobs-mail-watch.md` — 回復説明書き換え
- `docs/wrapper-api.md` — 新規（変数 10 個一覧 + harness 同期規律）
- `features/7-.../test/` — integration harness（本体実行型）
- `features/2-email-gateway-gmail-discord/` — 元 Issue #2 (Codex 最終レビューの指摘元)
