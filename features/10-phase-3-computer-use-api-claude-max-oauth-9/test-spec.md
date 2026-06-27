# test-spec for #10 (project_type: jobs, 手動チェックリスト)

自動テストフレームなし。本ファイルが T01..T13 の単一ソース。実行者が手動で各 T-ID をチェックする。

すべての JSON 出力は plan.md の B-5 allowlist フィールドのみを含むこと（追加 field は禁止）。

## 前提セットアップ

```bash
cd features/10-phase-3-computer-use-api-claude-max-oauth-9
ls research/  # README.md, computer_use_probe.sh, computer_use_probe.py, cost_estimate.md があること
ls fixtures/  # 11 件の *.json があること
```

## T01: Approach A 実行 (`research/computer_use_probe.sh approach-a`)

### 前提セットアップ

- `claude` CLI が PATH に通っている
- インターネット接続あり（curl で docs.claude.com にアクセス）

### コマンド

```bash
bash research/computer_use_probe.sh approach-a
```

### 期待値

- [ ] stdout が allowlist JSON で、`approach="A"`, `outcome` (4 区分 enum), `sub_outcome`, `cli_help_has_betas_flag` (bool), `cli_probe_tool_use_observed` (bool), `stage` を含む
- [ ] exit code = 0
- [ ] 標準エラーに raw response body / Authorization / cookie / `/home/shohei` が出ない

## T02_supported_path: Approach B が 200 + tool_use + console subscription 確認

### 前提セットアップ

- `~/.claude/.credentials.json` が存在し、有効な OAuth access_token を含む
- Anthropic console (console.anthropic.com) にアクセスできる別ウィンドウ

### コマンド

1. console Usage 画面の `subscription_used` を記録（baseline）
2. `python3 research/computer_use_probe.py approach-b`
3. 15 分以内に console を再確認
4. baseline からの差分が subscription 側で increase していたら `--apply-console-confirm incremented_subscription --checked-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"` を probe.py に渡す（または stdout JSON を手で編集して billing_delta_class を更新）

### 期待値

- [ ] 最終 stdout JSON で `outcome="supported"`, `sub_outcome="tool_use_observed_and_subscription_billing"`
- [ ] `billing_observation="subscription_billing"`, `billing_delta_class="incremented_subscription"`
- [ ] `additional_turn_attempted=false` (B-4 Non-Goal)
- [ ] `tool_use_observed=true`, `stop_reason="tool_use"`
- [ ] `console_checked_at` が ISO 8601 UTC 文字列

## T02b_conditional_billing_unknown: 200 + tool_use あり、console 未確認 or unknown

### コマンド

`python3 research/computer_use_probe.py approach-b`（apply-console-confirm を呼ばない、または `--apply-console-confirm unknown`）

### 期待値

- [ ] `outcome="conditional"`, `sub_outcome="tool_use_observed_but_billing_unknown"`
- [ ] `billing_delta_class="unknown"`, `billing_observation="console_confirmation_required"`
- [ ] `console_checked_at=null`

## T02c_conditional_extra_usage: 200 + tool_use + console で extra_usage 増加 (Hermes #15080 同型)

### コマンド

T02 と同じ、ただし console 確認結果が extra_usage 増加だった場合に `--apply-console-confirm incremented_extra_usage` を渡す

### 期待値

- [ ] `outcome="conditional"`, `sub_outcome="extra_usage_billing"`
- [ ] `billing_delta_class="incremented_extra_usage"`, `billing_observation="extra_usage_billing"`

## T03_conditional_messages_api: 200 + tool_use なし

### コマンド

`python3 research/computer_use_probe.py --classify-fixture fixtures/200_end_turn.json`

### 期待値

- [ ] `outcome="conditional"`, `sub_outcome="messages_api_only"`, exit code 0

## T04a_unsupported_beta_not_allowed: 400 + invalid_request_error + "Computer Use is not available"

### コマンド

`python3 research/computer_use_probe.py --classify-fixture fixtures/400_beta_not_allowed.json`

### 期待値

- [ ] `outcome="unsupported"`, `sub_outcome="beta_not_allowed"`, `message_class="not_available"`, exit code 0

## T04b_unsupported_permission: 403 + permission_error

### コマンド

`python3 research/computer_use_probe.py --classify-fixture fixtures/403_permission.json`

### 期待値

- [ ] `outcome="unsupported"`, `sub_outcome="api_explicit_reject_after_auth"`, `message_class="permission"`, exit code 0

## T05_undetermined_auth: 401 / 403 with error.type != permission_error

### コマンド

```bash
python3 research/computer_use_probe.py --classify-fixture fixtures/401_auth.json
python3 research/computer_use_probe.py --classify-fixture fixtures/403_other.json
```

### 期待値

- [ ] 両方とも `outcome="undetermined"`, `sub_outcome="auth_failure"`, exit code 0

## T06_undetermined_timeout: 60 分 cap 超過

