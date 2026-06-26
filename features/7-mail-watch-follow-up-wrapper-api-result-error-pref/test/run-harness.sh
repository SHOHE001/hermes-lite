#!/usr/bin/env bash
# run-harness.sh — Issue #7 wrapper API 整理の integration harness。
#
# 本体 bin/run-claude.sh を symlink + stub claude + stub notify で実走させ、
# 各 T-ID の stderr と Discord payload を観測して期待値検証する。
#
# 使い方:
#   bash features/7-mail-watch-follow-up-wrapper-api-result-error-pref/test/run-harness.sh
#
# 成功時: 各 T-ID で `PASS: <T-ID>` を出し、最後に `ALL PASSED (N tests)`。
# 失敗時: `FAIL: <T-ID>: <reason>` を出して exit 1。

set -euo pipefail

# --- ロケーション ---
HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURES="$HARNESS_DIR/fixtures"
REPO_ROOT="$(cd "$HARNESS_DIR/../../.." && pwd)"
HERMES_HOME_FIXTURE="$FIXTURES/hermes-home"

# --- 一時ディレクトリ（mktemp 配下に隔離、trap で必ず cleanup） ---
STUB_DIR="$(mktemp -d)"
trap 'rm -rf "$STUB_DIR"' EXIT

STUB_CLAUDE_JOB_FILE="$STUB_DIR/current-job"
export STUB_CLAUDE_JOB_FILE

# --- 結果集計 ---
PASS_COUNT=0
FAIL_COUNT=0
FAIL_DETAILS=()

pass() {
  echo "PASS: $1"
  PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
  echo "FAIL: $1: $2" >&2
  FAIL_COUNT=$((FAIL_COUNT + 1))
  FAIL_DETAILS+=("$1: $2")
}

# --- harness で wrapper を 1 回起動するヘルパー ---
# args: <t-id>
# 副作用: $STUB_DIR/<t-id>.stderr, $STUB_DIR/<t-id>.discord, $STUB_DIR/<t-id>.exit
run_job() {
  local t_id="$1"
  local stderr_file="$STUB_DIR/$t_id.stderr"
  local discord_file="$STUB_DIR/$t_id.discord"
  local exit_file="$STUB_DIR/$t_id.exit"

  # 各実行で discord log を初期化（空ファイル）
  : > "$discord_file"

  # job id を stub-claude.sh が読む env-mediated channel に書く
  echo "$t_id" > "$STUB_CLAUDE_JOB_FILE"

  # wrapper の HERMES_HOME 算出は BASH_SOURCE ベースなので、
  # symlink 経由で bin/run-claude.sh を叩くと HERMES_HOME=fixtures/hermes-home に解決される。
  set +e
  CLAUDE_BIN="$FIXTURES/stub-claude.sh" \
  STUB_CLAUDE_JOB_FILE="$STUB_CLAUDE_JOB_FILE" \
  STUB_DISCORD_LOG="$discord_file" \
    bash "$HERMES_HOME_FIXTURE/bin/run-claude.sh" "$t_id" \
    2>"$stderr_file" >/dev/null
  echo $? > "$exit_file"
  set -e
}

# ============================================================
# T01: default-compat
# ============================================================
test_t01() {
  local t_id="t01-default-compat"
  run_job "$t_id"
  local stderr_file="$STUB_DIR/$t_id.stderr"
  local discord_file="$STUB_DIR/$t_id.discord"

  if ! grep -qF 'OK exit=0' "$stderr_file"; then
    fail "T01_default_compat" "stderr に 'OK exit=0' が無い: $(cat "$stderr_file")"
    return
  fi
  local expected="[$t_id] ok"
  if ! diff <(echo "$expected") "$discord_file" >/dev/null 2>&1; then
    fail "T01_default_compat" "discord log が期待値と一致しない (expected='$expected', actual=$(cat "$discord_file" | tr '\n' '|'))"
    return
  fi
  pass "T01_default_compat"
}

# ============================================================
# T02: empty + SUPPRESS_EMPTY_RESULT=1 → skip
# ============================================================
test_t02() {
  local t_id="t02-empty"
  run_job "$t_id"
  local stderr_file="$STUB_DIR/$t_id.stderr"
  local discord_file="$STUB_DIR/$t_id.discord"

  if ! grep -qF 'empty result + SUPPRESS_EMPTY_RESULT=1 — skipping Discord post' "$stderr_file"; then
    fail "T02_empty_suppress" "stderr に suppress ログが無い: $(cat "$stderr_file")"
    return
  fi
  if [[ -s "$discord_file" ]]; then
    fail "T02_empty_suppress" "discord log が空でない: $(cat "$discord_file")"
    return
  fi
  pass "T02_empty_suppress"
}

