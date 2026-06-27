# Issue #10 research-log

実行日: 2026-06-27 UTC

実行者: gloop/orchestrator（自律モード）

実行環境:
- ホスト: gen8 (Ubuntu Server 24.04)
- Python: 標準ライブラリのみ（urllib.request）
- Claude CLI: PATH 上に存在（version は記録省略、`claude --help` で `--beta` 系オプションを検出）
- credentials.json: `~/.claude/.credentials.json`、`claudeAiOauth.accessToken` schema を使用

## Approach A 実行結果（capability 観測）

```json
{"additional_turn_attempted": false, "approach": "A", "billing_delta_class": "not_applicable",
 "billing_observation": "not_applicable", "cli_help_has_betas_flag": true,
 "cli_probe_tool_use_observed": false, "console_checked_at": null,
 "console_window_minutes": 15, "elapsed_seconds": 6, "exit_code": 0,
 "notes": "docs_reachable=true cli_probe_ok=true",
 "outcome": "undetermined", "stage": "approach_a_complete",
 "sub_outcome": "capability_observation_only"}
```

観測事実:

- `claude --help` 出力に `--beta` / `--experimental` / `--tool` 系の文字列が存在（`cli_help_has_betas_flag=true`）
- Computer Use docs URL (`docs.claude.com/.../computer-use`) が HTTP で取得可能（`docs_reachable=true`）
- `claude -p "ok とだけ返して"` の subprocess 起動は成功（`cli_probe_ok=true`、ただし Computer Use tool は CLI 側からは発火確認できず）

Approach A は capability 観測のみで、最終 outcome は Approach B で確定する（plan の規定どおり）。

## Approach B 実行結果（raw HTTP probe）

**Primary (authoritative, post-update truth table 行 12 で再分類)**:

```json
{"additional_turn_attempted": false, "approach": "B", "billing_delta_class": "not_applicable",
 "billing_observation": "not_applicable", "console_checked_at": null,
 "console_window_minutes": 15, "elapsed_seconds": 0, "exit_code": 0,
 "message_class": "other", "model_used": "claude-sonnet-4-5",
 "outcome": "undetermined", "redacted_error_type": "rate_limit_error",
 "stage": "approach_b_request", "status": 429, "stop_reason": null,
 "sub_outcome": "rate_limited", "tool_use_observed": false,
 "usage_token_counts": {}}
```

**Superseded (旧分類、初回実装の誤分類)**:

```json
{"approach": "B", "status": 429, "redacted_error_type": "rate_limit_error",
 "sub_outcome": "network_error", "exit_code": 3, "stage": "approach_b_request",
 "superseded": true,
 "supersede_reason": "429 was mapped via 'その他 status' fallback before truth table 行 12 was added"}
```

観測事実:

- POST `https://api.anthropic.com/v1/messages` に対して OAuth 認証ヘッダ + `anthropic-beta` ヘッダ（`computer-use-2025-01-24`）で送信（具体的なヘッダ値は plan.md B-2 参照、redacted）
- HTTP **429 rate_limit_error** が返却された（2 回試行、いずれも 429）
- 課金は発生していない（200 でないため）

**この結果の含意（重要）**:

1. **OAuth bearer token は `api.anthropic.com` 側の認証を通過した**（401 / 403 でない）。Claude Max OAuth credential で Messages API のエンドポイントには到達可能であることが確認できた。これは Hermes #15080 の文脈で「OAuth 経路は通る」という前提部分を補強する観測。
2. **Computer Use beta の可否は判定不能**: 429 はリクエストレートまたはトークン使用量の制限であり、Computer Use beta 自体の許可状態（403 permission_error / 400 beta_not_allowed）まで進めなかった。
3. **post-update**: codex final round 2 指摘を受け、truth table 行 12 として `429 → undetermined/rate_limited (exit 0)` を新設、probe.py に明示分岐を追加。再分類後の出力は `sub_outcome=rate_limited`, `exit_code=0`（ci.log 参照）。
4. follow-up Issue で **異なる時間帯 or 別 account or バックオフ後** に再実行する必要がある。

## Approach C 実行結果（pricing fetch、参考情報）

post-update（B 側 enum を流用せず、`undetermined/usage_schema_unknown` で中立化）:

```json
{"additional_turn_attempted": false, "approach": "C", "billing_delta_class": "not_applicable",
 "billing_observation": "not_applicable", "console_checked_at": null,
 "console_window_minutes": 15, "elapsed_seconds": 1, "exit_code": 0,
 "notes": "pricing_url_fetch_ok=true informational_match_lines=2",
 "outcome": "undetermined", "stage": "approach_c_pricing_fetch",
 "sub_outcome": "usage_schema_unknown"}
```

詳細は `research/cost_estimate.md` を参照（概算オーダー、確度: 低、実機なし）:

- light 利用（30 セッション/月、低 step）: 数 USD/月レンジ
- heavy 利用（300 セッション/月、高 step）: 3 桁 USD/月レンジ
- 10x 精度。実機計測で大幅変動可能。

## 最終 outcome（自律実行結果、post-update truth table 行 12 で再分類）

| 項目 | 値 |
|---|---|
| **最終 outcome** | `undetermined` |
| **sub_outcome** | `rate_limited`（HTTP 429 rate_limit_error、truth table 行 12 で明示分類、exit_code=0） |
| **初回 live 出力 (superseded)** | `sub_outcome=network_error, exit_code=3`（probe.py 更新前の "その他 status" 行マップ。codex final round 1 の指摘を受けて truth table に 429 行を新設、`--classify-fixture` で再分類した結果が現在の最終値） |
| **3 択判定** | **判定不能** |
| **#9 への推奨アクション** | follow-up Issue で異なる時間帯にリトライしてから判定。現状で #9 は **保留**（API 経路は通ったが Computer Use 可否は未確認） |
| **コード去就** | keep。`research/README.md` の「再評価必須、現状値は無効」を末尾に追記し、follow-up Issue 参照を記載 |

## follow-up Issue（起票済み）

**#11**: `[Phase 3] #10 follow-up: Computer Use 再評価 (rate_limit 後リトライ)`

理由: 本実行で Approach B が 429 rate_limit_error により Computer Use 可否を判定できなかったため。Anthropic 側 rate limit window のクールダウン後（または別 account / 静穏時間帯）に `python3 features/10-phase-3-.../research/computer_use_probe.py approach-b` を再実行する必要がある。

## redaction 確認（T10）

本ファイルは plan.md B-5 allowlist のみを使用する。secret 値（OAuth トークン値、ベアラ文字列、リクエスト ID、認証ヘッダ値、Cookie 値、ユーザのホームパス文字列）の生 raw は **出現しない**。OAuth credential JSON の top-level キー名称は記録しない（`top_keys_fingerprint` も今回は emit されていない）。probe.py 内の固定 prompt 定数は機密扱いしないが、本ファイル・Issue コメントには貼らない（plan のプレースホルダ運用に従う）。

## T13 fixture 検証

post-update 検証で 12 件全 pass（plan の B-2-a truth table と一致、`429_rate_limit.json` 追加後）:

```
T13 pass=12 fail=0 (expect pass=12 fail=0)
```

詳細は `ci.log` の T13 セクション参照。
