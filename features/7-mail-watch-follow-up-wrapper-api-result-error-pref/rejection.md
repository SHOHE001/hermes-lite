# Rejection log for #7

## design_loop=1 (Codex 3 ペルソナ blocking=7)

### 採用

- architect/contrarian/migration 共通 high「Non-Goals と mail-watch の挙動変更の矛盾」→ Non-Goals を「既定値で動く既存 job は互換、ただし mail-watch は明示変更」に書き直し
- architect/contrarian/migration 共通「テスト dry-run 過多」→ T02/T05/T06 を実実行に格上げし、`features/.../test/run-branches.sh` harness を新設
- migration 「FAIL 経路 before/after 不明」→ 通知分岐の full before/after + Discord payload 互換性表を追加
- architect/contrarian/migration 「既存 7 変数列挙不足」→ docs/wrapper-api.md 対象 10 変数を plan に明記
- architect 「bash パターン解釈」→ `case ... in "$VAR"*) ...` に置き換えて literal 保証を明示
- contrarian 「prompt 契約整合」→ docs/wrapper-api.md に `RESULT_ERROR_PREFIX=""` の適用条件を明記
- contrarian 「default 宣言 / source 順序」→ 62-72 行の構造と新変数の挿入位置を plan に明記
- architect 「prompt.md 追記方針が曖昧」→ 責務分離のため prompt.md 追記を **やめる** (Out-of-Scope 化)
- migration 「許容値仕様」→ SUPPRESS_EMPTY_RESULT は `"1"` のみ true、RESULT_ERROR_PREFIX は空文字 = 無効化 と固定

### 部分採用（理由を残して進める）

- contrarian 「過剰設計（mail-watch 固有修正で済むのでは）」→ Issue #7 本文が wrapper API 整理を明示要求しており、既に 4 job で `ERROR:` プロトコルが共通化していることを根拠に汎用 API として進める。plan 内 "なぜ wrapper API 整理が必要か" セクションで根拠を明記

### 棄却

なし

## design_loop=3 (Codex 3 ペルソナ blocking=8) — max_design_loops 到達、裁量で passed

### 採用（plan に反映済み）

- migration high「`[[ == * ]]` の literal 保証が bash 仕様前提に依存」→ **substring 比較 `[[ "${RESULT_TEXT:0:${#RESULT_ERROR_PREFIX}}" == "$RESULT_ERROR_PREFIX" ]]`** に変更。pattern matching ではなく純粋な文字列比較で literal 保証
- architect high「`ERR_SNIPPET` データフロー」→ FAIL 経路で `_starts_with_error_prefix=1` **または** `RESULT_TEXT == ERROR:*` の場合に `RESULT_TEXT` を `ERR_SNIPPET` に採用するロジックを分離（prefix 無効化と通知データフローを独立化）
- architect/migration high「`CLAUDE_BIN` の公開/内部境界が harness と矛盾」→ docs/wrapper-api.md を **3 カテゴリ** に分離（job.env 設定変数 10 個 / プロセス環境からの実行制御変数 `CLAUDE_BIN` `HERMES_HOME` `DISCORD_WEBHOOK_URL` / 内部実装変数）。harness の `CLAUDE_BIN=stub` 利用は正式サポート扱い
- architect/contrarian/migration medium「harness side channel が `/tmp` 固定で並列実行・残骸に弱い」→ `mktemp -d` 配下の `$STUB_DIR` を使い `STUB_CLAUDE_JOB_FILE` env で stub-claude.sh に渡す。trap で cleanup 保証
- architect/contrarian medium「stderr 文言の shell-safe quote 不足」→ カスタム prefix 時の stderr 出力を `printf '... (%q)\n' "$RESULT_ERROR_PREFIX"` に変更。改行・制御文字・引用符も安全に表示
- architect low「stub-claude の prompt 判別未使用コード」→ stub-claude.sh の仕様から prompt parsing を削除、env 経由のみに統一
- contrarian medium「既存 job.env での新変数名衝突確認」→ T10 に `grep -rE '^(SUPPRESS_EMPTY_RESULT\|RESULT_ERROR_PREFIX)=' jobs/ features/` の衝突確認を追加
- architect medium「In-Scope の「現行構文維持」表現の不整合」→ In-Scope 表現を「substring 比較に変更」に書き換え。整合性を明示
- migration medium「T01 が実 Discord 依存で再現性なし」→ T01 を harness ベースの文字列比較テストに変更

### 棄却（Issue 要件との対立で裁量採用）

- **contrarian high「`RESULT_ERROR_PREFIX=""` の opt-out 廃止 or 二重 opt-in」**: Issue #7 本文がこの opt-in 化を明示要求しており、廃止は要件違反。二重 opt-in (`ALLOW_RESULT_ERROR_PREFIX_DISABLE=1`) は複雑度を上げるので docs の適用条件記載で運用ルール担保する方針を維持
- **contrarian high「10 変数のサポート対象文書化が過剰、新 2 変数に限定すべき」**: Issue 本文「wrapper API として整理する価値あり」要求に反する縮小提案。既存 8 変数は `bin/run-claude.sh` 13-22 行で既に list 化されており、docs/wrapper-api.md 統合は重複ではなく canonical 化
- **migration high「`RESULT_ERROR_PREFIX=""` の opt-out で migration ガード（既存 4 job の typo 検出）を実装」**: docs/wrapper-api.md に「既存 4 job では使用禁止」と明記する運用ルールで担保。検出ガードを実装すると wrapper の責務範囲を超える

### 裁量採用の判断根拠

