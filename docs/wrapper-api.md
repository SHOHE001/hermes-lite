# wrapper API: `bin/run-claude.sh` の設定インターフェース

`bin/run-claude.sh` は `claude -p` を「無人」で安全に呼ぶための共通ラッパー。各 job は `jobs/<name>/job.env` で wrapper の挙動を上書きする。

このドキュメントは、`job.env` で **現時点でサポート対象として文書化する** 変数の仕様と、wrapper が `CLAUDE_BIN` などのプロセス環境変数経由でサポートする実行制御変数、および内部実装変数の境界を示す。

**注意**: 「公式 API として固定」ではなく「現時点でサポート対象として文書化」している。`source "$JOB_ENV"` は任意の変数を持ち込めるが、ここに列挙していない変数は内部実装か未定義動作扱いとなる。

---

## 1. 概要

| 種別 | スコープ | 例 |
|---|---|---|
| job.env サポート対象変数 | 各 job の挙動カスタマイズ | `MAX_TURNS`, `NOTIFY_RESULT`, `SUPPRESS_EMPTY_RESULT` |
| プロセス環境からの実行制御変数 | harness / テスト / 環境差吸収 | `CLAUDE_BIN`, `HERMES_HOME`, `DISCORD_WEBHOOK_URL` |
| 内部実装変数 | wrapper 内部処理 | `JOB_NAME`, `RESULT_TEXT`, `EXIT_CODE` |

---

## 2. job.env サポート対象変数（10 個）

| 変数 | 既定値 | 説明 | 設定例 | 真値判定 | 不正値扱い |
|---|---|---|---|---|---|
| `ALLOWED_TOOLS` | `""` | 空白区切りの allowed-tools リスト（`disallowed-tools.txt` と被ったらこちらが優先） | `ALLOWED_TOOLS="WebSearch WebFetch"` | 非空かつ非空白 | 空文字は「許可リスト指定なし」（既定挙動） |
| `MAX_TURNS` | `$DEFAULT_MAX_TURNS` (`.env`) | claude のマックスターン数（暴走防止） | `MAX_TURNS="5"` | 整数文字列 | 非整数は `claude -p` 側でエラー化 |
| `TIMEOUT_SEC` | `$DEFAULT_TIMEOUT_SEC` (`.env`) | `timeout` コマンドに渡す秒数 | `TIMEOUT_SEC="180"` | 整数文字列 | 非整数は `timeout` 側でエラー化 |
| `MAX_BUDGET_USD` | `$DEFAULT_MAX_BUDGET_USD` (`.env`) | `--max-budget-usd` 引数（Max サブスクでは保険） | `MAX_BUDGET_USD="0.50"` | 数値文字列 | `claude -p` 側で判定 |
| `MODEL` | `$DEFAULT_MODEL` (`.env`) | `--model` 引数 | `MODEL="sonnet"` | `sonnet` / `opus` / `haiku` / `fable` 等 | 不明な値は `claude -p` 側でエラー化 |
| `NOTIFY_RESULT` | `"0"` | 正常終了時の result を Discord に投稿するか | `NOTIFY_RESULT="1"` | `"1"` のみ true | それ以外は false（silent） |
| `NOTIFY_ON_ERROR` | `"1"` | 失敗時の概要を Discord に投稿するか | `NOTIFY_ON_ERROR="0"` で無効化 | `"1"` のみ true | それ以外は false（silent） |
| `SUPPRESS_RESULT_IF` | `""` | 最終応答が完全一致したら投稿スキップ（opt-in） | `SUPPRESS_RESULT_IF="[NOOP]"` | 非空文字列が完全一致 | 値内のメタ文字 (`[`, `*`, `?`) は literal 扱い |
| `SUPPRESS_EMPTY_RESULT` | `"0"` | 空 RESULT_TEXT の `(no result text)` 投稿をスキップ（opt-in） | `SUPPRESS_EMPTY_RESULT="1"` | `"1"` のみ true | `"0"`, `""`, `"2"`, `"yes"`, `"true"` 等すべて false（silent） |
| `RESULT_ERROR_PREFIX` | `"ERROR:"` | RESULT_TEXT がこの prefix で始まる場合 FAIL 経路扱い | `RESULT_ERROR_PREFIX=""` で無効化、`RESULT_ERROR_PREFIX="[ERR]"` で別 prefix に | 空文字 = 検出無効化、それ以外 = literal prefix | 値内の `[`, `*`, `?` 等は literal 扱い（substring 比較）。**先頭・末尾空白も literal**（quote 必須） |

