# test-spec: #5 session-search.sh

`project_type: jobs` のため自動テストは作らず、本ファイルの手動チェックリストで検証する。fixture ベースの主要ケースは `smoke-test.sh` で自動 assert する（CI 非統合、開発者ローカル実行）。

## Public contract（README 代替・`--help` と同じ仕様を再掲）

- exit code:
  - `0` = 正常（マッチ 0 件含む。「結果 0 件は正常終了として扱う」）
  - `1` = 実行環境エラー（依存欠如 / projects dir 不在 / jq filter 構文エラー）
  - `2` = usage / 引数 / regex エラー（QUERY 未指定、不正 date、不正 -n/-c、project glob 不正文字、invalid regex）
- 読み取り不能 jsonl は warning なしで skip（exit code に影響しない）
- 出力順序: 同 jsonl 内は時系列昇順、jsonl 間の順序は非保証
- SNIPPET: jq `@tsv` エスケープ後の文字列。本文中の literal `\t` / `\n` 2 文字シーケンスは `\\t` / `\\n` として現れる
- DATE: timestamp の先頭 10 文字。非 ISO / 空の場合は空文字列で出力（`-s`/`-u` 指定時は文字列比較で実質除外）
- 出力フォーマット（5 カラム TSV）: `PROJECT<TAB>DATE<TAB>SESSION<TAB>TYPE<TAB>SNIPPET`
- `--` でオプション終端、以降を QUERY 扱い（先頭ハイフン QUERY の指定方法）

## 導入手順

```bash
# 動作確認
~/hermes-lite/bin/session-search.sh --help

# 通常の検索
~/hermes-lite/bin/session-search.sh 'Phase 2'

# プロジェクト絞り込み + 日付範囲 + 件数上限
~/hermes-lite/bin/session-search.sh -p '*hermes-lite' -s 2026-06-23 -n 10 'tool_use'

# fixed-string + case-insensitive
~/hermes-lite/bin/session-search.sh -F -i 'My-Query'

# 別ディレクトリを root にする（テスト用）
CLAUDE_PROJECTS_DIR=/tmp/fixture ~/hermes-lite/bin/session-search.sh 'foo'
```

将来 FTS5 へ移行しても、上記 public contract（5 カラム TSV / exit code / 出力順序）は維持する。

## 前提セットアップ（fixture 作成）

```bash
TMP=$(mktemp -d)
mkdir -p "$TMP/-home-shohei-projA"
mkdir -p "$TMP/-home-shohei-projB"
mkdir -p "$TMP/-home-shohei-projA/session-1234/subagents"

# projA / session-001.jsonl: user string content + assistant text/thinking blocks
cat > "$TMP/-home-shohei-projA/session-001.jsonl" <<'EOF'
{"type":"user","timestamp":"2026-06-23T10:00:00.000Z","message":{"role":"user","content":"Phase 2 にしたい"}}
{"type":"assistant","timestamp":"2026-06-23T10:00:05.000Z","message":{"role":"assistant","content":[{"type":"text","text":"Phase 2 で進めます"},{"type":"thinking","thinking":"内部思考も検索できる"}]}}
{"type":"user","timestamp":"2026-06-23T10:00:10.000Z","message":{"role":"user","content":[{"type":"text","text":"OK"},{"type":"tool_result","tool_use_id":"x","content":"tool_result_should_not_match_PHRASE_X"}]}}
{"type":"attachment","timestamp":"2026-06-23T10:00:15.000Z","attachment":{"data":"meta_not_to_match"}}
EOF

# projA/subagents: subagent jsonl
cat > "$TMP/-home-shohei-projA/session-1234/subagents/agent-aa.jsonl" <<'EOF'
{"type":"user","timestamp":"2026-06-24T12:00:00.000Z","message":{"content":"subagent question Phase 2"}}
EOF

# projB / session-002.jsonl: assistant string content (旧形式)
cat > "$TMP/-home-shohei-projB/session-002.jsonl" <<'EOF'
{"type":"assistant","timestamp":"2026-06-25T09:00:00.000Z","message":{"content":"legacy assistant string content with Phase 2"}}
{"type":"user","timestamp":"2026-06-25T09:00:05.000Z","message":{"content":"fixed-string regex meta: $HOME/.claude"}}
EOF

# projA / broken.jsonl: 不正な JSON 行を含む
cat > "$TMP/-home-shohei-projA/broken.jsonl" <<'EOF'
{"type":"user","timestamp":"2026-06-23T11:00:00.000Z","message":{"content":"good line PHRASE_X"}}
{not_json_garbage
{"type":"user","timestamp":"2026-06-23T11:00:05.000Z","message":{"content":"after broken PHRASE_X"}}
EOF

# projA / legacy.jsonl: 旧形式 fail-safe
cat > "$TMP/-home-shohei-projA/legacy.jsonl" <<'EOF'
{"type":"user","timestamp":"2026-06-23T12:00:00.000Z"}
{"type":"user","timestamp":"2026-06-23T12:00:05.000Z","message":{"content":null}}
{"type":"user","timestamp":"2026-06-23T12:00:10.000Z","message":{"content":[{"type":"text","text":null}]}}
{"type":"user","timestamp":"2026-06-23T12:00:15.000Z","message":{"content":[{"type":"text","text":42}]}}
{"type":"user","timestamp":"2026-06-23T12:00:20.000Z","message":{"content":"valid_legacy_PHRASE_Y"}}
EOF

export CLAUDE_PROJECTS_DIR="$TMP"
echo "fixture dir: $TMP"
```

## チェックリスト

各項目は `CLAUDE_PROJECTS_DIR=$TMP ~/hermes-lite/bin/session-search.sh ...` を実行して結果を確認する。`SS` を以下のエイリアスとする:

