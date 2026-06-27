# Issue #11 research-log

## 実行コマンド

```
python3 features/10-phase-3-computer-use-api-claude-max-oauth-9/research/computer_use_probe.py approach-b > /tmp/probe_b_11.json
```

executed_at: 2026-06-27T07:35:00Z (秒粒度は probe 実行時点、UTC)

## probe 出力 JSON

```json
{
  "approach": "B",
  "billing_delta_class": "not_applicable",
  "billing_observation": "not_applicable",
  "console_checked_at": null,
  "console_window_minutes": 15,
  "elapsed_seconds": 0,
  "exit_code": 0,
  "message_class": "other",
  "model_used": "claude-sonnet-4-5",
  "notes": "",
  "outcome": "undetermined",
  "redacted_error_type": "rate_limit_error",
  "stage": "approach_b_request",
  "status": 429,
  "stop_reason": null,
  "sub_outcome": "rate_limited",
  "tool_use_observed": false,
  "usage_token_counts": {}
}
```

（B-5 allowlist フィルタ適用済み。`additional_turn_attempted` は allowlist 外のため除外。）

## 最終 outcome

- outcome: undetermined
- sub_outcome: rate_limited
- case: D
- 確定根拠: 設計方針 #3 enum 表 Case D（HTTP 429 rate_limit_error → undetermined/rate_limited）

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

## console 確認手順

該当なし（Case D のため console 確認は不要）。

## redaction 確認

- 設計方針 #6-a の禁止対象 7 系列 (実 8 パターン) が本ファイルに含まれないこと: **pre-commit pass / post-commit pending**
- 検査タイミング: 6-c (a) commit 前 grep は **済 (pass)**、(b) commit 後 git show grep は **STEP 8 squash merge 後に実施予定** (commit 確定前は post-commit hash がないため未実施)
- post-commit 検査結果は orchestrator 側 commit message + finalize 経由で別途記録

### 旧 #10 判定 supersede 履歴

- #10 PR 最終 outcome: undetermined / network_error → undetermined / rate_limited に post-update 再分類（commit 264ff78 時点）
- #11 ジョブ実行で観測した新 outcome: undetermined / rate_limited（再度同じ結果）
- supersede 履歴の保持先: 本 research-log.md。Case D 時点では README は **#10 PR 時の旧 temporary state を維持**しており（設計方針 #5-a）、#11 の最新観測 (undetermined / rate_limited) は本 research-log のみが保持する。README は terminal outcome (Case A/A'/B/C) 達成時にのみ最新値を反映する公開ミラー。
