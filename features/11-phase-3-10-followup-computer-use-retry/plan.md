# plan: #11 [Phase 3] #10 follow-up: Computer Use 再評価 (sub_outcome=rate_limited 後リトライ)

slug: phase-3-10-followup-computer-use-retry
milestone: -
labels: type:chore
flow: light
project_type: jobs

## In-Scope / Out-of-Scope

| In-Scope | Out-of-Scope |
|---|---|
| `features/10-phase-3-computer-use-api-claude-max-oauth-9/research/computer_use_probe.py approach-b` を **1 回だけ** 再実行（precondition なし、シンプル実行。根拠は設計方針 #1） | probe.py / probe.sh / cost_estimate.md の挙動変更（読み取りのみ） |
| `features/11-.../research-log.md` を **常に新規作成**（観測 1 件追加自体が成果物。Case D/E/F でも作成する） | 追加 follow-up Issue の自動起票 |
| `features/10-.../research/README.md` の **bounded block 形式での更新**: **Case A/A'/B/C (terminal outcome) の場合のみ実施**、Case D/E/F では README 更新しない（**ラウンド 4 contrarian H1 / migration H2 対応**）。block 内に旧 #10 bullet 4 行を superseded 表記で含めて置換することで旧結論の grep ヒットを排除（**ラウンド 4 migration H1 対応**） | Case D/E/F での README 上書き |
| 200 + tool_use が出た場合に限り、`--apply-console-confirm` 呼び出しコマンド例を research-log.md に記載 | console での subscription quota 差分確認そのもの |
| squash commit + `git push origin main`（commit trailer は **常に `Refs #11`**、Closes は使わない）。成果物 commit = 1 個、finalize-feature commit = 1 個の **計 2 commit、責務分離** を設計方針 #7-b で明示（**ラウンド 4 architect H2 対応**） | Issue #11 の自動 close、gh issue comment/close 呼び出し |
| Case A/A'/B/C 確定時、README bounded block 内で #9 と #10 への結論影響を 1 行ずつ明示 | #9 本体 Issue の本文編集 |
| 既存関数編集なし、README 更新は **手動編集（implementer teammate が直接 Edit）**（**ラウンド 4 architect M3 対応**） | スクリプト化された README 自動 patch ツールの新規作成 |

## Non-Goals

- Computer Use を本番経路（`gateway/discord/` 等）に組み込むこと
- billing_delta_class を実機計測で確定すること
- Approach C pricing 再取得・cost_estimate.md の数値更新
- 別 Anthropic account / 別 OAuth credential での再実行
- rate limit window 計測やバックオフ秒数のチューニング
- 「rate_limited は永続的に判定不能」と結論付けること
- precondition cooldown による probe 実行抑止
- Issue #11 の自動 close
- Case D/E/F での README 結論上書き表示（観測のみ research-log に残す）

## 設計方針

### 1. 再実行は 1 回限り、precondition なし

precondition は設けない（**ラウンド 3 全 persona 共通要求**）。**ラウンド 4 contrarian H2 の反論への明示的譲歩**:

- 「無駄打ち」リスクは認める（前回 429 直後で再 429 の可能性あり）
- ただし「観測 1 件追加」自体は research-log に残す価値あり（時刻 + 結果の事実観測）
- precondition を設けるには Anthropic 側 rate_limit window 仕様の確認が必要だが、それは Non-Goals
- 代替案として contrarian が提案した「`blocked: rate_limit window unknown` の research-log だけ作成」は **採用しない**（観測機会を失う、価値が小さい）
- → シンプルに 1 回実行、結果に応じて分岐

### 2. probe.py の exit code は実行結果で判定

事前 grep 契約確認は false positive を許すため削除。T01 で `exit_code` を実行結果から取得し、0 以外なら設計方針 #9 の synthetic JSON を Case F として処理。

### 3. sub_outcome enum と最終 outcome マッピング（4 値、Case 分類）