### コマンド

`python3 research/computer_use_probe.py --classify-fixture fixtures/5xx_timeout.json`

### 期待値

- [ ] `outcome="undetermined"`, `sub_outcome="timeout"` または `network_error`, exit code 0
- [ ] `elapsed_seconds`, `stage` が allowlist 内に記録

## T07_undetermined_probe_input: 400 + invalid_request_error + Computer Use 文言なし、または 400 + その他 error.type / null

### コマンド

```bash
python3 research/computer_use_probe.py --classify-fixture fixtures/400_invalid_request_other.json
python3 research/computer_use_probe.py --classify-fixture fixtures/400_other_error_type.json
python3 research/computer_use_probe.py --classify-fixture fixtures/400_null_error_type.json
```

### 期待値

- [ ] 3 件すべて `outcome="undetermined"`, `sub_outcome="probe_input_error"`, exit code 0
- [ ] 実機 probe フローのみリトライ 1 回（fixture モードはリトライしない）

## T08_undetermined_schema: credentials.json 不存在 or 未知 schema

### コマンド（破壊しないこと）

`~/.claude/.credentials.json` を退避させずに同等を再現するため、テスト用一時 JSON を渡す機能を probe.py に追加（`--credentials-override /tmp/test_cred.json`）か、または下記 fixture モードで近似:

`python3 research/computer_use_probe.py --classify-fixture fixtures/credential_missing.json`  ← optional. **本テストは実機との同期が難しいため、コード上の B-1 分岐が grep で確認できれば pass とする。**

### 期待値

- [ ] `grep -n "credential_missing\|credential_schema_unknown" research/computer_use_probe.py` で 2 分類が見えること
- [ ] `grep -n "sys.exit(1)" research/computer_use_probe.py` で B-1 emit 後に exit_code=1 で停止することを確認

## T09_cost_estimate: cost_estimate.md にレンジ + 仮定 + 感度分析が書かれる

### コマンド

`cat research/cost_estimate.md`

### 期待値

- [ ] 「概算オーダー」「確度: 低」「実機なし」のいずれかが文中に明記
- [ ] step ∈ {25, 50, 100}, cache_hit_rate ∈ {0, 50, 90}%, sessions/月 ∈ {30, 300} の感度分析テーブルがある
- [ ] pricing 取得 URL（docs.claude.com 系）が記載されている

## T10_secret_grep_extended: 機密情報の漏洩チェック（grep 対象限定）

### 対象範囲

- **対象**: `git ls-files features/10-*/research-log.md features/10-*/research/` のうち README.md / computer_use_probe.{sh,py} / cost_estimate.md を **除く** 実行生成ログ + Issue コメント全件
- **対象外**: `plan.md`、`research/README.md`、`research/computer_use_probe.{sh,py}`、`research/cost_estimate.md`、`test-spec.md`、`fixtures/*.json`

### コマンド

```bash
# Issue コメント
for n in 10 9; do gh issue view "$n" --comments --json comments -q '.comments[].body' > /tmp/issue_$n.txt; done

# research-log.md
cp features/10-phase-3-computer-use-api-claude-max-oauth-9/research-log.md /tmp/research-log.txt

# 実行生成ログ（存在すれば）
find features/10-phase-3-computer-use-api-claude-max-oauth-9/research -maxdepth 1 -type f \
  ! -name 'README.md' ! -name 'computer_use_probe.sh' ! -name 'computer_use_probe.py' \
  ! -name 'cost_estimate.md' \
  | xargs -I{} cat {} > /tmp/research_runtime.txt 2>/dev/null || touch /tmp/research_runtime.txt

# 検出パターン: 実際の token-shape のみマッチ（プレースホルダ <foo> や説明文の単語名はスルー）
# - sk-ant-...: Anthropic API key shape
# - eyJ...{20,}: JWT shape
# - Bearer <[A-Za-z0-9_.\-]{16,}> 16文字以上の token-shape のみ（プレースホルダは <,> を含むため不一致）
# - UUID v4 shape
# - /home/shohei に続けて / もしくは英数字 (ホームパスが真に展開された場合のみ。説明文の単独 `/home/shohei` は許容)
PATTERNS='(sk-ant-[A-Za-z0-9_-]{20,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]+|Bearer [A-Za-z0-9_.\-]{16,}|[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-4[A-Fa-f0-9]{3}-[89aAbB][A-Fa-f0-9]{3}-[A-Fa-f0-9]{12}|/home/shohei/[A-Za-z0-9._/-]+)'

grep -EH "$PATTERNS" /tmp/issue_10.txt /tmp/issue_9.txt /tmp/research-log.txt /tmp/research_runtime.txt \
  && echo "FAIL: leaks found above" || echo "PASS: no leaks"
```

### 期待値

- [ ] grep が `PASS: no leaks` を出力（ヒットしない）。プレースホルダ `<oauth_token>` や単語名「Authorization」「Bearer token」（実際の値を含まない）は許容