# ============================================================
# T03: empty + default (no suppress) → "(no result text)"
# ============================================================
test_t03() {
  local t_id="t03-empty-default"
  run_job "$t_id"
  local stderr_file="$STUB_DIR/$t_id.stderr"
  local discord_file="$STUB_DIR/$t_id.discord"

  if ! grep -qF 'OK exit=0' "$stderr_file"; then
    fail "T03_empty_default" "stderr に 'OK exit=0' が無い: $(cat "$stderr_file")"
    return
  fi
  if ! grep -qF "[$t_id] (no result text)" "$discord_file"; then
    fail "T03_empty_default" "discord log に '(no result text)' が無い: $(cat "$discord_file")"
    return
  fi
  pass "T03_empty_default"
}

# ============================================================
# T04: ERROR: default → FAIL
# ============================================================
test_t04() {
  local t_id="t04-error-default"
  run_job "$t_id"
  local stderr_file="$STUB_DIR/$t_id.stderr"
  local discord_file="$STUB_DIR/$t_id.discord"

  # grep 互換: 既定 prefix のときは末尾 (...) 無し
  if ! grep -qE 'FAIL via ERROR: prefix in result$' "$stderr_file"; then
    fail "T04_error_default" "stderr に 'FAIL via ERROR: prefix in result' (末尾 (...) 無し) が無い: $(cat "$stderr_file")"
    return
  fi
  # 末尾に (...) が付いていないことを negative 確認
  if grep -qF 'FAIL via ERROR: prefix in result (' "$stderr_file"; then
    fail "T04_error_default" "stderr に末尾 (...) 付きの文言が含まれている（既定では付かないはず）: $(cat "$stderr_file")"
    return
  fi
  if ! grep -qF 'FAIL exit=0' "$discord_file"; then
    fail "T04_error_default" "discord log に 'FAIL exit=0' が無い: $(cat "$discord_file")"
    return
  fi
  if ! grep -qF 'ERROR: stub fail' "$discord_file"; then
    fail "T04_error_default" "discord log に 'ERROR: stub fail' が無い: $(cat "$discord_file")"
    return
  fi
  pass "T04_error_default"
}

# ============================================================
# T05: ERROR: + RESULT_ERROR_PREFIX="" → OK 経路
# ============================================================
test_t05() {
  local t_id="t05-error-disabled"
  run_job "$t_id"
  local stderr_file="$STUB_DIR/$t_id.stderr"
  local discord_file="$STUB_DIR/$t_id.discord"

  if ! grep -qF 'OK exit=0' "$stderr_file"; then
    fail "T05_error_disabled" "stderr に 'OK exit=0' が無い (prefix 無効化が効いていない): $(cat "$stderr_file")"
    return
  fi
  local expected="[$t_id] ERROR: stub fail"
  if ! grep -qF "$expected" "$discord_file"; then
    fail "T05_error_disabled" "discord log に '$expected' が無い: $(cat "$discord_file")"
    return
  fi
  pass "T05_error_disabled"
}

# ============================================================
# T06: [ERR] + RESULT_ERROR_PREFIX="[ERR]" → FAIL with quoted prefix
# ============================================================
test_t06() {
  local t_id="t06-error-custom"
  run_job "$t_id"
  local stderr_file="$STUB_DIR/$t_id.stderr"
  local discord_file="$STUB_DIR/$t_id.discord"

  # printf %q で [ERR] → \[ERR\] となる exact match。
  # bash 5+ では printf '%q' '[ERR]' は '\[ERR\]' を出す。
  if ! grep -qF 'FAIL via ERROR: prefix in result (\[ERR\])' "$stderr_file"; then
    fail "T06_error_custom_prefix" "stderr に exact '(\\[ERR\\])' 形式の FAIL ログが無い: $(cat "$stderr_file")"
    return
  fi
  if ! grep -qF 'FAIL exit=0' "$discord_file"; then
    fail "T06_error_custom_prefix" "discord log に 'FAIL exit=0' が無い: $(cat "$discord_file")"
    return
  fi
  if ! grep -qF '[ERR] stub fail' "$discord_file"; then
    fail "T06_error_custom_prefix" "discord log に '[ERR] stub fail' が無い: $(cat "$discord_file")"
    return
  fi
  pass "T06_error_custom_prefix"
}

# ============================================================
# T07: mail-watch は無変更
# ============================================================
test_t07() {
  local diff_out
  diff_out=$(cd "$REPO_ROOT" && git diff main -- jobs/mail-watch/ 2>&1 || true)
  if [[ -n "$diff_out" ]]; then
    fail "T07_mail_watch_dryrun" "jobs/mail-watch/ に差分あり: $diff_out"
    return
  fi
  pass "T07_mail_watch_dryrun"
}

