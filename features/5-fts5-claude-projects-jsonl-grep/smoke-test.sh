#!/usr/bin/env bash
# smoke-test.sh: developer-local smoke test for bin/session-search.sh.
#
# Generates a temporary fixture under $CLAUDE_PROJECTS_DIR and asserts the
# key exit-code / count / format invariants documented in
# features/5-fts5-claude-projects-jsonl-grep/test-spec.md.
#
# Not wired into CI. Run manually:
#   bash features/5-fts5-claude-projects-jsonl-grep/smoke-test.sh
#
# Assertion targets: T01, T02, T03, T04, T05, T06, T07, T08, T11, T12, T14,
# T15, T15b, T16, T17, T18, T20, T22, T25, T27, T28, T29, T30,
# T31_non_iso_timestamp, T32_unreadable_file, T33_many_files.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SS_BIN="$REPO_ROOT/bin/session-search.sh"

if [[ ! -x "$SS_BIN" ]]; then
  echo "FAIL: setup: $SS_BIN not executable" >&2
  exit 1
fi

TMP="$(mktemp -d -t hermes-lite-session-search.XXXXXX)"
# Restore mode on any chmod-000'd fixture so rm -rf can clean up.
cleanup() {
  if [[ -d "$TMP" ]]; then
    find "$TMP" -type f -exec chmod u+rw {} + 2>/dev/null || true
    find "$TMP" -type d -exec chmod u+rwx {} + 2>/dev/null || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

OUT="$TMP/.out"
ERR="$TMP/.err"

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "ok: $*"; }

# ---- fixture ----------------------------------------------------------------

mkdir -p "$TMP/-home-shohei-projA"
mkdir -p "$TMP/-home-shohei-projB"
mkdir -p "$TMP/-home-shohei-projA/session-1234/subagents"

# projA / session-001.jsonl
cat > "$TMP/-home-shohei-projA/session-001.jsonl" <<'EOF'
{"type":"user","timestamp":"2026-06-23T10:00:00.000Z","message":{"role":"user","content":"Phase 2 にしたい"}}
{"type":"assistant","timestamp":"2026-06-23T10:00:05.000Z","message":{"role":"assistant","content":[{"type":"text","text":"Phase 2 で進めます"},{"type":"thinking","thinking":"内部思考も検索できる"}]}}
{"type":"user","timestamp":"2026-06-23T10:00:10.000Z","message":{"role":"user","content":[{"type":"text","text":"OK"},{"type":"tool_result","tool_use_id":"x","content":"tool_result_should_not_match_PHRASE_X"}]}}
{"type":"attachment","timestamp":"2026-06-23T10:00:15.000Z","attachment":{"data":"meta_not_to_match"}}
EOF

# projA / subagents / agent-aa.jsonl
cat > "$TMP/-home-shohei-projA/session-1234/subagents/agent-aa.jsonl" <<'EOF'
{"type":"user","timestamp":"2026-06-24T12:00:00.000Z","message":{"content":"subagent question Phase 2"}}
EOF

# projB / session-002.jsonl: legacy assistant string content
cat > "$TMP/-home-shohei-projB/session-002.jsonl" <<'EOF'
{"type":"assistant","timestamp":"2026-06-25T09:00:00.000Z","message":{"content":"legacy assistant string content with Phase 2"}}
{"type":"user","timestamp":"2026-06-25T09:00:05.000Z","message":{"content":"fixed-string regex meta: $HOME/.claude"}}
EOF