## T10b_code_dangerous_output_grep: コード成果物の危険出力経路チェック

### コマンド

```bash
# print / sys.stdout / sys.stderr / logging に対して response.text/content/headers/Authorization/token/request-id が直接渡されている記述だけを検出。
# 引数なしの "Authorization": f"Bearer {token}" のような HTTP ヘッダ構築は対象外（dict value 位置で urllib に渡るのみ、stdout には出ない）。
grep -nEH '(print|sys\.stdout\.write|sys\.stderr\.write|logging\.(debug|info|warn|error)|logger\.(debug|info|warn|error))\([^)]*(response\.(text|content)|\bheaders\b|\bAuthorization\b|\btoken\b|x-request-id)' \
  features/10-phase-3-computer-use-api-claude-max-oauth-9/research/computer_use_probe.py \
  features/10-phase-3-computer-use-api-claude-max-oauth-9/research/computer_use_probe.sh \
  && echo "FAIL: dangerous output paths found above" || echo "PASS: no dangerous output paths"
```

### 期待値

- [ ] grep が `PASS: no dangerous output paths` を出力（ヒットしない）

## T11_conclusion_comment: Issue 最終コメント + クロスポスト

### 期待値

- [ ] Issue #10 に Approach A / B / C / 結論 の 4 件以上のコメントが allowlist JSON で残る
- [ ] Issue #9 へクロスポストコメント 1 件が残る
- [ ] 結論コメントに以下 4 項目が allowlist フィールドで含まれる:
  - 最終 outcome (4 区分 enum + sub_outcome)
  - 3 択判定 (a / b / c / 判定不能)
  - コード去就 (keep + 理由)
  - #9 推奨アクション

## T12_state_invariants: state.json 既存キー保持

### コマンド

```bash
# 更新前 snapshot
jq -S . features/10-phase-3-computer-use-api-claude-max-oauth-9/state.json > /tmp/state_before.json

# state.mjs で final_review / merge を passed に
node "$HOME/.claude/skills/gloop-work/scripts/state.mjs" set \
  features/10-phase-3-computer-use-api-claude-max-oauth-9/state.json phases.final_review passed
node "$HOME/.claude/skills/gloop-work/scripts/state.mjs" set \
  features/10-phase-3-computer-use-api-claude-max-oauth-9/state.json phases.merge passed

# 差分検証
jq -S . features/10-phase-3-computer-use-api-claude-max-oauth-9/state.json > /tmp/state_after.json
diff <(jq -S 'del(.updated_at, .phases.final_review, .phases.merge)' /tmp/state_before.json) \
     <(jq -S 'del(.updated_at, .phases.final_review, .phases.merge)' /tmp/state_after.json) \
  && echo "PASS: invariant keys preserved"
```

### 期待値

- [ ] diff が空（許可差分は `updated_at` と `phases.final_review` / `phases.merge` のみ）
- [ ] `PASS: invariant keys preserved` が出力

## T13_classify_fixture: 11 件 fixture と truth table 一致

### コマンド

```bash
# 各 fixture について classify-fixture で実行し、期待値と一致するかチェック
declare -A EXPECT=(
  [200_tool_use]="conditional:tool_use_observed_but_billing_unknown:0"
  [200_end_turn]="conditional:messages_api_only:0"
  [200_other_stop_reason]="conditional:messages_api_only:0"
  [400_beta_not_allowed]="unsupported:beta_not_allowed:0"
  [400_invalid_request_other]="undetermined:probe_input_error:0"
  [400_other_error_type]="undetermined:probe_input_error:0"
  [400_null_error_type]="undetermined:probe_input_error:0"
  [401_auth]="undetermined:auth_failure:0"
  [403_permission]="unsupported:api_explicit_reject_after_auth:0"
  [403_other]="undetermined:auth_failure:0"
  [5xx_timeout]="undetermined:timeout:0"  # network_error も許容
  [429_rate_limit]="undetermined:rate_limited:0"
)

pass=0; fail=0
for name in "${!EXPECT[@]}"; do
  out=$(python3 research/computer_use_probe.py --classify-fixture "fixtures/${name}.json")
  ec=$?
  o=$(echo "$out" | jq -r .outcome)
  s=$(echo "$out" | jq -r .sub_outcome)
  IFS=':' read -r EO ES EC <<< "${EXPECT[$name]}"
  if [ "$o" = "$EO" ] && { [ "$s" = "$ES" ] || ([ "$name" = "5xx_timeout" ] && [ "$s" = "network_error" ]); } && [ "$ec" = "$EC" ]; then
    pass=$((pass+1))
  else
    fail=$((fail+1))
    echo "FAIL: $name expected $EO/$ES/$EC got $o/$s/$ec"
  fi
done
echo "T13 pass=$pass fail=$fail (expect pass=12 fail=0)"
```

### 期待値

- [ ] `T13 pass=12 fail=0`