```bash
SS=( env "CLAUDE_PROJECTS_DIR=$TMP" "$HOME/hermes-lite/bin/session-search.sh" )
```

### 正常系

- [ ] **T01_basic_hit**: `"${SS[@]}" 'Phase 2'` → 1 件以上の TSV 行 / 各行 5 カラム / exit 0
- [ ] **T03_project_filter**: `"${SS[@]}" -p '*projA' 'Phase 2'` → PROJECT カラムが `*projA` glob のみ
- [ ] **T04_date_range**: `"${SS[@]}" -s 2026-06-23 -u 2026-06-23 'Phase 2'` → DATE カラムが全て `2026-06-23`
- [ ] **T05_max_limit**: `"${SS[@]}" -n 1 'Phase 2'` → 行数 1 / exit 0
- [ ] **T07_help**: `"${SS[@]}" -h` → usage stdout / exit 0
- [ ] **T09_fixed_string**: `"${SS[@]}" -F '$HOME/.claude'` → projB session-002 のヒット
- [ ] **T11_case_insensitive**: `"${SS[@]}" -i 'PHASE'` → 1 件以上
- [ ] **T16_query_dash_prefix**: fixture に `-foo` を含むレコードを追加した上で `"${SS[@]}" -- '-foo'` → ヒット
- [ ] **T21_user_string_content**: T01 で projA session-001 1 行目（`Phase 2 にしたい`）がヒット
- [ ] **T22_user_text_block**: T01 で projA session-001 3 行目（text=`OK`）は出る、`tool_result_should_not_match_PHRASE_X` でクエリすると 0 件
- [ ] **T23_assistant_thinking**: `"${SS[@]}" '内部思考'` → projA session-001 の assistant thinking でヒット
- [ ] **T25_subagent_jsonl**: T01 で `subagent question Phase 2` を含む行が出る、PROJECT カラムが `-home-shohei-projA`（`subagents` や UUID にならない）
- [ ] **T29_assistant_string_content**: T01 で projB session-002 の `legacy assistant string content with Phase 2` がヒット

### 退化・境界

- [ ] **T02_no_match**: `"${SS[@]}" 'zzz_no_such_string_xyzzy_definitely_absent'` → 出力なし / exit 0
- [ ] **T06_no_query**: `"${SS[@]}"` → stderr に usage / exit 2
- [ ] **T08_invalid_date**: `"${SS[@]}" -s xxxx-xx-xx -- foo` → stderr `invalid date` / exit 2
- [ ] **T10_snippet_length**: `"${SS[@]}" -c 50 'Phase'` → SNIPPET 列の長さ ≤ 53 バイト（50 + `…` の 3 バイト）
- [ ] **T12_invalid_n**: `"${SS[@]}" -n 0 -- foo` / `-n -3 -- foo` / `-n abc -- foo` → stderr `invalid` / exit 2
- [ ] **T13_invalid_c**: `"${SS[@]}" -c 0 -- foo` / `-c -3 -- foo` / `-c abc -- foo` → stderr `invalid` / exit 2
- [ ] **T14_since_after_until**: `"${SS[@]}" -s 2026-06-30 -u 2026-06-01 -- foo` → stderr `since after until` / exit 2
- [ ] **T15_no_false_positive_tool_use**: `"${SS[@]}" 'tool_result_should_not_match'` → 0 件（jq 段で tool_result skip）
- [ ] **T15b_no_meta_match**: `"${SS[@]}" '2026-06-23'` → 0 件（awk が第5列のみ判定するため、DATE 列でヒットしない）
- [ ] **T17_max_results_exits_zero**: `"${SS[@]}" -n 1 -- a` → 1 行 / **exit 0**（SIGPIPE 141 にならない）
- [ ] **T18_broken_jsonl**: `"${SS[@]}" 'PHRASE_X'` → 2 件（broken.jsonl の good lines）/ exit 0
- [ ] **T19_invalid_glob**: `"${SS[@]}" -p 'foo|bar' -- foo` → stderr `invalid project glob` / exit 2
- [ ] **T20_no_projects_dir**: `CLAUDE_PROJECTS_DIR=/nonexistent ~/hermes-lite/bin/session-search.sh foo` → stderr `no projects dir` / exit 1
- [ ] **T24_skip_other_types**: `"${SS[@]}" 'meta_not_to_match'` → 0 件（attachment は抽出対象外）
- [ ] **T27_invalid_regex**: `"${SS[@]}" -- '['` → stderr `invalid regex` / exit 2
- [ ] **T28_text_with_tab_newline**: fixture に literal tab/newline を含む user content を追加し、検索しても 5 カラム TSV が崩れない
- [ ] **T30_legacy_fail_safe**: `"${SS[@]}" 'valid_legacy_PHRASE_Y'` → 1 件 / fail-safe skip された行はエラーを起こさない / exit 0

### 性能（acceptance criterion）

- [ ] **T26_perf_acceptance**: 実環境 `~/.claude/projects/` に対して `time ~/hermes-lite/bin/session-search.sh 'Phase 2' >/dev/null` が **5 秒以内**で完了する
  - 超過時の対応: 本 plan の一段化を撤回し、本 Issue 内で grep prefilter（`-F` 限定で復活）または FTS5 切替を検討

## smoke-test.sh の自動化対象

`features/5-fts5-claude-projects-jsonl-grep/smoke-test.sh` で以下を自動 assert する:

- T01 / T02 / T06 / T07 / T08 / T12 / T14 / T15 / T15b / T16 / T17 / T18 / T20 / T22 / T27 / T29 / T30

それ以外（T03 / T04 / T05 / T09 / T10 / T11 / T13 / T19 / T21 / T23 / T24 / T25 / T26 / T28）は手動チェック対象。