**補足**:

- 真値判定はすべて bash の文字列リテラル一致。整数演算 (`-eq`) ではない（`"1"` のみ true）
- 不正値は silent false（warn 出力しない）。これは bash の慣習に合わせた選択
- `RESULT_ERROR_PREFIX` の値に `"` や制御文字を含めても、stderr ログは `printf %q` で shell-safe quote 表示される（例: `"[ERR]"` → `\[ERR\]`、`"x y"` → `x\ y`）。読みやすさを保ちたいなら ASCII 英数記号のみが推奨
- **wrapper は値の検証 / 正規化を行わない**。`MAX_TURNS` / `TIMEOUT_SEC` / `MAX_BUDGET_USD` / `MODEL` などの値は `claude -p` や `timeout` コマンドへそのまま渡される。不正値はそれらの下位コマンドが報告する

---

## 3. `RESULT_ERROR_PREFIX=""` の適用条件

`RESULT_ERROR_PREFIX=""` を設定すると、wrapper の「`ERROR:` 始まりの RESULT_TEXT を FAIL 経路として扱う」検出が無効化される。

### 使ってよい条件

- prompt 側で `ERROR:` を fail シグナルとして **使っていない** こと
- prompt の本文が業務上 `ERROR:` で始まる正当なケースがある（例: ニュース要約で先頭が `ERROR: ...` という記事タイトル）

### 使ってはいけないジョブ

以下の既存 4 job は **すべて prompt 側で `ERROR:` を fail シグナルとして使っている**ため、`RESULT_ERROR_PREFIX=""` を設定すると本来 FAIL すべき結果が silent OK 化する:

- `jobs/mail-watch/`
- `jobs/goals-nudge/`
- `jobs/approval-demo-proposer/`
- `jobs/interview-mail-proposer/`

これらの job では `RESULT_ERROR_PREFIX` を空文字に設定する変更を行わないこと。

### カスタム prefix にする場合

`RESULT_ERROR_PREFIX="[ERR]"` のように別 prefix を指定すると、wrapper はそちらで FAIL 検出する。stderr ログは `[run-claude] FAIL via ERROR: prefix in result (<printf %q した値>)` という形式になり、grep 互換の既定文言 `FAIL via ERROR:` も依然マッチする。

---

## 4. `SUPPRESS_EMPTY_RESULT=1` の opt-in 例（mail-watch ケース）

`SUPPRESS_EMPTY_RESULT=1` を設定すると、空 RESULT_TEXT (`""`) の場合に Discord 投稿（`[<job>] (no result text)`）がスキップされる。

**本 Issue（#7）では本変数の追加のみを行い、`jobs/mail-watch/` への適用は別 Issue 扱いとする。** ここでは適用手順例とロールバック手順のみを示す。

### 設定手順例（mail-watch に適用する場合の手順）

`jobs/mail-watch/job.env` に 1 行追加する:

```
SUPPRESS_EMPTY_RESULT="1"
```

これにより、`SUPPRESS_RESULT_IF="[NOOP]"` でカバーできない「Claude のパース失敗 / malformed success などで RESULT_TEXT が空のまま正常終了したケース」の Discord 投稿が抑止される。

### ロールバック手順

不具合や運用上の問題が発生した場合は、以下のいずれかで元に戻せる:

- `jobs/mail-watch/job.env` の `SUPPRESS_EMPTY_RESULT` 行を削除（既定値 `"0"` に戻る）
- `SUPPRESS_EMPTY_RESULT="0"` に書き換え

### 空 result の痕跡確認先

`SUPPRESS_EMPTY_RESULT=1` で投稿スキップしても、ログには痕跡が残る:

- `logs/<job>/<timestamp>.json` の `.result` フィールド（空文字列または null）
- `logs/<job>/<timestamp>.stderr` の wrapper ログ
- `logs/<job>/cost.csv` の該当行

### 期待される stderr 文言

```
[run-claude] empty result + SUPPRESS_EMPTY_RESULT=1 — skipping Discord post
```

この文字列で `grep` すれば、スキップが実際に発生した実行を抽出できる。

---

## 5. プロセス環境からサポートする実行制御変数

`job.env` 経由ではなく、wrapper 起動時のプロセス環境から渡す変数。harness / テスト / 環境差吸収のための正式サポート対象。

