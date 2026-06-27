# Rejection log for #11

## ラウンド 5 で裁量採用した残置 findings (max_design_loops=3 超過、design_loops=4 で打ち切り)

flow=light の `max_design_loops=3` を超過したため、ラウンド 5 で残った critical/high findings 6 件を裁量で plan に取り込まず残置する。本ジョブの主目的は「Computer Use probe を 1 回再実行して結果を記録する」chore であり、設計レビューの完璧性より観測機会の獲得を優先する判断。

各残置 finding と裁量根拠:

### 1. architect H1: research-log への probe 出力取り込みが allowlist key だけで信頼境界を閉じていない

**指摘**: `notes`, `message_class`, `model_used`, `redacted_error_type` など allowlist 済みフィールドの値に秘匿値・生エラー・絶対パスが混入する可能性。任意の credential 形状や将来追加 token を防げない。

**裁量根拠**: 既存 #10 の probe.py は B-5 allowlist 出力契約で実装済み（commit 264ff78 時点）。本 plan は probe.py を改修しない方針 (Out-of-Scope) のため、上流契約に依存する。万一漏洩した場合は設計方針 #6-c の grep 検査が補助検出する (commit 前 + commit 後の 2 段)。完全な型/長さ validation は probe.py 改修案件として別 Issue にスコープ外し。

### 2. architect H2: README H2 配下に bounded block + H3 注入で既存ドキュメント境界が曖昧

**指摘**: 既存 H2 `本 PR 実行時の最終判定（2026-06-27）` が #10 PR 時の判定なのか #11 follow-up 後の公開ミラーなのか責務混在。`### 旧判定` H3 が文書構造に参加。

**裁量根拠**: 既存 H2 名の grep/anchor 互換維持を優先 (migration 観点)。`### 旧判定` H3 はあくまで bounded block 内の補助構造で、TOC 生成等への影響は実害として顕在化していない。`## follow-up 更新履歴` への分離提案は #10 PR の運用契約変更を伴うため別 Issue で検討。

### 3. contrarian H1: 非 terminal Case D/E/F でも finalize + push する設計が過剰

**指摘**: Case D/E/F は Issue 完了条件未達かつ README 不変なのに、成果物 commit + finalize commit 計 2 commit を push する。research-log だけ commit、finalize は terminal limited にする代替案を採らない理由不足。

**裁量根拠**: gloop-work の STEP 8 は標準フロー固定で、commit/push/finalize は分離不可能 (skill の固定パイプライン)。`commit/push しない` は本 plan で表現できない (skill の前提を曲げる必要)。research-log 追加自体は観測 1 件追加の価値があり、main に積む価値は維持される。後続 reviewer も partial_observation 状態を commit history で追跡可能。

### 4. contrarian H2: redaction が allowlist key 抽出に依存しすぎている

**指摘**: 1 と同質の指摘。許可フィールド値からの漏洩を防げない。任意 JSON を整形してログ化するより必要 enum/数値/boolean だけ再構成する方が安全。

**裁量根拠**: 上記 1 と同じ (probe.py 改修案件としてスコープ外)。本 plan は probe.py の上流契約に依存し、grep 補助検査で網羅性を担保する設計。free-form `notes` の固定文化は probe.py 側の改修が必要。

### 5. migration H1: Case D/E/F で README 完全不変だと既存 README 利用者が旧分類を最新値として読み続ける

**指摘**: README に `#11 partial_observation exists` の短い注記を追加する案。

**裁量根拠**: 短い注記を追加すると bounded block の冪等性ロジック (terminal/非 terminal で異なる) が複雑化。Case D/E/F でも常に README に注記する場合の追加マーカー仕様が必要。今回 1 回限りの follow-up では実害が限定的 (README 利用者は #10 PR 時点と同じ「再評価必須」を読む)。terminal outcome 達成時の README 更新で最終的に正常化される。

### 6. migration H2: 旧 probe 形式の `network_error` を Case F に落とすため #10 互換入力の移行パスがない

**指摘**: status=429 / redacted_error_type=rate_limit_error を見て旧形式 `network_error` を Case D `rate_limited` として再分類する明示ルールが必要。

**裁量根拠**: #10 PR で probe.py に truth table 行 12 (429 → rate_limited) が post-update 追加済み (commit 264ff78)。本ジョブで実行する probe.py は新分類版のため、新規 429 観測は直接 `rate_limited` を返す。`network_error` で返るのは旧版 probe.py のみで、本ジョブ実行時には該当しない。将来 probe.py が再びリグレッションした場合のみ問題化するが、その時点で別 Issue 案件。

---

## 残置 findings の commit message 表記

commit message 本文に「Codex design blocking 6 件残置 (ラウンド 5 max_design_loops 超過、裁量採用、詳細 features/11-.../rejection.md)」を含める。
