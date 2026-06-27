# test-spec for #11 — Computer Use 再評価 retry

project_type: jobs → 自動テストフレームなし、手動チェックリスト運用。

## 前提セットアップ

- 作業ブランチ: `gloop/11-phase-3-10-followup-computer-use-retry`
- 作業ディレクトリ: `/home/shohei/hermes-lite`
- 入力 plan: `features/11-phase-3-10-followup-computer-use-retry/plan.md`
- 既存 research 資産: `features/10-phase-3-computer-use-api-claude-max-oauth-9/research/`
- gh API rate limit: 枯渇中、gh は呼ばない
- ALLOWED_TOOLS: 通常通り（probe.py は `python3` 直接実行で claude CLI を内部 spawn する）

## チェックリスト

### T01 probe 実行 + exit code 確認

- [ ] コマンド: `python3 features/10-phase-3-computer-use-api-claude-max-oauth-9/research/computer_use_probe.py approach-b > /tmp/probe_b_11.json; echo "EXIT=$?"`
- [ ] 期待値: exit code 0 + `/tmp/probe_b_11.json` が JSON parse 可能
- [ ] exit code != 0 or parse 不能 → 設計方針 #9 の synthetic JSON を生成して Case F として処理

### T02 sub_outcome 分類

- [ ] `/tmp/probe_b_11.json` の `sub_outcome` を Case A/A'/B/C/D/E/F に分類（設計方針 #3）
- [ ] 既知 enum に一致しなければ Case F（一意）
- [ ] 最終 outcome は 4 値 `<supported | conditional | unsupported | undetermined>` のいずれか

### T03 research-log の必須見出し名 grep

- [ ] `grep -Fxc '## 実行コマンド' features/11-.../research-log.md` が 1
- [ ] 同様に `## probe 出力 JSON` / `## 最終 outcome` / `## README 更新内容` / `## 再評価判断` / `## console 確認手順` / `## redaction 確認` が各 1 件
- [ ] `### legacy_sub_outcome` / `### 旧 #10 判定 supersede 履歴` が各 1 件

### T04 README 更新 (terminal outcome のみ)

**Case A/A'/B/C の場合**:
- [ ] 旧 H2 `^## 本 PR 実行時の最終判定（2026-06-27）$` が 1 件 (不変)
- [ ] `<!-- begin: #11-update -->` が 1 件 (冪等)
- [ ] `<!-- end: #11-update -->` が 1 件
- [ ] bounded block 内の新 outcome 行が `^- 最終 outcome:` の最初のヒット (grep -m1 で確認)
- [ ] `### 旧判定（#10 時点、superseded by #11）` が bounded block 内に 1 件
- [ ] 旧 bullet 4 行が `### 旧判定` 配下に移動

**Case D/E/F の場合**:
- [ ] `<!-- begin: #11-update -->` が 0 件 (README 完全不変)
- [ ] 旧 bullet 4 行が元の位置で不変

### T05 redaction 検査 (commit 前 + commit 後、POSIX ERE)

設計方針 #6-c のスクリプト相当を bash で実行:

```bash
PATTERNS=(
  'sk-ant-[A-Za-z0-9_-]+'
  '(^|[^A-Za-z])Bearer [A-Za-z0-9._-]+'
  '(^|[^A-Za-z])Authorization:[[:space:]]*[^[:space:]]'
  '(^|[^A-Za-z])Cookie:[[:space:]]*[^[:space:]]'
  '"request_id"[[:space:]]*:[[:space:]]*"req_[a-z0-9]+'
  '/home/shohei/'
  '"(oauthAccount|claudeAiOauth|access_token|accessToken)"'
  '"token"[^_]'
)
TARGETS=(features/11-phase-3-10-followup-computer-use-retry/research-log.md)
case "$CASE" in A|A\'|B|C) TARGETS+=(features/10-phase-3-computer-use-api-claude-max-oauth-9/research/README.md);; esac

# (a) commit 前
for f in "${TARGETS[@]}"; do
  for p in "${PATTERNS[@]}"; do
    if grep -qE "$p" "$f"; then echo "VIOLATION (pre-commit): $f / $p"; exit 1; fi
  done
done

# (b) commit 後
for f in "${TARGETS[@]}"; do
  for p in "${PATTERNS[@]}"; do
    if git show "HEAD:$f" 2>/dev/null | grep -qE "$p"; then echo "VIOLATION (post-commit): $f / $p"; exit 1; fi
  done
done
COMMIT_MSG=$(git log -1 --format=%B)
for p in "${PATTERNS[@]}"; do
  if echo "$COMMIT_MSG" | grep -qE "$p"; then echo "VIOLATION (commit msg): $p"; exit 1; fi
done
```

- [ ] 両段で violation なし

### T06 Case D 退化シナリオ (rate_limited)

`sub_outcome == rate_limited` (Case D) の場合のみ:

- [ ] research-log の「再評価判断」に `next_review_required: true` と `next_review_trigger:` が "none" 以外を含む
- [ ] README が完全不変 (T04 で確認済み)
- [ ] `grep -E '(永続|permanent|definitive)' features/11-.../research-log.md` が空
- [ ] `features/.intake/` に新規 issue-*.yaml がない (follow-up 起票なし)
- [ ] commit message が `Refs #11` を含み、`Closes #11` を含まない
- [ ] commit message に `partial_observation` を含む

### T07 commit message (trailer 固定 + Case 別本文)

- [ ] 成果物 commit (commit #1) の message に最終 outcome の 1 行要約を含む (例: `outcome=undetermined sub_outcome=rate_limited case=D`)
- [ ] `^Refs #11$` を含む
- [ ] `Closes #11` を含まない (全ケース共通)
- [ ] T05 (b) の secret 検査を通過
- [ ] Case D/E/F の場合: `partial_observation` を含む
- [ ] commit message に「Codex design blocking 6 件残置」を含む (rejection.md 参照記載)

### T08 legacy_sub_outcome フィールド分離

- [ ] `### legacy_sub_outcome` セクションが以下 6 フィールド全て含む:
  - `source_issue: 10`
  - `source_value: network_error`
  - `source_classification:` (文字列)
  - `reclassified_sub_outcome_for_issue_10: rate_limited` (固定値、T01 結果と独立)
  - `observed_sub_outcome_for_issue_11: <T01 結果>` (T01 と一致)
  - `mapping_rule:` に「truth table 行 12」を含む

### T09 finalize-feature no gh + commit 数 = 2

- [ ] `grep -E '(^|[^A-Za-z])gh([^A-Za-z]|$)' $HOME/.claude/skills/gloop-work/scripts/finalize-feature.mjs` が空
- [ ] finalize commit `chore(gloop): finalize features/11-...` のメッセージに `Closes` も `Refs` も trailer として含まれない
- [ ] push 後 `git log --oneline 264ff78..HEAD` で本フローが追加した commit が成果物 squash + finalize の 2 件 (中間 commit 含まず)

## test-summary.json (STEP 7 で Codex 入力に渡す)

```json
{
  "framework": "manual checklist",
  "test_spec_file": "features/11-phase-3-10-followup-computer-use-retry/test-spec.md",
  "automated_tests": "none",
  "manual_check_required": true,
  "checklist_items": 9,
  "case_dependent_items": ["T04", "T06"],
  "redaction_check": "pre_commit_and_post_commit_grep_2stage"
}
```