- light flow の max_design_loops=3 に到達
- 残り blocking は Issue 要件（wrapper API 整理 + opt-in 化）と本質的に対立する縮小提案・または運用ルールで担保可能な範囲
- 合理的改善点（substring 比較・データフロー分離・harness mktemp 化・shell-safe quote・境界整理）はすべて plan に反映済み
- commit message 本文に「Codex blocking 3 件残置（裁量採用、運用ルールで担保）」と明記する

## codex_loop=2 (final review blocking=4, architect PASS)

### 採用

- contrarian high「codex 中間生成物のコミット混入」→ `.gitignore` に `features/*/codex-*.yaml*` / `codex-input.md` / `judgment-summary.md` / `plan-snapshots/` を追加。既コミット分は `git rm --cached`
- migration high「HERMES_HOME の docs と実装の矛盾」→ docs/wrapper-api.md の表から HERMES_HOME を外し、「ベースディレクトリの切替方法」として独立節に。env override 不可と明示、symlink 起動だけが正式手段
- migration medium「T06 ログ exact match 不足」→ harness T06 を `grep -qF 'FAIL via ERROR: prefix in result (\[ERR\])'` の exact match に強化
- migration medium「test summary が空」→ test-summary.json を 10 テスト全て + stderr_log_compat + compatibility_matrix を含む詳細形式に拡充

### 棄却（継続）

- contrarian high「`RESULT_ERROR_PREFIX=""` opt-out 廃止」: 設計段階で既に棄却済み、Issue 要件 (#7 対応案 2) と整合せず
- contrarian medium「8 変数公開化が過剰」: Issue 本文「wrapper API として整理する価値あり」要求に対する canonical 化として進める判断は維持
- contrarian/migration medium「T10 fixture 自身衝突で赤になる」: 実装の harness は既に `features/7-.../` を除外済みで実際は PASS している。plan/test-spec の表記にも除外条件は明記してある。Codex は実装と plan の表記を分けて読んで「赤になる」と書いているが、harness 実行結果として PASS は実証済み

## codex_loop=1 (final review blocking=6)

### 採用（実装/docs/test-spec を修正）

- 全 persona high「unrelated な loop/batch 状態ファイル混入」→ `.claude/gloop-config.json`, `features/.batch/`, `features/.loop/`, `features/5-.../state.json` を unstaged にしてコミット対象から除外
- architect/contrarian/migration high「custom prefix の stderr 期待値が実装と plan/test で不一致」→ harness は実装の `printf %q` 出力（`\[ERR\]`）と既に整合していたので、plan.md / test-spec.md の表記を実態（`(` で始まる shell-safe quote 形式）に訂正
- architect medium「T10 grep の `\|` ESC が ERE で literal 扱い」→ plan.md の T10 期待値テキストを修正（harness 実装側は既に `-E '^(A|B)='` で正しい構文）
- migration high「T10 自己 fixture との衝突検査の混線」→ harness 実装は既に `features/7-.../` 配下を除外済み。plan.md / test-spec.md の表記にも除外条件を明記
- migration medium「HERMES_HOME の env override 仕様」→ docs/wrapper-api.md の HERMES_HOME を「**プロセス環境からの override はサポートしない**。代わりに wrapper を別パス（symlink / コピー）から起動する」に訂正（line 28 の `bin/run-claude.sh` は unconditional override で env を見ない実態に合わせる）
- architect medium「MAX_TURNS 等の責務分離」→ docs/wrapper-api.md 補足に「wrapper は値の検証 / 正規化を行わない。下位コマンドに従う」と明記

### 棄却（Issue 要件との対立で裁量採用）

- contrarian high「`RESULT_ERROR_PREFIX=""` の opt-out 廃止 or 二重 opt-in」: 設計段階で既に棄却済み、Issue 要件と整合せず
- contrarian medium「wrapper-api docs が既存変数までサポート対象化」: Issue 本文「wrapper API として整理する価値あり」要求に対する canonical 化として進める判断は維持

### 採用

- 3 persona 共通 high「harness が本体を実行しないと退行検出にならない」→ harness を **本体 `bin/run-claude.sh` を symlink + stub で実走するintegration テスト** に刷新。fixture jobs + stub claude + stub notify を `features/.../test/` に置く
- contrarian high「空 result 抑止が malformed success を無通知化」→ `jobs/mail-watch/job.env` への `SUPPRESS_EMPTY_RESULT=1` 適用を **本 Issue から外す**。wrapper API 整備のみ、mail-watch 実適用は別 Issue へ送る。これで Non-Goals 矛盾も解消
- contrarian medium「public API 化が過剰」→ docs/wrapper-api.md の表現を「公式 API として固定」から「現時点でサポート対象として文書化」に弱める
- contrarian/migration medium「T03 payload 観測不能」→ stub notify が payload を `$STUB_DISCORD_LOG` に append する形式に変更し、文字列比較で検証
- contrarian/migration medium「不正値の境界仕様」→ `SUPPRESS_EMPTY_RESULT="2"` を T09 に追加し silent false 動作を確認。docs にも明記
- migration high「stderr 文言変更の grep 影響」→ 既定文言 `FAIL via ERROR: prefix in result` を **維持**。カスタム prefix 時のみ末尾に `("$prefix")` を併記。T10 で repo 内 grep 確認も実施
- architect medium「case 置換理由の揺れ」→ case 置換を **やめる**。現行 `[[ ... == "$PREFIX"* ]]` を維持。挙動変更を最小化
- architect low「3 job vs 4 job 不整合」→ Non-Goals を「既存全 4 job + ping の挙動を一切変えない」に統一
- migration medium「mail-watch ロールバック手順」→ docs/wrapper-api.md の「opt-in 例」セクション内にロールバック手順を記載（本 Issue では適用しない旨も注記）

### 棄却

なし