# ============================================================
# T08: docs review
# ============================================================
test_t08() {
  # (1) docs/jobs-mail-watch.md の旧記述削除を確認
  local docs_diff
  docs_diff=$(cd "$REPO_ROOT" && git diff main -- docs/jobs-mail-watch.md 2>&1 || true)
  # diff の削除行に旧記述 '.result' + 'stderr で発見可能' が出ているか
  # (.result はバッククォート quote されているので、間に他の文字も入る前提で fixed string で 2 段確認)
  if ! echo "$docs_diff" | grep '^-' | grep -F 'stderr で発見可能' >/dev/null; then
    fail "T08_docs_review" "docs/jobs-mail-watch.md の旧記述 'stderr で発見可能' が削除行に出ていない"
    return
  fi

  # (2) wrapper-api.md に 10 変数以上の行
  local var_rows
  var_rows=$(grep -c '^| `[A-Z_]\+`' "$REPO_ROOT/docs/wrapper-api.md" || echo 0)
  if (( var_rows < 10 )); then
    fail "T08_docs_review" "docs/wrapper-api.md の変数行が 10 未満 ($var_rows)"
    return
  fi

  # (3) wrapper-api.md に 2 新変数が記載
  if ! grep -qF 'SUPPRESS_EMPTY_RESULT' "$REPO_ROOT/docs/wrapper-api.md"; then
    fail "T08_docs_review" "docs/wrapper-api.md に SUPPRESS_EMPTY_RESULT が無い"
    return
  fi
  if ! grep -qF 'RESULT_ERROR_PREFIX' "$REPO_ROOT/docs/wrapper-api.md"; then
    fail "T08_docs_review" "docs/wrapper-api.md に RESULT_ERROR_PREFIX が無い"
    return
  fi
  pass "T08_docs_review"
}

# ============================================================
# T09: 不正値 SUPPRESS_EMPTY_RESULT="2" は silent false
# ============================================================
test_t09() {
  local t_id="t09-suppress-bad-value"
  run_job "$t_id"
  local stderr_file="$STUB_DIR/$t_id.stderr"
  local discord_file="$STUB_DIR/$t_id.discord"

  if ! grep -qF 'OK exit=0' "$stderr_file"; then
    fail "T09_suppress_bad_value" "stderr に 'OK exit=0' が無い: $(cat "$stderr_file")"
    return
  fi
  if ! grep -qF "[$t_id] (no result text)" "$discord_file"; then
    fail "T09_suppress_bad_value" "discord log に '(no result text)' が無い（不正値が誤って true 判定された可能性）: $(cat "$discord_file")"
    return
  fi
  pass "T09_suppress_bad_value"
}

# ============================================================
# T10: grep 互換確認
# ============================================================
test_t10() {
  # (1) 'FAIL via ERROR' のコード上の参照が bin/run-claude.sh のみ
  # plan の T10 の意図は「外部 grep 監視が壊れないこと」「コードで重複参照していないこと」の確認。
  # docs/ と features/ 配下は plan/test-spec/wrapper-api 等の説明記述で本文言を引用しており、
  # コードの挙動には影響しないため除外する。
  local hits
  hits=$(cd "$REPO_ROOT" && grep -rn 'FAIL via ERROR' \
    --include='*.md' --include='*.sh' --include='*.py' --include='*.mjs' --include='*.js' \
    . 2>/dev/null || true)
  local extra_hits
  extra_hits=$(echo "$hits" | grep -v '^$' \
    | grep -v '^\./bin/run-claude.sh:' \
    | grep -v '^\./docs/' \
    | grep -v '^\./features/' \
    || true)
  if [[ -n "$extra_hits" ]]; then
    fail "T10_grep_compat" "FAIL via ERROR が bin/run-claude.sh 以外（docs/features を除く）でヒット: $extra_hits"
    return
  fi

  # (2) 既存 job.env / features 配下に SUPPRESS_EMPTY_RESULT / RESULT_ERROR_PREFIX 設定が無いこと
  # 本 Issue で追加した features/7-.../ 配下（plan / test fixtures）は除外。
  local conflict
  conflict=$(cd "$REPO_ROOT" && grep -rE '^(SUPPRESS_EMPTY_RESULT|RESULT_ERROR_PREFIX)=' jobs/ features/ 2>/dev/null \
    | grep -v '^features/7-mail-watch-follow-up-wrapper-api-result-error-pref/' \
    || true)
  if [[ -n "$conflict" ]]; then
    fail "T10_grep_compat" "新変数名と既存設定で衝突: $conflict"
    return
  fi
  pass "T10_grep_compat"
}

# ============================================================
# 実行
# ============================================================
echo "[harness] STUB_DIR=$STUB_DIR"
test_t01
test_t02
test_t03
test_t04
test_t05
test_t06
test_t07
test_t08
test_t09
test_t10

TOTAL=$((PASS_COUNT + FAIL_COUNT))
if (( FAIL_COUNT > 0 )); then
  echo ""
  echo "FAILED ($FAIL_COUNT / $TOTAL): " >&2
  for d in "${FAIL_DETAILS[@]}"; do
    echo "  - $d" >&2
  done
  exit 1
fi
echo ""
echo "ALL PASSED ($PASS_COUNT tests)"