| ケース | sub_outcome enum | 最終 outcome (4 値) | terminal? | README 更新? |
|---|---|---|---|---|
| A | `supported_with_billing_unknown` | `supported` | **yes** | **yes** |
| A' | `tool_use_observed_with_billing_confirmed` | `supported` | **yes** | **yes** |
| B | `permission_denied` | `unsupported` | **yes** | **yes** |
| C | `beta_not_allowed` | `conditional` | **yes** | **yes** |
| D | `rate_limited` | `undetermined` | no | **no** |
| E | `network_error` / `credential_schema_unknown` / `usage_schema_unknown` (既知異常 enum) | `undetermined` | no | **no** |
| F | 上記 A〜E 以外の任意 enum (`probe_exit_code_nonzero` / `probe_parse_error` / 未知値) | `undetermined` | no | **no** |

**T02 判定境界**: 既知 enum (A〜E) に一致しなければ Case F に分類（一意）。

**Issue body 完了条件との関係**: terminal Case (A/A'/B/C) のみ Issue 完了条件達成。Case D/E/F は `needs-followup` 状態として研究継続（research-log の `next_review_required: true`）。**ラウンド 4 migration H2 対応**: Case D/E/F は plan の終了状態として `success` ではなく `partial_observation` を report し、後続手動操作が必須であることを commit message と research-log に明記。

#### README 追記文言の具体例（Case 別、commit時に決定）

| Case | 追記文言（READMEbounded block 内の outcome 行） |
|---|---|
| A | `最終 outcome: **\`supported / supported_with_billing_unknown\`**`、「#9 で再利用可。再評価 expiry: <merge 日 + 90 日>」 |
| A' | `最終 outcome: **\`supported / tool_use_observed_with_billing_confirmed\`**`、「#9 で再利用可（billing 確認済）」 |
| B | `最終 outcome: **\`unsupported / permission_denied\`**`、「明示拒否確認済 (403)、再利用禁止」 |
| C | `最終 outcome: **\`conditional / beta_not_allowed\`**`、「beta 未許可、条件付き再評価可能」 |

### 4. 禁止語

ケース D 以下の `undetermined` 文脈で commit message / research-log に **使わない語**:

- `永続`、`permanent`、`definitive`（日本語/英語両方、3 語のみ）

「最終 outcome」「final outcome」は対象外。T06 は上記 3 語のみ grep 検査。

### 5. README 更新運用（**terminal outcome のみ、bounded block で旧 bullet 含めて置換**）

#### 5-a. Case D/E/F の場合: README 完全不変

`features/10-.../research/README.md` には一切手を入れない。最新観測は research-log のみに記録。これにより:

- Issue 完了条件未達の状態が README 上の「結論更新」として誤って公開されない（**ラウンド 4 contrarian H1 / migration H2 対応**）
- 旧 #10 bullet 4 行が依然として最新公開状態（次回 terminal outcome 確定まで temporary state を維持）

#### 5-b. Case A/A'/B/C の場合: bounded block で旧 bullet 含めて置換

既存 H2 見出し `## 本 PR 実行時の最終判定（2026-06-27）` 自体は変更しない（grep / anchor 互換）。

H2 直下の **旧 bullet 4 行も bounded block の管理範囲に含める**:

before:

```markdown
## 本 PR 実行時の最終判定（2026-06-27）

- 最終 outcome: **`undetermined / network_error`**（実態は HTTP 429 rate_limit_error、OAuth 認証は通過済み）
- 再利用条件: **再評価必須、現状値は無効**
- follow-up Issue: **#11** （rate_limit クールダウン後リトライ）
- #9 への推奨: **保留**（OAuth 経路は通ったが Computer Use 可否は未確認）
```

after (Case A 例):

```markdown
## 本 PR 実行時の最終判定（2026-06-27）

<!-- begin: #11-update -->

**※#11 で更新あり**（更新日: `2026-06-27T07:25:00Z`）:

- 最終 outcome: **`supported / supported_with_billing_unknown`**
- supersedes #10 conclusion (互換マッピング: 旧 `undetermined / network_error` → 新 `supported / supported_with_billing_unknown`、legacy 詳細は research-log の `legacy_sub_outcome` 参照)
- 再利用条件: **#9 で再利用可。再評価 expiry: 2026-09-25**
- #9 への推奨: **採用可**（OAuth 経路で Computer Use beta 利用可能を確認）
- 詳細: `features/11-phase-3-10-followup-computer-use-retry/research-log.md`

### 旧判定（#10 時点、superseded by #11）

- 最終 outcome: **`undetermined / network_error`**（実態は HTTP 429 rate_limit_error、OAuth 認証は通過済み）
- 再利用条件: **再評価必須、現状値は無効**
- follow-up Issue: **#11** （rate_limit クールダウン後リトライ）
- #9 への推奨: **保留**（OAuth 経路は通ったが Computer Use 可否は未確認）

<!-- end: #11-update -->
```

これにより:

- 既存 H2 anchor / 見出しは無傷
- **旧 bullet は bounded block 内の `### 旧判定（#10 時点、superseded by #11）` 配下に移動**。grep `^- 最終 outcome:` した場合、新 outcome が先にヒットする（旧結論が誤読されない、**ラウンド 4 migration H1 対応**）
- bounded block は冪等に replace 可能（再実行時は block 全体を新 outcome で書き換える）

#### 5-c. 冪等挿入アルゴリズム

```
1. README.md を読む
2. terminal outcome (Case A/A'/B/C) でない → 終了（何もしない）
3. terminal outcome の場合:
   a. `<!-- begin: #11-update -->` 〜 `<!-- end: #11-update -->` の bounded block が存在する場合:
      - block 全体を新 outcome の内容で **置換**
   b. 存在しない場合:
      - `## 本 PR 実行時の最終判定（2026-06-27）` H2 直下の bullet 4 行を **bounded block 内の `### 旧判定` セクションへ移動**
      - bounded block を H2 直下に挿入
4. README.md を書き戻す
```

### 6. redaction（**POSIX 表現に統一**、**probe 出力は構造化 parse**、ラウンド 4 contrarian M1 / migration M2 対応）

#### 6-a. 生成元の安全性確保（contrarian M1 反映）

probe.py が emit する JSON を research-log に書き込む前に、**JSON parse → B-5 allowlist key だけ抽出 → 整形** する:

```python
ALLOWED_KEYS = {"approach", "outcome", "sub_outcome", "status", "exit_code",
                "redacted_error_type", "stage", "model_used", "usage_token_counts",
                "console_checked_at", "billing_observation", "billing_delta_class",
                "console_window_minutes", "elapsed_seconds", "notes", "message_class",
                "tool_use_observed", "stop_reason"}
data = json.load(open("/tmp/probe_b_11.json"))
safe = {k: v for k, v in data.items() if k in ALLOWED_KEYS}
# safe を research-log に書く
```

これにより、probe.py が将来 unknown key を加えても research-log には漏れない。

#### 6-b. grep 補助検査（POSIX ERE 互換、grep -E 統一）

| # | 禁止対象 | regex (POSIX ERE, `[[:space:]]` `[^[:space:]]` 使用) |
|---|---|---|
| 1 | OAuth token prefix | `sk-ant-[A-Za-z0-9_-]+` |
| 2 | Bearer スキーム | `(^\|[^A-Za-z])Bearer [A-Za-z0-9._-]+` |
| 3 | Authorization ヘッダ右辺 | `(^\|[^A-Za-z])Authorization:[[:space:]]*[^[:space:]]` |
| 4 | Cookie ヘッダ右辺 | `(^\|[^A-Za-z])Cookie:[[:space:]]*[^[:space:]]` |
| 5 | request_id raw | `"request_id"[[:space:]]*:[[:space:]]*"req_[a-z0-9]+` |
| 6 | 絶対パス | `/home/shohei/` |
| 7a | OAuth credential JSON top-level キー名（completionキーのみ） | `"(oauthAccount\|claudeAiOauth\|access_token\|accessToken)"` |
| 7b | bare `"token"` キー（`"token_*"` `usage_token_counts` を除外、後続が `_` でないことを確認） | `"token"[^_]` （後続が `_` 以外、JSON 内では `"token":` のように `:` が続くため衝突しない） |

#### 6-c. 検査タイミング（commit 前 + commit 後、ラウンド 2 から継承）

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
TARGETS=(
  features/11-phase-3-10-followup-computer-use-retry/research-log.md
)
# Case A/A'/B/C のみ README も TARGETS に追加
if [ "$CASE" = "A" ] || [ "$CASE" = "A'" ] || [ "$CASE" = "B" ] || [ "$CASE" = "C" ]; then
  TARGETS+=("features/10-phase-3-computer-use-api-claude-max-oauth-9/research/README.md")
fi

# (a) commit 前
for f in "${TARGETS[@]}"; do
  for p in "${PATTERNS[@]}"; do
    if grep -qE "$p" "$f"; then echo "REDACTION VIOLATION (pre-commit): $f / $p"; exit 1; fi
  done
done

# (b) commit 後
for f in "${TARGETS[@]}"; do
  for p in "${PATTERNS[@]}"; do
    if git show "HEAD:$f" 2>/dev/null | grep -qE "$p"; then echo "REDACTION VIOLATION (post-commit): $f / $p"; exit 1; fi
  done
done
COMMIT_MSG=$(git log -1 --format=%B)
for p in "${PATTERNS[@]}"; do
  if echo "$COMMIT_MSG" | grep -qE "$p"; then echo "REDACTION VIOLATION (commit msg): $p"; exit 1; fi
done
```

`console_check_required` は `notes` フィールドに自然文記述（独立フィールド作らない）。

### 7. Issue close 経路と commit モデル（**Refs 固定、commit 数 = 2 を明示**、ラウンド 4 architect H1/H2 対応）

#### 7-a. trailer 固定

commit message trailer は outcome に関係なく **常に `Refs #11`**。`Closes` は使わない（理由はラウンド 3 で確立、Issue コメント無しの自動 close を抑止）。

#### 7-b. commit 数と責務分離（architect H2 対応）

本フローは **2 個の commit** を作る:

| commit # | 種類 | 作成者 | message | redaction/Refs 検査対象? |
|---|---|---|---|---|
| 1 | 成果物 squash commit | STEP 8（人間 or orchestrator） | `chore: ... outcome=X sub_outcome=Y case=Z\n\nRefs #11` | **yes** |
| 2 | finalize メタ commit | `finalize-feature.mjs` | `chore(gloop): finalize features/11-...` | **no**（メタのみ、outcome 情報なし、trailer なし） |

検査責務:

- **redaction 検査**は commit #1 の本体ファイル + commit message のみ対象（finalize メタ commit は変更ファイルが既に redaction pass 済み）
- **`Refs #11` trailer 検査**は commit #1 のみ（finalize commit は trailer 不要）
- **`Closes` 不存在検査**は両 commit を対象（finalize commit も `Closes` を含まないことを T09 で確認、二重 close trigger 防止）

両 commit を **1 回の push** で main に送る。

#### 7-c. single source of truth の現実（architect H1 対応の明示訂正）

旧 plan で「Issue は single source of truth」と書いたが、現状の実態は以下:

- **research-log.md** = 観測事実の single source of truth（変更不可な事実）
- **README.md** = 最新 outcome の公開ミラー（Case A/A'/B/C 確定時のみ更新、terminal でない場合は旧結論を維持）
- **Issue #11** = 索引・通知用（コメント追加は rate limit 復帰後の人間判断）

この実態を本 plan で明示する。Issue は索引、研究事実は research-log、公開最新値は README、という三層構造。

### 8. legacy_sub_outcome 構造（フィールド分離維持）

```yaml
legacy_sub_outcome:
  source_issue: 10
  source_value: network_error
  source_classification: "その他 status fallback (probe.py 初版)"
  reclassified_sub_outcome_for_issue_10: rate_limited
  observed_sub_outcome_for_issue_11: <T01 結果>
  mapping_rule: "truth table 行 12 (post-update, #10 codex final round 2 追加)"
```

### 9. probe_exit_code_nonzero / probe_parse_error の synthetic JSON

probe.py が exit 0 以外で返ってきた、または stdout が JSON parse 不能の場合、本ジョブが synthetic JSON を直接 research-log.md に追記:

```json
{
  "approach": "B",
  "outcome": "undetermined",
  "sub_outcome": "probe_exit_code_nonzero",
  "status": null,
  "exit_code": "<実際の非 0 値>",
  "redacted_error_type": "probe_contract_violation",
  "stage": "approach_b_request",
  "model_used": null,
  "usage_token_counts": {},
  "console_checked_at": null,
  "billing_observation": "not_applicable",
  "billing_delta_class": "not_applicable",
  "console_window_minutes": 15,
  "elapsed_seconds": 0,
  "notes": "synthetic JSON generated by #11 job due to probe.py exit code violation",
  "message_class": "other",
  "tool_use_observed": false,
  "stop_reason": null
}
```

`probe_parse_error` の場合は `sub_outcome` だけ `probe_parse_error` に変える。両者とも Case F として処理、research-log のみ作成、README 不変。

## 実装対象

### A) `features/11-phase-3-10-followup-computer-use-retry/research-log.md`（新規作成）

**必須見出し（grep -F で存在確認、セクション数固定ではなく見出し名固定。ラウンド 4 contrarian L1 対応）**:

`^## ` レベル必須:
- `## 実行コマンド`
- `## probe 出力 JSON`
- `## 最終 outcome`
- `## README 更新内容`
- `## 再評価判断`
- `## console 確認手順`
- `## redaction 確認`

`^### ` レベル必須:
- `### legacy_sub_outcome`
- `### 旧 #10 判定 supersede 履歴`

各セクションの中身は plan の Case 別具体例を参照。

#### Case A の完成後 research-log 全体例（**ラウンド 4 migration M1 対応**）

```markdown
# Issue #11 research-log

## 実行コマンド

```
python3 features/10-phase-3-computer-use-api-claude-max-oauth-9/research/computer_use_probe.py approach-b > /tmp/probe_b_11.json
```

## probe 出力 JSON

```json
{
  "approach": "B",
  "outcome": "supported",
  "sub_outcome": "supported_with_billing_unknown",
  "status": 200,
  "exit_code": 0,
  "redacted_error_type": null,
  "stage": "approach_b_response",
  "model_used": "claude-sonnet-4-5",
  "usage_token_counts": {"input_tokens": 123, "output_tokens": 45},
  "console_checked_at": null,
  "billing_observation": "subscription_quota_unconfirmed",
  "billing_delta_class": "pending_human_console_check",
  "console_window_minutes": 15,
  "elapsed_seconds": 4,
  "notes": "console_check_required=true",
  "message_class": "tool_use",
  "tool_use_observed": true,
  "stop_reason": "tool_use"
}
```

## 最終 outcome

- outcome: supported
- sub_outcome: supported_with_billing_unknown
- case: A
- 確定根拠: 設計方針 #3 enum 表 Case A

### legacy_sub_outcome

- source_issue: 10
- source_value: network_error
- source_classification: "その他 status fallback (probe.py 初版)"
- reclassified_sub_outcome_for_issue_10: rate_limited
- observed_sub_outcome_for_issue_11: supported_with_billing_unknown
- mapping_rule: "truth table 行 12 (post-update, #10 codex final round 2 追加)"

## README 更新内容

（5-b の after スニペットを Case A の値で展開した bounded block 全文）

## 再評価判断

- next_review_required: false
- next_review_trigger: none
- 注: terminal outcome のため再評価不要。ただし re-evaluation expiry は 90 日 (2026-09-25)。

## console 確認手順（Case A のみ）

```
cat /tmp/probe_b_11.json | python3 features/10-.../research/computer_use_probe.py \
  --apply-console-confirm incremented_subscription \
  --checked-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

console で subscription quota 差分を 15 分以内に確認したら、上記コマンドで billing 情報をマージする（人間操作）。

## redaction 確認

- 設計方針 #6-a の禁止対象 7 系列 (実 8 パターン) が本ファイルに含まれないこと: confirmed
- 検査タイミング: 6-c (a) commit 前 grep + (b) commit 後 git show grep の両方を通過

### 旧 #10 判定 supersede 履歴

- #10 PR 最終 outcome: undetermined / network_error → undetermined / rate_limited に post-update 再分類（commit 264ff78 時点）
- #11 ジョブ実行で観測した新 outcome: supported / supported_with_billing_unknown
- supersede 履歴の保持先: 本 research-log.md（README 側は最新 outcome のみ）
```

#### Case D の完成後 research-log 全体例

```markdown
# Issue #11 research-log

## 実行コマンド

```
python3 features/10-phase-3-computer-use-api-claude-max-oauth-9/research/computer_use_probe.py approach-b > /tmp/probe_b_11.json
```

## probe 出力 JSON

```json
{
  "approach": "B",
  "outcome": "undetermined",
  "sub_outcome": "rate_limited",
  "status": 429,
  "exit_code": 0,
  "redacted_error_type": "rate_limit_error",
  "stage": "approach_b_request",
  "model_used": "claude-sonnet-4-5",
  "usage_token_counts": {},
  "console_checked_at": null,
  "billing_observation": "not_applicable",
  "billing_delta_class": "not_applicable",
  "console_window_minutes": 15,
  "elapsed_seconds": 1,
  "notes": "",
  "message_class": "other",
  "tool_use_observed": false,
  "stop_reason": null
}
```

## 最終 outcome

- outcome: undetermined
- sub_outcome: rate_limited
- case: D
- 確定根拠: 設計方針 #3 enum 表 Case D

### legacy_sub_outcome

- source_issue: 10
- source_value: network_error
- source_classification: "その他 status fallback (probe.py 初版)"
- reclassified_sub_outcome_for_issue_10: rate_limited
- observed_sub_outcome_for_issue_11: rate_limited
- mapping_rule: "truth table 行 12 (post-update, #10 codex final round 2 追加)"

## README 更新内容

Case D のため README は更新しない（設計方針 #5-a）。旧 #10 結論を temporary state として維持。

## 再評価判断

- next_review_required: true
- next_review_trigger: external_quota_change_or_separate_account_or_offhours_retry
- 注: 今回の自動ジョブでも rate_limited、判定不能。外部条件変化後に手動で再評価。

## console 確認手順（Case A のみ）

該当なし。

## redaction 確認

- 設計方針 #6-a の禁止対象 7 系列 (実 8 パターン) が本ファイルに含まれないこと: confirmed
- 検査タイミング: 6-c (a) commit 前 grep + (b) commit 後 git show grep の両方を通過

### 旧 #10 判定 supersede 履歴

- #10 PR 最終 outcome: undetermined / network_error → undetermined / rate_limited に post-update 再分類（commit 264ff78 時点）
- #11 ジョブ実行で観測した新 outcome: undetermined / rate_limited（再度同じ結果）
- supersede 履歴の保持先: 本 research-log.md（README 側は最新 outcome のみ）
```

### B) `features/10-phase-3-computer-use-api-claude-max-oauth-9/research/README.md`（terminal outcome 時のみ改修）

Case A/A'/B/C の場合: 設計方針 #5-b の冪等アルゴリズムで bounded block を旧 bullet 含めて置換。
Case D/E/F の場合: README 完全不変。

#### Case A 適用後の README 該当セクション完成例

設計方針 #5-b の「after (Case A 例)」スニペットそのまま。

#### Case D の場合の README 該当セクション完成例

旧 README から変化なし（**ラウンド 4 contrarian H1 / migration H2 対応**）。

### C) 成果物 commit message の完成例（**ラウンド 4 migration M1 対応**）

#### Case A の場合

```
chore(research): #11 Computer Use 再評価 — outcome=supported sub_outcome=supported_with_billing_unknown case=A

approach-b probe を 1 回再実行した結果、HTTP 200 + tool_use を観測した。
- features/11-phase-3-10-followup-computer-use-retry/research-log.md: 観測ログ新規作成
- features/10-.../research/README.md: bounded block で旧 #10 判定 (undetermined / network_error) を superseded として置換、新 outcome (supported / supported_with_billing_unknown) を最新値として公開
- legacy_sub_outcome により #10 post-update 再分類 (rate_limited) と #11 新観測 (supported_with_billing_unknown) を独立フィールドで保持

Issue #11 完了条件達成。コメント投稿と Issue close は rate limit 復帰後に人間が手動実施。

Refs #11
```

#### Case D の場合

```
chore(research): #11 Computer Use 再評価 — outcome=undetermined sub_outcome=rate_limited case=D partial_observation

approach-b probe を 1 回再実行した結果、再度 HTTP 429 rate_limit_error を観測した。
- features/11-phase-3-10-followup-computer-use-retry/research-log.md: 観測ログ新規作成、next_review_required=true
- features/10-.../research/README.md: 未変更 (Case D は terminal outcome ではないため、設計方針 #5-a)
- needs-followup 状態。外部条件変化後に手動再評価が必要。

Issue #11 完了条件未達 (terminal outcome に到達せず)。

Refs #11
```

## テスト計画（手動チェックリスト、project_type=jobs）

**T01_run_probe**（実行 + exit code 確認）

- `python3 features/10-.../research/computer_use_probe.py approach-b > /tmp/probe_b_11.json; echo "EXIT=$?"`
- exit code を記録（0 が期待、非 0 なら設計方針 #9 で synthetic JSON 生成）
- `/tmp/probe_b_11.json` が JSON parse できる（parse 不能なら `probe_parse_error` synthetic JSON）

**T02_classify**（4 値 outcome、Case 一意分類）

- 出力 JSON の `sub_outcome` が enum 表 Case A 〜 E のいずれかに完全一致、それ以外は Case F に分類
- 最終 outcome は 4 値 `<supported | conditional | unsupported | undetermined>` のいずれか
- Case F でも例外停止せず research-log に「未知 sub_outcome」と明示

**T03_research_log_headings**（必須見出し名 grep、**ラウンド 4 contrarian L1 対応**）

- `grep -Fxc '## 実行コマンド' features/11-.../research-log.md` が 1
- 同様に `## probe 出力 JSON` / `## 最終 outcome` / `## README 更新内容` / `## 再評価判断` / `## console 確認手順` / `## redaction 確認` の各見出しがそれぞれ 1 件
- `### legacy_sub_outcome` / `### 旧 #10 判定 supersede 履歴` も各 1 件

セクション数の固定検査は行わない（説明追加に強い構造）。

**T04_readme_update**（terminal outcome 限定 + bounded block 冪等 + 旧 bullet 移動）

- 旧 H2 見出し `^## 本 PR 実行時の最終判定（2026-06-27）$` の grep 結果が **1 件**（不変）
- **Case A/A'/B/C の場合のみ**:
  - bounded block 開始マーカー `<!-- begin: #11-update -->` が **1 件**（冪等、重複なし）
  - bounded block 終了マーカー `<!-- end: #11-update -->` が **1 件**
  - bounded block 内の **新 outcome 行** (`^- 最終 outcome: \*\*\`<outcome> / <sub_outcome>\`\*\*`) が、旧 H2 内で **最初にヒット**する `- 最終 outcome:` であること（**ラウンド 4 migration H1 対応**、grep -m1 で確認）
  - `### 旧判定（#10 時点、superseded by #11）` が bounded block 内に **1 件**
  - 旧 bullet 4 行が `### 旧判定` 配下に **移動**している（重複追記なし、移動のみ）
- **Case D/E/F の場合**:
  - bounded block マーカー `<!-- begin: #11-update -->` が **0 件**（README は完全不変、**ラウンド 4 contrarian H1 / migration H2 対応**）
  - 旧 bullet 4 行が元の位置で不変

**T05_redaction**（2 段検査、POSIX ERE 統一）

設計方針 #6-c のスクリプトを実行 (8 パターン、commit 前 + commit 後 + commit message)。違反 0 で pass。

**T06_boundary_rate_limited**（Case D、永続表現禁止、partial_observation 状態）

sub_outcome が `rate_limited` (Case D) の場合:

- research-log の「再評価判断」セクションに `next_review_required: true` かつ `next_review_trigger` が "none" でない値を含む
- README 不変（T04 でも検証）
- `grep -E '(永続|permanent|definitive)' features/11-.../research-log.md` の結果が **空**
- 追加 follow-up Issue が起票されていない（`features/.intake/` に新規 yaml なし）
- commit message が:
  - `Refs #11` を含み、`Closes #11` を含まない
  - `partial_observation` を含む（terminal でないことの明示、**ラウンド 4 migration H2 対応**）
- `git push origin main` は実行する（観測ログ追加自体が価値、ラウンド 4 contrarian H3 への対応として「research-log 追加は terminal でなくとも価値あり」を In-Scope で明示済み）

**T07_commit_message**（trailer 固定 = Refs、Case 別本文）

成果物 squash commit (commit #1) の message が:

- 最終 outcome の 1 行要約を含む（例: `outcome=undetermined sub_outcome=rate_limited case=D`）
- `Refs #11` を含む（行頭 `^Refs #11$`）
- `Closes #11` を含まない（全ケース共通）
- T05 (b) と同じ secret 検査を通過
- Case D/E/F の場合: `partial_observation` 文字列を含む

**T08_legacy_mapping**（フィールド分離維持）

`features/11-.../research-log.md` の `### legacy_sub_outcome` セクションが以下 6 フィールド全て含む:

- `source_issue: 10`
- `source_value: network_error`
- `source_classification:`
- `reclassified_sub_outcome_for_issue_10: rate_limited` (固定値)
- `observed_sub_outcome_for_issue_11: <T01 結果>`
- `mapping_rule:` に「truth table 行 12」を含む

**T09_finalize_feature_no_gh + commit 数 = 2 検証**（**ラウンド 4 architect H2 対応**）

- `grep -E '(^|[^A-Za-z])gh([^A-Za-z]|$)' $HOME/.claude/skills/gloop-work/scripts/finalize-feature.mjs` が空（gh 呼び出しなし）
- finalize commit `chore(gloop): finalize features/11-...` のメッセージに `Closes` も `Refs` も trailer として含まれない
- push 後 main に **本フローが追加した commit が正確に 2 個**（成果物 squash + finalize）。これを `git log --oneline origin/main..HEAD` (push 前) で 2 件確認、push 後は `git log --oneline 264ff78..HEAD` (#10 マージ commit から) で本フロー 2 件 + 中間 commit 等を確認

## Issue body 抜粋 と 完了条件正規化

#11 本文 — `gh issue view 11` で取得済み。本 plan での Issue body 完了条件の解釈:

| Issue body の条件 | 本 plan の解釈 |
|---|---|
| 「Approach B が 429 以外のレスポンスを返す」 | 必須ではない。Case D (429 再発) も plan の終了状態として許容、ただし `partial_observation` 扱いで Issue 完了条件未達 |
| 「最終 outcome が `supported` / `conditional` / `unsupported` のいずれかに確定」 | 4 値 outcome 維持。Case A/A' → supported, B → unsupported, C → conditional、これらのみ Issue 完了条件達成 |
| 「結果を本 Issue にコメントし、#10 の結論を上書きする形で確定」 | gh rate limit のため自動コメントは Out-of-Scope。代わりに research-log + (terminal の場合のみ) README bounded block で代替。Issue は常に open のまま、rate limit 復帰後の人間判断 (コメント + 手動 close) に委ねる |
| 「結果に応じて `features/10-*/research/README.md` 末尾の再利用条件を更新」 | terminal outcome のみ bounded block で旧 bullet 含めて置換 (Case D/E/F では更新しない、設計方針 #5) |

## 補足: gh rate limit 枯渇への対応

- `gh issue view 11` は init-feature 前に事前取得済み
- 以後 `gh` を呼ばない
- Issue close は **本フロー外** (trailer は `Refs #11` のみ)
- finalize-feature.mjs は `gh` を呼ばない (grep 確認済み)
- 復帰後の運用: `gh issue comment 11 -F features/11-.../research-log.md` で結果コメント + terminal outcome 達成時 `gh issue close 11` で手動 close