# projA / broken.jsonl: contains an invalid JSON line in the middle
cat > "$TMP/-home-shohei-projA/broken.jsonl" <<'EOF'
{"type":"user","timestamp":"2026-06-23T11:00:00.000Z","message":{"content":"good line PHRASE_X"}}
{not_json_garbage
{"type":"user","timestamp":"2026-06-23T11:00:05.000Z","message":{"content":"after broken PHRASE_X"}}
EOF

# projA / legacy.jsonl: legacy / malformed records that must fail-safe skip
cat > "$TMP/-home-shohei-projA/legacy.jsonl" <<'EOF'
{"type":"user","timestamp":"2026-06-23T12:00:00.000Z"}
{"type":"user","timestamp":"2026-06-23T12:00:05.000Z","message":{"content":null}}
{"type":"user","timestamp":"2026-06-23T12:00:10.000Z","message":{"content":[{"type":"text","text":null}]}}
{"type":"user","timestamp":"2026-06-23T12:00:15.000Z","message":{"content":[{"type":"text","text":42}]}}
{"type":"user","timestamp":"2026-06-23T12:00:20.000Z","message":{"content":"valid_legacy_PHRASE_Y"}}
EOF

# projA / dash.jsonl: user content containing literal '-foo' (T16)
cat > "$TMP/-home-shohei-projA/dash.jsonl" <<'EOF'
{"type":"user","timestamp":"2026-06-23T13:00:00.000Z","message":{"content":"contains -foo literal"}}
EOF

# projA / mixed-date.jsonl: 3 distinct ISO dates for T04_date_range.
cat > "$TMP/-home-shohei-projA/mixed-date.jsonl" <<'EOF'
{"type":"user","timestamp":"2026-06-20T08:00:00.000Z","message":{"content":"DATE_RANGE_PHRASE_A early"}}
{"type":"user","timestamp":"2026-06-23T08:00:00.000Z","message":{"content":"DATE_RANGE_PHRASE_A middle"}}
{"type":"user","timestamp":"2026-06-30T08:00:00.000Z","message":{"content":"DATE_RANGE_PHRASE_A late"}}
EOF

# projA / casefold.jsonl: T11 case-insensitive PHRASE_CI in upper/lower.
cat > "$TMP/-home-shohei-projA/casefold.jsonl" <<'EOF'
{"type":"user","timestamp":"2026-06-23T14:00:00.000Z","message":{"content":"upper PHRASE_CI"}}
{"type":"user","timestamp":"2026-06-23T14:00:05.000Z","message":{"content":"lower phrase_ci"}}
EOF

# T28 fixture: text containing literal tab (0x09) and newline (0x0A) inside
# the JSON string. Use jq to encode safely so the source bytes are correct.
jq -nc \
  --arg c "literal tab[	]and newline
inside text PHRASE_TN" \
  '{type:"user",timestamp:"2026-06-23T16:00:00.000Z",message:{content:$c}}' \
  > "$TMP/-home-shohei-projA/tab-newline.jsonl"

# T31 fixture: non-ISO and empty timestamps. PHRASE_W appears in both rows.
cat > "$TMP/-home-shohei-projA/weird-ts.jsonl" <<'EOF'
{"type":"user","timestamp":"zzzzzzzzzz","message":{"content":"weird_ts_PHRASE_W"}}
{"type":"user","timestamp":"","message":{"content":"empty_ts_PHRASE_W"}}
EOF

# T32 fixture: one readable + one unreadable jsonl side-by-side in projC.
mkdir -p "$TMP/-home-shohei-projC"
cat > "$TMP/-home-shohei-projC/readable.jsonl" <<'EOF'
{"type":"user","timestamp":"2026-06-23T17:00:00.000Z","message":{"content":"readable line PHRASE_Z"}}
EOF
cat > "$TMP/-home-shohei-projC/unreadable.jsonl" <<'EOF'
{"type":"user","timestamp":"2026-06-23T17:00:05.000Z","message":{"content":"unreadable line PHRASE_Z should NOT match"}}
EOF
chmod 000 "$TMP/-home-shohei-projC/unreadable.jsonl"

# T33 fixture: many empty jsonl files to exercise xargs batching (no jsonl
# records, just many file paths to make sure argv stays within ARG_MAX).
mkdir -p "$TMP/-home-shohei-projD"
for i in $(seq 1 1200); do
  : > "$TMP/-home-shohei-projD/empty-$i.jsonl"
done
# One real record at the end so a PHRASE_D query has something to match.
cat > "$TMP/-home-shohei-projD/real.jsonl" <<'EOF'
{"type":"user","timestamp":"2026-06-23T18:00:00.000Z","message":{"content":"final PHRASE_D among many files"}}
EOF

export CLAUDE_PROJECTS_DIR="$TMP"

# ---- helper: run with captured stdout/stderr and exit code ------------------
# Usage: run_ss [args...]
# Sets globals: RC (exit code), OUT_LINES (line count of stdout)
run_ss() {
  set +e
  "$SS_BIN" "$@" >"$OUT" 2>"$ERR"
  RC=$?
  set -e
  # wc -l counts newlines; treat empty file as 0 lines
  if [[ -s "$OUT" ]]; then
    OUT_LINES=$(wc -l < "$OUT")
  else
    OUT_LINES=0
  fi
}

assert_five_columns() {
  # Every non-empty stdout line must have exactly NF=5 under -F'\t'.
  local label="$1"
  awk -F '\t' '
    NF != 5 { print "line " NR ": NF=" NF " line=[" $0 "]" > "/dev/stderr"; bad=1 }
    END { exit bad ? 1 : 0 }
  ' "$OUT" || fail "$label: not 5 columns TSV (see stderr above)"
}

# ---- T01_basic_hit ----------------------------------------------------------
run_ss 'Phase 2'
[[ $RC -eq 0 ]] || fail "T01_basic_hit: expected exit 0, got $RC. stderr=$(cat "$ERR")"
[[ $OUT_LINES -ge 1 ]] || fail "T01_basic_hit: expected >=1 line, got $OUT_LINES"
assert_five_columns "T01_basic_hit"
pass "T01_basic_hit ($OUT_LINES lines)"

# ---- T02_no_match -----------------------------------------------------------
run_ss 'zzz_no_such_string_xyzzy_definitely_absent'
[[ $RC -eq 0 ]] || fail "T02_no_match: expected exit 0, got $RC. stderr=$(cat "$ERR")"
[[ $OUT_LINES -eq 0 ]] || fail "T02_no_match: expected 0 lines, got $OUT_LINES"
pass "T02_no_match"

# ---- T06_no_query -----------------------------------------------------------
run_ss
[[ $RC -eq 2 ]] || fail "T06_no_query: expected exit 2, got $RC"
grep -q 'Usage:' "$ERR" || fail "T06_no_query: stderr lacks usage. stderr=$(cat "$ERR")"
pass "T06_no_query"

# ---- T07_help ---------------------------------------------------------------
run_ss -h
[[ $RC -eq 0 ]] || fail "T07_help: expected exit 0, got $RC"
grep -q 'Usage:' "$OUT" || fail "T07_help: stdout lacks usage"
pass "T07_help"

# ---- T08_invalid_date -------------------------------------------------------
run_ss -s xxxx-xx-xx -- foo
[[ $RC -eq 2 ]] || fail "T08_invalid_date: expected exit 2, got $RC"
grep -q 'invalid date' "$ERR" || fail "T08_invalid_date: stderr lacks 'invalid date'. stderr=$(cat "$ERR")"
pass "T08_invalid_date"

# ---- T12_invalid_n (3 sub-cases) --------------------------------------------
for bad_n in 0 -3 abc; do
  run_ss -n "$bad_n" -- foo
  [[ $RC -eq 2 ]] || fail "T12_invalid_n($bad_n): expected exit 2, got $RC"
  grep -qi 'invalid' "$ERR" || fail "T12_invalid_n($bad_n): stderr lacks 'invalid'. stderr=$(cat "$ERR")"
done
pass "T12_invalid_n"

# ---- T14_since_after_until --------------------------------------------------
run_ss -s 2026-06-30 -u 2026-06-01 -- foo
[[ $RC -eq 2 ]] || fail "T14_since_after_until: expected exit 2, got $RC"
grep -q 'since after until' "$ERR" || fail "T14_since_after_until: stderr lacks marker. stderr=$(cat "$ERR")"
pass "T14_since_after_until"

# ---- T15_no_false_positive_tool_use -----------------------------------------
run_ss 'tool_result_should_not_match'
[[ $RC -eq 0 ]] || fail "T15: expected exit 0, got $RC"
[[ $OUT_LINES -eq 0 ]] || fail "T15: expected 0 lines (tool_result skipped), got $OUT_LINES. stdout=$(cat "$OUT")"
pass "T15_no_false_positive_tool_use"

# ---- T15b_no_meta_match -----------------------------------------------------
# '2026-06-23' is only present in timestamp metadata (DATE col) and in no
# extracted user/assistant text. Awk evaluates only $5, so 0 matches.
run_ss '2026-06-23'
[[ $RC -eq 0 ]] || fail "T15b_no_meta_match: expected exit 0, got $RC"
[[ $OUT_LINES -eq 0 ]] || fail "T15b_no_meta_match: expected 0 lines, got $OUT_LINES. stdout=$(cat "$OUT")"
pass "T15b_no_meta_match"

# ---- T16_query_dash_prefix --------------------------------------------------
run_ss -- '-foo'
[[ $RC -eq 0 ]] || fail "T16_query_dash_prefix: expected exit 0, got $RC. stderr=$(cat "$ERR")"
[[ $OUT_LINES -ge 1 ]] || fail "T16_query_dash_prefix: expected >=1 line, got $OUT_LINES"
pass "T16_query_dash_prefix"

# ---- T17_max_results_exits_zero ---------------------------------------------
# Query 'a' matches many records; with -n 1 awk exits after 1 hit. The
# producer side gets SIGPIPE (141); the wrapper must normalize that to 0.
run_ss -n 1 -- a
[[ $RC -eq 0 ]] || fail "T17_max_results_exits_zero: expected exit 0 (not 141), got $RC"
[[ $OUT_LINES -eq 1 ]] || fail "T17_max_results_exits_zero: expected 1 line, got $OUT_LINES"
pass "T17_max_results_exits_zero"

# ---- T18_broken_jsonl -------------------------------------------------------
# broken.jsonl has exactly 2 good lines containing PHRASE_X; the bad middle
# line is silently skipped. No other fixture record contains literal PHRASE_X
# in extracted text (tool_result content is filtered out).
run_ss 'PHRASE_X'
[[ $RC -eq 0 ]] || fail "T18_broken_jsonl: expected exit 0, got $RC. stderr=$(cat "$ERR")"
[[ $OUT_LINES -eq 2 ]] || fail "T18_broken_jsonl: expected 2 lines, got $OUT_LINES. stdout=$(cat "$OUT")"
pass "T18_broken_jsonl"

# ---- T20_no_projects_dir ----------------------------------------------------
# Override CLAUDE_PROJECTS_DIR to a nonexistent path for just this call.
set +e
CLAUDE_PROJECTS_DIR="/nonexistent/path/$(date +%s)" "$SS_BIN" foo >"$OUT" 2>"$ERR"
RC=$?
set -e
[[ $RC -eq 1 ]] || fail "T20_no_projects_dir: expected exit 1, got $RC"
grep -q 'no projects dir' "$ERR" || fail "T20_no_projects_dir: stderr lacks marker. stderr=$(cat "$ERR")"
pass "T20_no_projects_dir"

# ---- T22_user_text_block ----------------------------------------------------
# tool_result content embedded in user.content[] must not match.
run_ss 'tool_result_should_not_match_PHRASE_X'
[[ $RC -eq 0 ]] || fail "T22_user_text_block: expected exit 0, got $RC"
[[ $OUT_LINES -eq 0 ]] || fail "T22_user_text_block: expected 0 lines, got $OUT_LINES. stdout=$(cat "$OUT")"
pass "T22_user_text_block"

# ---- T27_invalid_regex ------------------------------------------------------
run_ss -- '['
[[ $RC -eq 2 ]] || fail "T27_invalid_regex: expected exit 2, got $RC"
grep -q 'invalid regex' "$ERR" || fail "T27_invalid_regex: stderr lacks marker. stderr=$(cat "$ERR")"
pass "T27_invalid_regex"

# ---- T29_assistant_string_content -------------------------------------------
run_ss 'legacy assistant string content'
[[ $RC -eq 0 ]] || fail "T29_assistant_string_content: expected exit 0, got $RC"
[[ $OUT_LINES -ge 1 ]] || fail "T29_assistant_string_content: expected >=1 line, got $OUT_LINES"
# Sanity: the matched row should be from projB / session-002 / assistant.
awk -F '\t' '$1=="-home-shohei-projB" && $3=="session-002" && $4=="assistant" {found=1} END{exit found?0:1}' "$OUT" \
  || fail "T29_assistant_string_content: no row matched projB/session-002/assistant. stdout=$(cat "$OUT")"
pass "T29_assistant_string_content"

# ---- T30_legacy_fail_safe ---------------------------------------------------
# Only the last record of legacy.jsonl has a valid string content with
# PHRASE_Y. The malformed earlier records (missing message / null content /
# null .text / non-string .text) must be skipped without error.
run_ss 'valid_legacy_PHRASE_Y'
[[ $RC -eq 0 ]] || fail "T30_legacy_fail_safe: expected exit 0, got $RC. stderr=$(cat "$ERR")"
[[ $OUT_LINES -eq 1 ]] || fail "T30_legacy_fail_safe: expected 1 line, got $OUT_LINES. stdout=$(cat "$OUT")"
pass "T30_legacy_fail_safe"

# ---- T03_project_filter -----------------------------------------------------
# projA and projB both contain 'Phase 2' rows; -p '*projA' must keep only
# projA in the PROJECT column.
run_ss -p '*projA' 'Phase 2'
[[ $RC -eq 0 ]] || fail "T03_project_filter: expected exit 0, got $RC. stderr=$(cat "$ERR")"
[[ $OUT_LINES -ge 1 ]] || fail "T03_project_filter: expected >=1 line, got $OUT_LINES"
awk -F '\t' '$1 != "-home-shohei-projA" { print "leaked project: " $1 > "/dev/stderr"; bad=1 } END { exit bad?1:0 }' "$OUT" \
  || fail "T03_project_filter: rows from other projects leaked. stdout=$(cat "$OUT")"
pass "T03_project_filter ($OUT_LINES lines)"

# ---- T04_date_range ---------------------------------------------------------
# mixed-date.jsonl has rows on 2026-06-20 / 23 / 30. The middle date must be
# the only one returned for -s 2026-06-23 -u 2026-06-23.
run_ss -s 2026-06-23 -u 2026-06-23 'DATE_RANGE_PHRASE_A'
[[ $RC -eq 0 ]] || fail "T04_date_range: expected exit 0, got $RC. stderr=$(cat "$ERR")"
[[ $OUT_LINES -eq 1 ]] || fail "T04_date_range: expected 1 line, got $OUT_LINES. stdout=$(cat "$OUT")"
awk -F '\t' '$2 != "2026-06-23" { print "wrong date: " $2 > "/dev/stderr"; bad=1 } END { exit bad?1:0 }' "$OUT" \
  || fail "T04_date_range: row outside [2026-06-23,2026-06-23] returned. stdout=$(cat "$OUT")"
pass "T04_date_range"

# ---- T05_max_limit ----------------------------------------------------------
# 'Phase 2' matches multiple rows; -n 1 must clip output to exactly 1 line
# and exit 0 (SIGPIPE 141 must be swallowed by the wrapper).
run_ss -n 1 'Phase 2'
[[ $RC -eq 0 ]] || fail "T05_max_limit: expected exit 0, got $RC"
[[ $OUT_LINES -eq 1 ]] || fail "T05_max_limit: expected 1 line, got $OUT_LINES. stdout=$(cat "$OUT")"
pass "T05_max_limit"

# ---- T11_case_insensitive ---------------------------------------------------
# casefold.jsonl has both 'PHRASE_CI' and 'phrase_ci'; -i with query 'PHASE'
# variant must catch both (here we use 'PHRASE_CI' to be explicit about case).
run_ss -i 'PHRASE_CI'
[[ $RC -eq 0 ]] || fail "T11_case_insensitive: expected exit 0, got $RC"
[[ $OUT_LINES -eq 2 ]] || fail "T11_case_insensitive: expected 2 lines, got $OUT_LINES. stdout=$(cat "$OUT")"
pass "T11_case_insensitive"

# ---- T25_subagent_jsonl -----------------------------------------------------
# The subagent jsonl lives under projA/<uuid>/subagents/agent-aa.jsonl. The
# PROJECT column must still be the top-level dir name ('-home-shohei-projA'),
# never 'subagents' or the UUID.
run_ss 'subagent question'
[[ $RC -eq 0 ]] || fail "T25_subagent_jsonl: expected exit 0, got $RC"
[[ $OUT_LINES -ge 1 ]] || fail "T25_subagent_jsonl: expected >=1 line, got $OUT_LINES"
awk -F '\t' '$1 != "-home-shohei-projA" { print "wrong project: " $1 > "/dev/stderr"; bad=1 } END { exit bad?1:0 }' "$OUT" \
  || fail "T25_subagent_jsonl: PROJECT was not the top-level dir. stdout=$(cat "$OUT")"
# SESSION should be the file basename ('agent-aa'), not a uuid path.
awk -F '\t' '$3 != "agent-aa" { print "wrong session: " $3 > "/dev/stderr"; bad=1 } END { exit bad?1:0 }' "$OUT" \
  || fail "T25_subagent_jsonl: SESSION column was not the file basename. stdout=$(cat "$OUT")"
pass "T25_subagent_jsonl"

# ---- T28_text_with_tab_newline ----------------------------------------------
# tab-newline.jsonl contains a literal 0x09 and 0x0A inside the JSON string.
# The TSV output must remain exactly 5 columns (control chars normalized).
run_ss 'PHRASE_TN'
[[ $RC -eq 0 ]] || fail "T28_text_with_tab_newline: expected exit 0, got $RC. stderr=$(cat "$ERR")"
[[ $OUT_LINES -eq 1 ]] || fail "T28_text_with_tab_newline: expected 1 line, got $OUT_LINES. stdout=$(cat "$OUT")"
assert_five_columns "T28_text_with_tab_newline"
pass "T28_text_with_tab_newline"

# ---- T31_non_iso_timestamp --------------------------------------------------
# weird-ts.jsonl has two rows: timestamp 'zzzzzzzzzz' (non-ISO) and ''
# (empty). Both must be returned when no date filter is applied, both must
# have DATE = empty string in the output.
run_ss -- 'PHRASE_W'
[[ $RC -eq 0 ]] || fail "T31_non_iso_timestamp(no filter): expected exit 0, got $RC. stderr=$(cat "$ERR")"
[[ $OUT_LINES -eq 2 ]] || fail "T31_non_iso_timestamp(no filter): expected 2 lines, got $OUT_LINES. stdout=$(cat "$OUT")"
awk -F '\t' '$2 != "" { print "DATE not empty for non-ISO ts: " $2 > "/dev/stderr"; bad=1 } END { exit bad?1:0 }' "$OUT" \
  || fail "T31_non_iso_timestamp(no filter): DATE column was not empty. stdout=$(cat "$OUT")"

# With -u 2026-01-01, both rows have empty DATE so they must be dropped
# (cannot be lexically compared with the upper bound).
run_ss -u 2026-01-01 -- 'PHRASE_W'
[[ $RC -eq 0 ]] || fail "T31_non_iso_timestamp(-u): expected exit 0, got $RC. stderr=$(cat "$ERR")"
[[ $OUT_LINES -eq 0 ]] || fail "T31_non_iso_timestamp(-u): expected 0 lines, got $OUT_LINES. stdout=$(cat "$OUT")"
pass "T31_non_iso_timestamp"

# ---- T32_unreadable_file ----------------------------------------------------
# unreadable.jsonl was chmod 000'd at setup. Only readable.jsonl must hit.
run_ss -- 'PHRASE_Z'
[[ $RC -eq 0 ]] || fail "T32_unreadable_file: expected exit 0, got $RC. stderr=$(cat "$ERR")"
[[ $OUT_LINES -eq 1 ]] || fail "T32_unreadable_file: expected 1 line (readable.jsonl only), got $OUT_LINES. stdout=$(cat "$OUT")"
awk -F '\t' '$3 != "readable" { print "leaked session: " $3 > "/dev/stderr"; bad=1 } END { exit bad?1:0 }' "$OUT" \
  || fail "T32_unreadable_file: a session other than 'readable' leaked. stdout=$(cat "$OUT")"
pass "T32_unreadable_file"

# ---- T33_many_files ---------------------------------------------------------
# 1200 empty jsonl + 1 real jsonl in projD. The xargs batching must avoid
# 'Argument list too long' and still surface the one real PHRASE_D row.
run_ss -- 'PHRASE_D'
[[ $RC -eq 0 ]] || fail "T33_many_files: expected exit 0, got $RC. stderr=$(cat "$ERR")"
[[ $OUT_LINES -eq 1 ]] || fail "T33_many_files: expected 1 line, got $OUT_LINES. stdout=$(cat "$OUT")"
# Make sure no 'Argument list too long' phrase leaked anywhere.
if grep -qi 'argument list too long' "$ERR" "$OUT"; then
  fail "T33_many_files: 'Argument list too long' surfaced. stderr=$(cat "$ERR")"
fi
pass "T33_many_files"

echo "ALL PASS"
