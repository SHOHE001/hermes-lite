# debug-spec for #10 — 裁量で残置 findings

`codex_loops` が `max_codex_loops=5` に到達したため、`stop_conditions.ask_user_on_blocking=false` に従い自動裁量採用。最終 review 結果は **blocking=1 (architect high)** で、内容は wording の最終ラウンド微調整。本 commit で対応済みだが、コミット履歴に明示する。

## 残置 finding (round 6, architect high)

**title**: "最終判定根拠が live 実機結果と fixture 再分類で混線している"

**現状の対応 (本 commit で同時実施)**:

1. `test-summary.json` の `final_classification_source` を「post-update live re-run stdout JSON **のみ**」に修正。fixture は T13 回帰検証用で final_outcome の根拠でないと明記。
2. `ci.log` Summary に「final_classification_source は post-update live re-run の stdout JSON のみ」を追加し、fixture が判定根拠ではないことを明示。
3. Issue #10 結論コメントは既に rate_limited に訂正済み（superseded 履歴あり）、Issue #11 タイトルは `sub_outcome=rate_limited` を含む形に更新済み。

**残置 (架空のリスク)**:

- 厳密には codex final round 6 を再実行して architect が pass 出すことを確認する余地があるが、`max_codex_loops=5` に到達したため再実行は skip。fixture/live の混線については本 commit で wording を明確に分離した。

## 残置 finding (round 6, architect medium x2)

| # | 内容 | 対応 |
|---|---|---|
| 1 | merge passed と #9 保留の境界が曖昧 | `test-summary.json` の `issue_9_recommendation="保留"` + `raised_issues=[11]` + `ci.log` Summary 行で machine-readable に明記済み |
| 2 | T10 secret grep pattern が ci.log から復元困難 | ci.log Summary に「pattern source は test-spec.md T10 セクションが単一ソース」を追記済み |

## 旧 round の残置はなし

Round 1〜5 の指摘はすべて plan / 実装 / ci.log への反映で対応済み（plan の rejection.md と本 PR の各 wip コミット履歴参照）。
