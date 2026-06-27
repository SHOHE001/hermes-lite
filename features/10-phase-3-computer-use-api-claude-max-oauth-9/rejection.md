# Rejection log for #10

## Round 1 (codex-design 2026-06-27)

### contrarian high: "一回限りの実機調査に対して PR・4ファイル・merge まで要求するのは過剰設計"

**部分棄却 + 部分採用**。

棄却理由:
- gloop は全 Issue を「ブランチ → 設計レビュー → 実装 → 最終レビュー → squash merge」のサイクルで回す前提（`.claude/gloop-config.json` の `branch_prefix` / `mode: loop`）。「mktemp で実行、Issue コメントだけ残す」だと state.json / features/ / squash merge 経路に乗らず、gloop 全体の整合性が壊れる。
- 再現性のためにスクリプトを repo に残す価値はある。(a) なら #9 で流用、(b)/(c) でも「どのリクエストで何が返ってきたか」を後から検証できる。
- 「履歴に残るリスク」は配置場所と redaction で吸収できる（後述）。

採用部分:
- 配置場所を `gateway/discord/_research/` から `features/10-phase-3-.../research/` へ変更する。これにより：
  - 本番領域 (gateway/**) を汚さない（contrarian の懸念点を解消）
  - guard_paths.allow_orchestrator_write の `features/**` に入るので orchestrator が直接書ける（implementer 委譲不要）
  - features/ ディレクトリ単位で運用整理（消去 / keep）が可能
  - Discord runner からの import 経路が物理的に存在しない（隔離強度が上がる）

### contrarian medium: "Computer Use の tool_result ループを検証していない"

**部分採用**。tool_use がレスポンスに出るかは検証する。ただし tool_result を返す 2 ターン目までは時間 cap 60 分の範囲内で実現困難なら諦め、その場合は outcome を `messages_api_only` として記録し (b) ではなく `conditional` に倒す。

## Round 2 (codex-design 2026-06-27)

### contrarian medium: "Approach A が目的に対して回り道で過剰"

**棄却**。Issue #10 本体の「決定事項」で Approach A / B / C の 3 段階が明記されており、本 plan はそれを満たす必要がある。A を Drop すると Issue 本体の DoD（「Approach A の結果（動く / 動かない / エラー詳細）をコメントで報告」）を満たせず、本 Issue の Close 条件が崩れる。CLI 経由の能力観測自体に意義がある（`claude -p` で完結する経路があれば #9 設計が大きく変わる）ため、補助に降格はしない。

ただし、**A の責務を CLI capability + JSONL schema 観測のみに限定し、課金経路判定は B 専用** とする方針は採用（architect 指摘との整合）。

### contrarian medium: "Approach C のコスト試算は今回の Non-Goal 寄り"

**棄却**。Issue #10 本体 DoD で「Approach C のコスト見積もり（月次 USD 試算）をコメントで報告」が明記されている。Issue 本体を満たさずに Close することはできない。ただし「概算オーダー（10x 精度）、実機なし、確度: 低」の制約は維持。

## Round 3 (codex-design 2026-06-27, blocking=9)

すべての persona high 指摘は **採用** して plan.md を以下のように更新（採用詳細は plan 本文の差分参照）:

| persona | severity | 指摘 | 対応 |
|---|---|---|---|
| architect | high | supported 判定と課金確認の要件が矛盾 | 採用: outcome 表で `tool_use_observed_and_subscription_billing` に統合し supported の必須条件を明示。T02 / JSON 例 / B-2 / B-4 すべて反映 |
| architect | high | 未定義 sub_outcome `tool_use_observed_but_unconfirmed` | 採用: 既存の `tool_use_observed_but_billing_unknown` に統合。B-4 / オープン論点を修正 |
| architect | high | 成果物数と DoD の矛盾 | 採用: 必須成果物リストを 1 箇所（実装対象節）に固定し、DoD はそのリストを参照する形に統一。test-spec.md を必須に明示、debug-spec.md は任意 |
| architect | medium | Approach A の責務混線 | 採用: A は capability/CLI schema 観測専用、JSONL は参考情報、課金判定は B 専用と明文化 |
| architect | medium | docs 取得の境界曖昧 | 採用: `computer_use_probe.sh` の `curl` に統一 |
| architect | medium | guard_paths 未検証 | 採用: 前提条件節を追加し jq コマンドで検証 |
| architect | low | `unsupported` の 400 分類が文字列一致 | 採用: `status` → `error.type` → 正規化済み `error.message` の優先順位を B-2 に明記 |
| contrarian | high | supported 判定が目的を満たしていない | architect high と同根、上記で対応 |
| contrarian | high | T10 secret grep が plan 自身と衝突 | 採用: plan の prompt を `<probe_prompt_redacted>` プレースホルダ化、T10 の grep 対象から plan.md / コード成果物固定文字列を除外、prompt 本文 grep は廃止 |
| contrarian | high | 未定義 sub_outcome | architect high と同根、上記で対応 |
| contrarian | medium | allowlist と JSON 例の不整合 | 採用: allowlist にフィールド表を新設し型と用途を固定、`elapsed_seconds`/`stage`/`cli_help_has_betas_flag`/`additional_turn_attempted`/`error_code`/`message_class` 等を正式追加 |
| contrarian | medium | Approach A が過剰、API 直叩きだけに絞れ | **棄却**（Round 2 と同じ理由。Issue 本体 DoD で A/B/C 3 段階が明記されている） |
| contrarian | medium | Approach C は #9 follow-up に分離せよ | **棄却**（Round 2 と同じ理由。Issue 本体 DoD で C が明記されている） |
| migration | high | sub_outcome enum 破綻と supported/conditional 不整合 | 採用: enum 統合・supported 必須条件明示で対応 |
| migration | high | allowlist と T01/JSON 例の不整合 | 採用: allowlist フィールド表で `cli_help_has_betas_flag` / `elapsed_seconds` / `stage` 等を正式に許可 |
| migration | high | T10_secret_grep_extended が plan 自身と矛盾 | 採用: grep 対象範囲を明文化（plan・コード成果物除外） |
| migration | medium | state.json schema 互換性が未定義 | 採用: 実装対象節と DoD に「`state.mjs set/inc` 経由のみ、既存キー保持」を明記、T12_state_invariants を新設 |
| migration | medium | 401/403 分類の raw-less 記録不足 | 採用: allowlist に `error_code` / `message_class` / `redacted_error_type` を含め後方互換的に再分類可能とする |

## Round 4 (codex-design 2026-06-27, blocking=8)

スコープを縮める方向で大きく整理した：

- **B-4（追加 1 ターン）を Non-Goal に降格**（contrarian C2 / architect A2）。supported は「1 リクエスト 200 + tool_use + console subscription_billing 確認」で完結する。
- **Approach C を WebFetch から curl に統一**（architect A1 / contrarian medium / migration medium）。
- **fixture classify モード追加**（contrarian C3）: `computer_use_probe.py --classify-fixture` と 8 件の fixture を必須成果物に。
- **state.json invariant 強化**（migration M1 / architect A4）: 全 top-level キー + `.phases.*` の既存サブキー保持を T12 で検証。
- **credential 分類細分化**（migration M2）: ファイル不存在 / parse failure / token なし / 未知 schema を分類、`top_keys_fingerprint` で再評価可能に。
- **400 truth table 化 + exit code 表追加**（architect low / contrarian low / migration medium）: B-2-a で全ケース 1 表に統合。
- **console 確認手順を test-spec.md に固定**（architect A5 / contrarian C1）: baseline / 15 分窓 / `billing_delta_class` enum / 並行 session 分離不能時の unknown fallback を明記。
- **節タイトル**「Anthropic Python SDK 直叩き」→「raw HTTP probe (SDK 不使用)」（architect medium / contrarian medium）。
- **allowlist の status 型表記修正**（migration medium）: `int|null` に修正。
- **実装対象節の境界書き直し**（architect medium）: 「既存関数編集なし、原則新規、例外として state.json と plan.md は明示条件下のみ更新可」。
- **T10b_code_dangerous_output_grep 新設**（architect low）: コード成果物に対する危険出力経路の静的 grep を追加。

**棄却継続**:
- contrarian C4 「A と C が過剰」: Round 2 / Round 3 と同じ理由（Issue 本体 DoD で A/B/C 必須）。

**部分採用**:
- contrarian medium 「allowlist の強制機構がない」: allowlist validation 関数を必須として B-5 / fixtures / test-spec.md に明記したが、Issue コメントを probe stdout の出力に限定する強制機構までは入れない（最終結論コメントは人間が allowlist を遵守して書く運用）。理由: 機械生成だけにすると判定者の裁量（keep/delete、#9 推奨 a/b/c）を JSON に詰め込む schema が肥大化する。test-spec.md で「結論コメント本文も B-5 allowlist フィールドのみ」と明文化することで担保する。

## Round 5 (codex-design 2026-06-27, blocking=8)

3 persona がほぼ同じ高指摘に収束（Round 4 の編集取りこぼし）。全部採用:

- **T02_supported_path の `additional_turn_attempted=true` を `false` に修正**（全 persona high）: B-4 を Non-Goal にした以上、supported path も `additional_turn_attempted=false` で完結する。
- **In-Scope の「1 回 + tool_use があれば追加 1 ターン」を「1 リクエストだけ」に書き直し**（contrarian high）: Non-Goals との表現揺れを解消。
- **T02c_conditional_extra_usage を新設 + apply_console_confirmation truth table を追加**（architect high）: `incremented_extra_usage` から `conditional/extra_usage_billing` への合成ルールを明示し、Hermes #15080 同型ケースを最終 outcome に反映できるようにする。
- **B-2-a truth table の各行に fixture name を 1 対 1 で割付け、合計 11 件に拡張**（全 persona high）: `200_other_stop_reason.json` / `400_other_error_type.json` / `400_null_error_type.json` / `403_other.json` を追加。T13 も 11 件に。
- **DoD の必須成果物に `features/10-*/fixtures/*.json` を明記**（contrarian medium / migration medium）: 実装対象と DoD のリスト差分を解消。
- **T04 を T04a_unsupported_beta_not_allowed / T04b_unsupported_permission に分割**（migration medium）: 同じ T-ID で sub_outcome が分岐する曖昧さを排除。
- **Approach A vs B の最終 outcome 合成優先順位を明示**（architect medium）: 主判定は常に B、A は capability 観測のみ。
- **`usage_schema_unknown` の優先順位明示**（architect medium）: 観測メタデータとして notes に記録するだけで最終 outcome を上書きしない。
- **httpx を禁止、urllib 固定**（contrarian medium）: jobs project_type で依存管理がないため標準ライブラリのみ。
- **B-1 擬似コードに `sys.exit(1)` 明記 + exit_code 契約節を追加**（migration medium）: B-1 emit と B-2-b 分類 exit_code 0 の住み分けを明文化。stdout JSON の `exit_code` field を authoritative とする。
- **fallback 時の責務表を追加**（architect low）: orchestrator と implementer の境界を 3 行で固定。

**棄却継続**:
- contrarian medium 「state 更新・自動 Issue 起票・クロスポストまで抱え込みすぎ」: Round 2/3/4 と同じ理由（Issue 本体 DoD で要求されており、本 Issue で Close する以上は必須）。

## Round 6 への dispatch は実施せず（design_loops=4/3 cap 超過、裁量で passed）

`.claude/gloop-config.json` の `stop_conditions.max_design_loops.light=3` および `stop_conditions.ask_user_on_blocking=false` に従い **自動裁量採用**。

Round 5 で指摘された blocking 8 件はすべて plan 編集で対応済み（採用詳細は上記）。critical/high の残置はなし。ただし Round 5 編集後の plan が新たな指摘を呼ばない保証はない（再 dispatch していないため）。commit message 本文に「Codex design 裁量 passed: blocking 0 残置、Round 5 指摘は同一バッチで対応済み、再検証なし」と明記する。