| 変数 | 既定値 | 用途 |
|---|---|---|
| `CLAUDE_BIN` | `$HOME/.local/bin/claude` | `claude` バイナリのパス。プロセス環境からの override をサポート（`${CLAUDE_BIN:-default}` で参照）。harness では stub バイナリに差し替える |
| `DISCORD_WEBHOOK_URL` | `.env` から `set -a; source .env` で承継 | Discord webhook URL。`.env` に書かれていれば process env を上書きする（`set -a` の挙動）。harness では `.env` 内で `https://stub.invalid` 等のダミー値に固定し、stub notify が payload を別ログにリダイレクトする |

### `HERMES_HOME` の切替方法（env override 不可）

`HERMES_HOME` は wrapper 起動時に **無条件で算出される**（`${BASH_SOURCE[0]}` の `bin/` の親）。プロセス環境変数として渡しても上書きされない（line 28 の `export HERMES_HOME="$(cd ... && pwd)"`）ため、**env override はサポートしない**。

ベースディレクトリを切り替えたい場合は、wrapper を **別パス（symlink / コピー）から起動する** ことで間接的に切替える:

```bash
# harness: features/.../test/fixtures/hermes-home/bin/run-claude.sh が
# 本体 ../../../../../bin/run-claude.sh への symlink。
# symlink を起動すると BASH_SOURCE がリンク先のパスになり、
# HERMES_HOME が fixtures/hermes-home/ に解決される。
bash features/.../test/fixtures/hermes-home/bin/run-claude.sh <job>
```

harness はこの間接切替に依拠する。`CLAUDE_BIN=stub` の env override と合わせて、本体ロジックを実走しつつ外部依存（claude バイナリ / Discord）を stub に置き換える。

---

## 6. 内部実装変数（job.env で上書き可能だが未定義動作）

以下は `bin/run-claude.sh` 内部で使う変数。`job.env` で上書きすると wrapper の動作が壊れる可能性があるため、上書きしないこと。

- `JOB_NAME` — 第 1 引数のジョブ名
- `LOG_DIR` — ジョブごとのログ出力ディレクトリ
- `JOB_DIR` / `PROMPT_FILE` / `JOB_ENV` / `COST_CSV` — パス各種
- `RESULT_TEXT` / `COST_USD` / `INPUT_TOKENS` / `OUTPUT_TOKENS` / `IS_ERROR` — `jq` で抽出した結果
- `EXIT_CODE` — `claude -p` の exit code
- `JSON_LOG` / `ERR_LOG` — claude の stdout/stderr 一時ログ
- `TS` — タイムスタンプ
- `CLAUDE_ARGS` / `DISALLOWED` / `ALLOWED_ARR` — 引数配列
- `ERR_SNIPPET` — FAIL 通知本文の抜粋
- `_starts_with_error_prefix` — prefix 一致判定の内部フラグ

これらを `job.env` で再代入しても wrapper 側でその後上書きされるか、または wrapper の動作が壊れる可能性がある（未定義動作）。

---

## 7. harness 同期規律

`features/7-mail-watch-follow-up-wrapper-api-result-error-pref/test/run-harness.sh` は **本体 `bin/run-claude.sh` を symlink 経由で実際に走らせる integration harness** であり、wrapper の挙動を退行検出する。

### 規律

- `bin/run-claude.sh` を変更したら、必ず `bash features/7-.../test/run-harness.sh` を再実行し、全 T-ID が PASS することを確認する
- 新規 wrapper 変数を `job.env` サポート対象として追加した場合は、本ドキュメント（`docs/wrapper-api.md`）の表に行を追加し、harness にも fixture job を追加して退行検出範囲を広げる
- harness の fixture が drift していると感じたら、本体側の整合性を `docs/wrapper-api.md` 表と突き合わせて再確認する

これは「wrapper API を文書化したのに harness が古い」状態を防ぐための運用ルール。

---

## 関連ファイル

- `bin/run-claude.sh` — wrapper 本体（13-23 行のヘッダーコメントと本ドキュメント表は同期されている）
- `lib/notify.sh` — `notify_discord` 実装（DISCORD_WEBHOOK_URL を読む）
- `lib/disallowed-tools.txt` — 共通禁止ツールリスト
- `features/7-mail-watch-follow-up-wrapper-api-result-error-pref/` — 本 API 整理の plan / test-spec / harness
- `docs/jobs-mail-watch.md` — mail-watch 固有運用（本 API のユースケース例）
