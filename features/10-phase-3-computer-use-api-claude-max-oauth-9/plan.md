# plan: #10 [Phase 3] Computer Use API が Claude Max OAuth で使えるか実機調査（#9 前提）

slug: phase-3-computer-use-api-claude-max-oauth-9
milestone: Phase 3
labels: type:chore, batch:feature
flow: light
project_type: jobs（自動テストフレーム無し。検証は手動チェックリスト）

## 目的（1 行）

Computer Use beta API を Claude Max OAuth 枠だけで回せるか実機で評価し、#9 の実装方針を **outcome 体系** に従って判定する。

## outcome 体系（判定の単一ソース）

`supported` / `unsupported` / `conditional` / `undetermined` の 4 区分。サブ outcome は分類用で、本表が **enum の単一ソース**（本文中で表外の値を使わない）。

| outcome | サブ outcome（enum） | 意味 | #9 への含意（3 択） |
|---|---|---|---|
| supported | `tool_use_observed_and_subscription_billing` | API が認証済みリクエストを受け、Computer Use tool_use がレスポンスに出る **かつ** Max subscription で課金された痕跡が console で確認できた | (a) Max で動く → #9 に着手 |
| conditional | `messages_api_only`, `extra_usage_billing`, `tool_use_observed_but_billing_unknown` | API は通るが、Computer Use tool 起動が確認できない / 課金経路が extra usage（Hermes #15080 再現） / tool_use は出るが課金経路が未確認（console 未確認 or 追加ターン未実施） | (c) 条件付き → #9 は条件下で着手、または別経路検討 |
| unsupported | `beta_not_allowed`, `api_explicit_reject_after_auth` | 認証済みリクエストに対し Anthropic 側が Computer Use を **明示的に拒否**（403 + error.type=`permission_error` / 400 + error.type=`invalid_request_error` で `Computer Use is not available` 等） | (b) 動かない → #9 は API key 経路 or 保留 |
| undetermined | `auth_failure`, `credential_missing`, `credential_schema_unknown`, `usage_schema_unknown`, `timeout`, `network_error`, `probe_input_error`, `rate_limited`, `capability_observation_only` | OAuth scope 不足、token 期限切れ、`~/.claude/.credentials.json` 不存在 or schema 差分、JSONL schema 差分、60 分 cap 超過、HTTP 5xx、リクエスト不備 (model 名間違い等)、HTTP 429 rate_limit_error、Approach A の capability 観測のみ（A 専用、最終 outcome に上書きしない） | 判定不能 → follow-up Issue を自動起票、#9 は保留 |

判定不能 (`undetermined`) を `unsupported` に潰さない。これが本 plan の中核ルール。

**supported の必須条件**: tool_use 観測 **AND** subscription_billing 確認の両方。どちらか欠ければ自動で `conditional/tool_use_observed_but_billing_unknown` に倒す（B-4 の追加ターン未実施・console 未確認はすべてここに集約）。

## 前提条件（plan 確定時に検証する）

```bash
jq -e '.guard_paths.allow_orchestrator_write | index("features/**")' .claude/gloop-config.json
# → "features/**" が allow_orchestrator_write に含まれることを確認（含まれなければ implementer 委譲にフォールバック）
```

## In-Scope / Out-of-Scope

| In-Scope | Out-of-Scope |
|---|---|
| `claude -p` の `--help` / 公式 docs から Computer Use サポートの有無を確認（capability 観測のみ） | Windows GUI 操作の実装（screenshot / click / keyboard tool） |
| `~/.claude/.credentials.json` の OAuth access_token を直叩き、Anthropic Messages API に Computer Use beta request を **1 リクエストだけ** 試す最小プローブ | gateway/discord/bot.py への Computer Use ハンドラ追加。2 ターン目（`tool_result` を返して assistant の次応答を観測すること）の検証は Non-Goal（B-4 削除） |
| Approach A: `claude -p` 実行時に CLI が生成する `~/.claude/projects/*/sessions/*.jsonl` 最新行の usage block を **参考情報として** 読む（capability/CLI schema 観測のみ） | Approach A の JSONL を outcome の主判定（supported/unsupported）に使うこと（経路不整合） |
| Approach B: API response body 自体の usage / billing 情報 + Anthropic console 有人確認（許容、課金判定の一次データはここに集約） | Anthropic console の自動 scrape |
| Anthropic 公式 pricing から **概算オーダー（誤差 10x 想定）** の月次コスト試算（実機なし、#9 着手判断材料として必要） | 公式 API key 取得 / API key で実機リクエスト |
| Issue #10 へ allowlist 形式 JSON summary をコメント（Approach A/B/C 結果 + 結論 + #9 推奨アクション）、Issue #9 へクロスポスト | raw error body / response body / session JSONL 行を Issue に貼ること |
| `features/10-*/research/` 配下 4 ファイル + `features/10-*/research-log.md` + `features/10-*/test-spec.md` を本 PR に含める（必須成果物リストは DoD と同一） | `gateway/discord/_research/` の作成（contrarian/architect 指摘で配置変更） |
| docs 取得は `computer_use_probe.sh` 内の `curl` に統一（WebFetch は使わない、script 単体で再実行可能にする） | orchestrator の WebFetch 機能を成果物の動作前提にすること |

## Non-Goals

- #9 の本実装に進むことはしない（本 Issue は判定根拠の収集のみ）
- `outcome=conditional` / `undetermined` の場合に「Anthropic 側挙動が将来変わるか」を待つ・議論する（本時点の挙動だけ記録）
- Computer Use 以外の代替実装パス（RDP / win32 SendKeys 等）の比較検討（#9 で別途）
- 課金経路の **完全自動判定**（Anthropic console は有人確認を許容）
- repo に commit したコードを本番経路から import / 再利用する設計（隔離維持）
- **Computer Use の 2 ターン目検証**（`tool_result` を返して assistant の次応答を観測すること）。1 リクエスト + console 確認で supported / conditional 判定を確定させる。B-4 の追加ターンは本 Issue 範囲外、必要なら follow-up Issue（#9 着手前）で検証する
- Anthropic Python SDK の利用（raw HTTP probe で完結、SDK 依存はしない）

## 設計方針

### 全体の流れ

1. `features/10-phase-3-.../research/` 配下に隔離ディレクトリを作る（`README.md` で「Issue #10 評価コード。本番 import 禁止、Claude CLI / credentials のバージョン依存」を明記）。
2. Approach A → B → C の順に実機検証し、各結果を **allowlist 形式 JSON** で Issue #10 にコメント。
3. 最終コメントで outcome（4 区分）+ 3 択判定（a/b/c/判定不能）+ 評価コード去就 + #9 への推奨アクションをまとめる。
4. Issue #9 にクロスポストコメント。
5. `outcome=undetermined` なら follow-up Issue を自動起票（タイトル `#10 follow-up: Computer Use 再評価 (<sub_outcome>)`、Phase 3、`type:chore`）。

### 配置と隔離（Round 1 review 反映）

| パス | 配置理由 |
|---|---|
| `features/10-phase-3-.../research/README.md` | 「Issue #10 専用評価コード。本番 import 禁止、Claude CLI v<検出 version>・credential schema v<検出 schema> 依存、re-use 前に必ず再評価」 |
| `features/10-phase-3-.../research/computer_use_probe.sh` | Approach A 実行（claude --help grep / docs URL の curl + grep / 最小プローブ） |
| `features/10-phase-3-.../research/computer_use_probe.py` | Approach B 実行（OAuth token 直叩き、redaction 通過、結果を allowlist JSON で stdout に吐く） |
| `features/10-phase-3-.../research/cost_estimate.md` | Approach C 試算と仮定（概算レンジ扱い） |
| `features/10-phase-3-.../research-log.md` | 実行ログの redacted 抜粋。最終 outcome 判定の根拠を残す |

- 本番 (gateway/discord/) を一切汚さない。
- features/ ディレクトリ単位で「keep / delete」運用ができる（squash merge 後も判断可能）。
- guard_paths.allow_orchestrator_write の `features/**` に入るので orchestrator が直接書ける（implementer 委譲不要 = STEP 6 はシンプル実行のみ）。

### Approach A: `claude -p` subprocess 経由（capability 観測のみ）

- `claude --help 2>&1 | grep -iE 'computer.use|beta|experimental|tool'` で関連オプションを洗う。
- 公式 docs は `computer_use_probe.sh` 内の `curl` で取得（`docs.claude.com` の Computer Use ページ / `claude -p` の CLI ref ページ）。WebFetch / orchestration 環境機能には依存しない。
- もし `--betas` 相当のフラグがあれば最小プローブ（`claude -p "ok とだけ返して"`）を 1 回試す。**通常プローブ + Computer Use 起動を促すプローブの 2 種類を分けて記録** → CLI 経由での tool_use 出現有無を `cli_help_has_betas_flag` / `cli_probe_tool_use_observed` として記録。
- 実行直後に `~/.claude/projects/<encoded_cwd>/*.jsonl` の **最新ファイルの末尾行** を tail し、`usage` フィールドを **schema-tolerant に** 読む（存在しない field は `usage_schema_unknown` として記録）。
- 時間 cap: **60 分**。超過時は `outcome=undetermined`, `sub_outcome=timeout` で打ち切り、中間結果を JSON summary で Issue に投稿してから B へ進む。
- **Approach A は capability / CLI schema 観測専用**。outcome（supported / unsupported）の主判定には使わない。JSONL の usage は参考情報のみ、課金経路判定（subscription_billing / extra_usage_billing）は Approach B の response body + console 確認だけで行う。

### Approach B: raw HTTP probe（SDK 不使用、`httpx` または `urllib` の標準形式）

SDK は使わない。`computer_use_probe.py` 単体で **標準ライブラリの `urllib.request` のみ** で raw POST を組み立てる（`httpx` 等の依存追加は禁止、`jobs` project_type で依存管理が無いため）。

#### B-1. credential 読み出し（schema-tolerant、分類細分化）

```python
# 擬似コード
import json, os
path = os.path.expanduser("~/.claude/.credentials.json")

if not os.path.exists(path):
    emit("undetermined", "credential_missing"); sys.exit(1)  # exit_code=1

try:
    cred = json.loads(open(path).read())
except json.JSONDecodeError:
    emit("undetermined", "credential_schema_unknown",
         notes="credentials.json parse failure"); sys.exit(1)  # exit_code=1

# 候補 key を順に試す（既知 schema、Claude Code/CLI のバージョン差吸収）
token = (
    cred.get("oauthAccount", {}).get("access_token") if isinstance(cred.get("oauthAccount"), dict) else None
) or cred.get("access_token") or cred.get("token")
if not token and isinstance(cred.get("claudeAiOauth"), dict):
    token = cred["claudeAiOauth"].get("accessToken")  # Claude Code installs >= 2026-XX schema
if not token:
    # 既知 container はあるが token field がない → schema が変わった可能性
    known_containers = {"oauthAccount", "access_token", "token", "claudeAiOauth"}
    seen_top_keys = set(cred.keys())
    if seen_top_keys & known_containers:
        emit("undetermined", "credential_schema_unknown",
             notes=f"known_container_no_token top_keys_fingerprint={sorted(seen_top_keys)}"); sys.exit(1)
    # 既知コンテナが一切ない未知 schema
    emit("undetermined", "credential_schema_unknown",
         notes=f"unknown_schema top_keys_fingerprint={sorted(seen_top_keys)}"); sys.exit(1)
```

**exit_code 契約（B-2-b と B-1 の合成）**: B-1 で credential 取得に失敗した場合は **必ず exit_code=1** で停止する（stdout には B-1 emit の最小 JSON）。`--classify-fixture` の分類モードは B-2-b の表どおり exit_code=0 で stdout JSON を返す（プロセス成否ではなく stdout JSON の `outcome` を読む）。呼び出し側は stdout JSON の `exit_code` field を authoritative とし、process status は補助確認のみに使う。

**分類細分**:
| 状況 | sub_outcome | notes に書く（raw 値は出さない） |
|---|---|---|
| ファイル不存在 | `credential_missing` | "credentials.json absent" |
| JSON parse failure | `credential_schema_unknown` | "parse failure" |
| 既知 container あり / token field なし | `credential_schema_unknown` | `top_keys_fingerprint=...` |
| 既知 container 一切なし | `credential_schema_unknown` | `top_keys_fingerprint=...` |

`top_keys_fingerprint` は top-level key 名のソート済み配列のみ（値は出さない、allowlist-safe）。判定（a/b/c）には使わず必ず follow-up Issue 起票。

#### B-2. リクエスト仕様（明示）

- URL: `POST https://api.anthropic.com/v1/messages`
- Headers:
  - `Authorization: Bearer <access_token>`
  - `anthropic-version: 2023-06-01`
  - `anthropic-beta: computer-use-2025-01-24`
  - `content-type: application/json`
- Body:

```json
{
  "model": "claude-sonnet-4-5",
  "max_tokens": 1024,
  "tools": [
    {
      "type": "computer_20250124",
      "name": "computer",
      "display_width_px": 1280,
      "display_height_px": 800,
      "display_number": 1
    }
  ],
  "messages": [
    {
      "role": "user",
      "content": "<probe_prompt_redacted>"
    }
  ]
}
```

- 実装上の `messages[0].content` は `computer_use_probe.py` 内の短い非機密定数（Computer Use tool 起動を促す英語 1 行）。plan.md / Issue コメント / research-log.md には貼らない（プレースホルダのみ）。
- model は `claude-sonnet-4-5` を第一候補とする。実行時に公式 Computer Use 対応モデル名が変わっていれば、docs から取得した model 名で上書き（実行ログに記録）。
- **分類関数 `classify_response(status, error_type, error_message_normalized, tool_use_observed, stop_reason)` の優先順位（必ずこの順で判定する。文字列一致は補助のみ）**:
  1. HTTP `status`
  2. response body の `error.type`（あれば）
  3. 正規化済み `error.message` のキーワード一致（補助のみ）

#### B-2-a. 分類 truth table（単一ソース、test fixture と 1 対 1 対応）

| # | fixture name | status | error.type | message | tool_use | stop_reason | outcome | sub_outcome | exit code |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `200_tool_use.json` | 200 | – | – | true | tool_use | conditional※ | tool_use_observed_but_billing_unknown | 0 |
| 2 | `200_end_turn.json` | 200 | – | – | false | end_turn | conditional | messages_api_only | 0 |
| 3 | `200_other_stop_reason.json` | 200 | – | – | false | max_tokens 等 | conditional | messages_api_only | 0 |
| 4 | `400_beta_not_allowed.json` | 400 | invalid_request_error | "Computer Use is not available" を含む | – | – | unsupported | beta_not_allowed | 0 |
| 5 | `400_invalid_request_other.json` | 400 | invalid_request_error | 上記以外（model 名不正等） | – | – | undetermined→retry※2 | probe_input_error | 0 |
| 6 | `400_other_error_type.json` | 400 | invalid_request_error 以外 | – | – | – | undetermined | probe_input_error | 0 |
| 7 | `400_null_error_type.json` | 400 | null | – | – | – | undetermined | probe_input_error | 0 |
| 8 | `401_auth.json` | 401 | – | – | – | – | undetermined | auth_failure | 0 |
| 9 | `403_permission.json` | 403 | permission_error | – | – | – | unsupported | api_explicit_reject_after_auth | 0 |
| 10 | `403_other.json` | 403 | permission_error 以外 | – | – | – | undetermined | auth_failure | 0 |
| 11 | `5xx_timeout.json` | 408 / 5xx / null (timeout) | – | – | – | – | undetermined | timeout または network_error | 0 |
| 12 | `429_rate_limit.json` | 429 | rate_limit_error | – | – | – | undetermined | rate_limited | 0 |

※ 200 + tool_use の場合は **console 確認結果で sub_outcome を上書き** する（合成ルールは下記 B-2-c の `apply_console_confirmation` truth table）。`classify_response` 自体は console 確認なしの暫定 outcome（必ず `conditional/tool_use_observed_but_billing_unknown`）を返す。
※2 行 5 は **実機 probe フロー** では「1 回だけ docs から取得した model 名でリトライしてから undetermined にする」。`--classify-fixture` モードでは入力 JSON 1 つに対して 1 回の分類だけを行い、リトライは行わない（fixture は最終結果のみを表す）。

`classify_response` は **HTTP レイヤの分類だけ** を行い、外部 console 確認や billing observation は別関数 `apply_console_confirmation` で合成する。

#### B-2-c. `apply_console_confirmation` truth table（最終 outcome 合成）

入力: `classify_response` の暫定 result + `billing_delta_class` (manual input)。

| 暫定 outcome / sub_outcome | billing_delta_class | 最終 outcome | 最終 sub_outcome | billing_observation |
|---|---|---|---|---|
| conditional / tool_use_observed_but_billing_unknown | incremented_subscription | supported | tool_use_observed_and_subscription_billing | subscription_billing |
| conditional / tool_use_observed_but_billing_unknown | incremented_extra_usage | conditional | extra_usage_billing | extra_usage_billing |
| conditional / tool_use_observed_but_billing_unknown | no_change | conditional | tool_use_observed_but_billing_unknown | console_confirmation_required |
| conditional / tool_use_observed_but_billing_unknown | unknown | conditional | tool_use_observed_but_billing_unknown | console_confirmation_required |
| conditional / messages_api_only | incremented_subscription | conditional | messages_api_only | subscription_billing |
| conditional / messages_api_only | incremented_extra_usage | conditional | messages_api_only | extra_usage_billing |
| conditional / messages_api_only | no_change / unknown | conditional | messages_api_only | console_confirmation_required |
| unsupported / * | （適用しない） | unsupported / *（変更なし） | 変更なし | not_applicable |
| undetermined / * | （適用しない） | undetermined / *（変更なし） | 変更なし | not_applicable |

console 確認をスキップして `apply_console_confirmation` を呼ばない場合は暫定 outcome がそのまま最終 outcome になる。

#### B-2-b. exit code 仕様

| exit code | 意味 |
|---|---|
| 0 | classify が表どおり実行された（outcome 種別は stdout JSON を参照） |
| 1 | credential 読み出し失敗（B-1 で emit 済み）。stdout は B-1 の JSON |
| 2 | docs 取得失敗（model 名解決不可かつ docs から取得不可） |
| 3 | network/timeout（リトライ後再失敗）。stdout に undetermined JSON |
| 4 | 内部例外（traceback は stderr に redact 済みで出力、stdout は最小 JSON） |

#### B-3. 課金経路の判定（Approach B 専用、再現可能な手順を test-spec.md に落とす）

- 一次データ = API response body 自身の `usage` block。`service_tier`, `cache_creation_input_tokens`, `cache_read_input_tokens` 等が **公式 docs で意味確認済みの場合のみ** 判定に使う。公式裏付けが取れないフィールドは `usage_schema_unknown` 扱いで判定に使わない。
- 二次データ（許容）= Anthropic console の Usage 画面での手動確認。以下の手順を **test-spec.md** に落とす（再現可能性を担保）:

  1. probe 実行 **直前** に console Usage 画面を開いて `subscription_used_baseline_tokens` と `extra_usage_baseline_tokens` を記録（probe stdout の `console_checked_at_before` に書く想定だが、UTC 時刻のみ allowlist で許容）。
  2. probe 実行（API 1 リクエスト）。
  3. 実行完了後 **15 分以内**（`console_window_minutes=15` を allowlist に固定）に同じ画面を再確認。
  4. 差分を `billing_delta_class` enum で分類:
     - `incremented_subscription`: subscription_used が増えた（差分が probe usage tokens ± 20% 以内）
     - `incremented_extra_usage`: extra_usage が増えた（同じ条件、Hermes #15080 再現）
     - `no_change`: いずれも変化なし
     - `unknown`: 反映遅延で 15 分以内に確認できない / 他利用と分離不能
  5. `billing_delta_class=unknown` の場合の **fallback**: outcome は `conditional/tool_use_observed_but_billing_unknown` または `conditional/messages_api_only` に倒す（supported に昇格させない）。
  6. 同一 account で他に Claude を使っている場合（並行 session 等）は **必ず unknown** に倒し、別 account / 静穏時間帯での再評価を follow-up Issue に書く。

- **Approach A の JSONL は Approach B の判定に流用しない**（architect 指摘の経路不整合を解消）。

console 確認結果は `apply_console_confirmation` 関数で probe stdout JSON に後付けマージする。生 console スクリーンショットは Issue / repo に貼らない（allowlist 外）。

#### B-4. （削除）tool_use 観測時の追加 1 ターン

**Non-Goal に降格**（contrarian C2 / architect A2 指摘）。理由:

- 公式仕様準拠の tool_result body を完全に固めないと、follow-up 400 を「API 非対応」と「probe 入力不備」のどちらに分類すべきか判別不能。
- supported 判定は **「200 + tool_use 観測 + console subscription_billing 確認」** で完結する。追加ターンを投げる必要はない。
- 追加ターンが必要だと後から判明したら、follow-up Issue（#9 着手前）で実施する。

`additional_turn_attempted` は allowlist に残すが、本 Issue では常に `false` で出力する（将来 follow-up で true 値を扱えるよう field 自体は保持）。

時間 cap は **B 全体で 60 分**（1 リクエストなので普通は数秒〜数十秒）。

#### B-5. secret / PII 投稿制御

- Issue コメント / `research-log.md` / probe stdout 共通の **allowlist フィールド一覧**（これ以外は出力禁止）:

  | field | 型 | 用途 |
  |---|---|---|
  | `approach` | string enum (`A`/`B`/`C`) | どの Approach の結果か |
  | `status` | `int \| null` | HTTP status |
  | `outcome` | string enum | outcome 表の 4 値 |
  | `sub_outcome` | string enum | outcome 表の sub 値 |
  | `redacted_error_type` | string | response body の `error.type` をそのまま（enum 想定で機密性なし） |
  | `error_code` | string | null | response body の `error.code` 等の再分類用 |
  | `message_class` | string | error.message を `permission` / `not_available` / `invalid_request` / `other` に正規化した分類 |
  | `usage_token_counts` | object | `{input, output, cache_creation, cache_read}` 数値のみ |
  | `billing_observation` | string enum | `subscription_billing` / `extra_usage_billing` / `console_confirmation_required` / `not_applicable` |
  | `billing_delta_class` | string enum | `incremented_subscription` / `incremented_extra_usage` / `no_change` / `unknown` / `not_applicable` |
  | `console_checked_at` | string \| null | console 確認時刻（ISO 8601 UTC、`account_id` 等は出さない） |
  | `console_window_minutes` | int | 確認窓（固定値 15） |
  | `model_used` | string | model 名（Anthropic 公式定数のみ） |
  | `stop_reason` | string enum \| null | Anthropic 仕様の停止理由 |
  | `tool_use_observed` | bool | tool_use block が response に出たか |
  | `additional_turn_attempted` | bool | 本 Issue では常に false（B-4 は Non-Goal、field は将来用に保持） |
  | `elapsed_seconds` | int | 当該 Approach の経過秒（timeout 等で必要） |
  | `stage` | string enum | `approach_a_help` / `approach_a_docs` / `approach_a_probe` / `approach_a_complete` / `approach_b_credential` / `approach_b_request` / `approach_b_console_check` / `approach_c_pricing_fetch` / `approach_c_estimate` |
  | `cli_help_has_betas_flag` | bool | Approach A: `--betas` 相当の有無 |
  | `cli_probe_tool_use_observed` | bool | Approach A: CLI probe で tool_use が出たか |
  | `exit_code` | int | probe.py / probe.sh の exit code（B-2-b の表参照） |
  | `notes` | string | プレースホルダ済みの一文（80 文字以内、機密語不可） |

- 禁止: raw response body, raw error body, `access_token`, `account_id`, `request_id` (`x-request-id` header), `Authorization` header, cookie, `home_path` (`/home/shohei` 文字列そのもの), prompt transcript 全文。
- `features/10-*/research-log.md` に書く場合も同じ allowlist + 「<account_id_redacted>」「<request_id_redacted>」「<home_redacted>」「<probe_prompt_redacted>」のプレースホルダで通す。

### Approach C: 公式 API key 経路コスト試算（実機なし、概算レンジ扱い）

**判定対象外**: Approach C の出力 JSON における `outcome` / `sub_outcome` フィールドは **最終 outcome 判定に使わない**（pricing fetch の参考情報専用）。final outcome は **Approach B 結果コメント + 結論コメント** のみが authoritative。後続 parser や集計ツールは `approach == "C"` または `stage == "approach_c_*"` を見て Approach C 出力を判定計算からスキップすること。固定値として `outcome: "undetermined"` / `sub_outcome: "usage_schema_unknown"` を allowlist 制約のために emit するが、これは非判定を示す中立値（migration 観点：「判定不能を意味する undetermined」ではなく「判定処理に含めない参考情報」）。

- Anthropic 公式 pricing は `computer_use_probe.sh` の `pricing` サブコマンド（または同等の独立 `curl` 手順）で取得する。**WebFetch は使わない**（再実行性を担保）。取得 URL は docs.claude.com の pricing ページに固定（README に明記）。: input / output / cache_creation / cache_read 単価を model 別に取得。
- 仮定（**全部明示 + 感度分析あり**）:
  - 1 セッション = `step ∈ {25, 50, 100}` step
  - 1 step あたり screenshot input = 1280×800 PNG → 公式画像トークン式に従う（取れなければ "1500 ± 5x" と注記）
  - 1 step あたり assistant 応答 = 200 ± 3x tokens
  - cache hit 率 = `{0, 50, 90}%`
  - sessions/月 = `{30, 300}` の 2 ケース
- 試算: `step × (image_tokens + assistant_tokens) × price_per_token × sessions/月` を **オーダー（10x の精度）** として記録。
- 出力: `cost_estimate.md` に表 + 注記 + 「概算レンジ。実機なし。確度: 低」を明記。

### コード去就（DoD と整合）

- `features/10-*/research/` 配下は **本 PR に含まれた状態で squash merge** する（DoD に含む）。
- **最終判定後の運用**:
  - `outcome=supported` → README に「#9 で再利用可。再評価 expiry: <merge 日 + 90 日>」を追記して keep。
  - `outcome=conditional` / `unsupported` → README に「known-invalid outcome、再利用禁止、follow-up #X 参照」を追記して keep（履歴として）。
  - `outcome=undetermined` → README に「再評価必須、現状値は無効」を追記して keep。
- **delete は本 Issue ではしない**（gloop の squash merge サイクルに乗せるため）。Issue #10 最終コメントには「keep + 利用条件」を明記。

### 失敗時の振る舞い（outcome 体系に従う）

**主判定は常に Approach B**。Approach A は capability 観測のみで、A の outcome は最終 outcome に上書きしない（A timeout / failure でも B の結果が最終 outcome）。A が timeout したら参考コメントとして Issue に投稿し、B を必ず実施する。`usage_schema_unknown` は **観測メタデータ** として `notes` に記録するだけで、最終 outcome を `undetermined` に上書きしない（B-3 で公式裏付けが取れない usage field を出さなければよいだけ）。

| 状況（B の結果） | outcome | 追加処理 |
|---|---|---|
| B 200 + tool_use なし | `conditional, messages_api_only` | (c) として #9 に推奨。follow-up なし |
| B 200 + tool_use あり + console 確認なし or `billing_delta_class=unknown` | `conditional, tool_use_observed_but_billing_unknown` | (c) として #9 に推奨。follow-up なし |
| B 200 + tool_use あり + `billing_delta_class=incremented_extra_usage` | `conditional, extra_usage_billing` | (c) として #9 に推奨。Hermes #15080 同型ケース |
| B 401 / 403 with error.type != permission_error | `undetermined, auth_failure` | follow-up Issue 起票、#9 保留 |
| B timeout (60 分 cap 超過) | `undetermined, timeout` | follow-up Issue 起票、#9 保留 |
| B 403 + permission_error | `unsupported, api_explicit_reject_after_auth` | (b) として #9 に推奨（API key 経路または保留） |
| B 400 + invalid_request_error + Computer Use is not available | `unsupported, beta_not_allowed` | (b) として #9 に推奨 |
| B 200 + tool_use 観測 + `billing_delta_class=incremented_subscription` | `supported, tool_use_observed_and_subscription_billing` | (a) として #9 に推奨 |

## 実装対象（既存関数編集なし。成果物は原則新規）

**既存関数編集なし**（既存 .py / .sh / .rs / .ts のロジックを書き換えない）。成果物は原則新規ファイル。例外として **既存ファイルへの編集が許可されるのは以下のみ**:

- `features/10-phase-3-.../state.json`（既存）: **`state.mjs set/inc` 経由のみ更新**。直接 Edit/Write 禁止。許可される差分は `updated_at` の更新と `phases.final_review` / `phases.merge` の状態遷移のみ。他の既存キー（`issue`, `slug`, `created_at`, `loops.*`, `raised_issues`, `phases.*` のその他サブキー、未知キー）は **完全保持**（T12_state_invariants で検証）。
- `features/10-phase-3-.../plan.md`（既存、本ファイル）: codex-design レビュー反映時のみ更新可。実装フェーズでの編集は禁止。

それ以外の編集許可パス（**すべて新規ファイル**）:

- `features/10-phase-3-.../research/**`（新規、必須成果物）
- `features/10-phase-3-.../research-log.md`（新規、必須成果物）
- `features/10-phase-3-.../test-spec.md`（新規、必須成果物 — project_type: jobs）
- `features/10-phase-3-.../test-summary.json`（新規、必須成果物 — STEP 7 用要約）
- `features/10-phase-3-.../codex-input.md` / `codex-design.yaml` / `codex-final.yaml` 系（gloop ツーリングが自動生成、許可）
- `features/10-phase-3-.../debug-spec.md`（新規、**任意成果物**。Codex final で failing finding が出た場合のみ作成）
- `features/10-phase-3-.../rejection.md`（新規、必須成果物 — `init-feature.mjs` が自動生成し設計議論の決着履歴を残す。再評価時の判断履歴として keep）
- `features/10-phase-3-.../ci.log`（新規、必須成果物 — project_type: jobs で自動テストフレームがないため、T01/T09/T10/T10b/T11/T12/T13 等の手動実行証跡を残す唯一の枠）
- `features/10-phase-3-.../fixtures/*.json`（新規、`--classify-fixture` 用テスト fixture、必須成果物）

**触らない（implementer / orchestrator 共通禁止）**: `gateway/**`, `bot.py`, `_research/` (古い配置案), `jobs/**`, `lib/**`, `bin/**`, `systemd/**`, `.env`, `~/.claude/.credentials.json` (read only, 変更禁止)。

### 必須成果物（DoD と同一リスト）

| パス | 種別 | 役割 |
|---|---|---|
| `features/10-*/research/README.md` | 新規 | 隔離理由・本番 import 禁止・CLI/credential schema version・expiry 方針・pricing 取得 URL |
| `features/10-*/research/computer_use_probe.sh` | 新規 | Approach A 実行（claude --help / docs curl / CLI probe） + Approach C の `pricing` サブコマンド |
| `features/10-*/research/computer_use_probe.py` | 新規 | Approach B 実行 + `--classify-fixture <json_path>` ローカル分類モード（redaction + allowlist JSON 出力） |
| `features/10-*/research/cost_estimate.md` | 新規 | Approach C 試算と仮定（概算レンジ） |
| `features/10-*/research-log.md` | 新規 | 実行ログの redacted 抜粋、outcome 判定根拠 |
| `features/10-*/test-spec.md` | 新規 | project_type: jobs の手動チェックリスト（T01..T13）+ console 確認手順（B-3） |
| `features/10-*/fixtures/*.json` 計 12 件 | 新規 | `--classify-fixture` 用 fixture（B-2-a truth table の各行 1 件、合計 12 件）: `200_tool_use.json` / `200_end_turn.json` / `200_other_stop_reason.json` / `400_beta_not_allowed.json` / `400_invalid_request_other.json` / `400_other_error_type.json` / `400_null_error_type.json` / `401_auth.json` / `403_permission.json` / `403_other.json` / `5xx_timeout.json` / `429_rate_limit.json` |

`features/**` は **前提条件節で検証する** guard_paths.allow_orchestrator_write に入っているので、orchestrator が直接書ける（STEP 6 は implementer 委譲不要、orchestrator が `gh issue comment` までやる）。前提検証が失敗したら implementer 委譲にフォールバック。

**fallback 時の責務表（前提検証が失敗した場合）**:

| 作業 | 担当 |
|---|---|
| `features/10-*/research/**` のファイル生成 | implementer teammate |
| `features/10-*/research-log.md` / `test-spec.md` / `fixtures/**` の生成 | implementer teammate |
| `--classify-fixture` の実機実行と T13 検証 | implementer teammate |
| Approach A 実機実行（`claude --help` / `curl` / CLI probe） | implementer teammate |
| Approach B 実機実行（OAuth token 直叩き） | implementer teammate |
| Approach B-3 console 手動確認 | orchestrator（test-spec.md の手順に従って実行者が手動入力、結果を JSON にマージ） |
| Issue #10 / #9 への `gh issue comment` 投稿 | orchestrator |
| `state.mjs set/inc` による phase 遷移 | orchestrator |
| T10 / T10b / T11 / T12 の最終チェック | orchestrator |

## テスト計画（手動チェックリスト、project_type: jobs）

| ID | 内容 | 期待値 |
|---|---|---|
| T01 | Approach A 実行: `claude --help` grep + 公式 docs 確認 + プローブ 2 種（通常 / Computer Use 起動促し） | A の JSON summary が Issue #10 にコメント。`approach="A"`, `outcome`, `sub_outcome`, `cli_help_has_betas_flag`, `cli_probe_tool_use_observed` (bool), `stage` が allowlist 内で記録される |
| T02_supported_path | Approach B: API が 200 + tool_use + console で subscription 消費確認できた場合 | `outcome=supported, sub=tool_use_observed_and_subscription_billing`、`billing_observation="subscription_billing"`、`billing_delta_class="incremented_subscription"`、`additional_turn_attempted=false`（B-4 Non-Goal）、`tool_use_observed=true` |
| T02b_conditional_billing_unknown | Approach B: 200 + tool_use あり、console 未確認 or `billing_delta_class=unknown` | `outcome=conditional, sub=tool_use_observed_but_billing_unknown`、`billing_observation="console_confirmation_required"`、`billing_delta_class="unknown"` |
| T02c_conditional_extra_usage | Approach B: 200 + tool_use あり + console で extra_usage 増加（Hermes #15080 再現） | `outcome=conditional, sub=extra_usage_billing`、`billing_observation="extra_usage_billing"`、`billing_delta_class="incremented_extra_usage"`、(c) として #9 推奨 |
| T03_conditional_messages_api | Approach B: API が 200 + tool_use なし | `outcome=conditional, sub=messages_api_only`、(c) として #9 推奨 |
| T04a_unsupported_beta_not_allowed | Approach B: 400 + `error.type=invalid_request_error` + message に "Computer Use is not available" | `outcome=unsupported, sub=beta_not_allowed`、`message_class="not_available"`、fixture: `400_beta_not_allowed.json`、(b) として #9 推奨 |
| T04b_unsupported_permission | Approach B: 403 + `error.type=permission_error` | `outcome=unsupported, sub=api_explicit_reject_after_auth`、`message_class="permission"`、fixture: `403_permission.json`、(b) として #9 推奨 |
| T05_undetermined_auth | Approach B: 401 / 403 with error.type != permission_error | `outcome=undetermined, sub=auth_failure`、`redacted_error_type` 記録、follow-up Issue 自動起票 |
| T06_undetermined_timeout | Approach A or B が 60 分 cap を超過 | `outcome=undetermined, sub=timeout`、`elapsed_seconds`, `stage` 必須、中間 JSON summary がコメント、follow-up 起票 |
| T07_undetermined_probe_input | Approach B: 400 with model 名不正等（`error.type != invalid_request_error` または message に "Computer Use" を含まない） | 1 度だけ docs から取得した model 名でリトライ。再失敗で `outcome=undetermined, sub=probe_input_error` |
| T08_undetermined_schema | `~/.claude/.credentials.json` 不存在 or 未知 schema / JSONL 未知 schema | `credential_missing` / `credential_schema_unknown` / `usage_schema_unknown` のいずれかを記録、判定には使わない、follow-up 起票 |
| T09_cost_estimate | Approach C: cost_estimate.md にレンジ + 仮定 + 感度分析が書かれる | 「概算オーダー、確度: 低」が明記 |
| T10_secret_grep_extended | **grep 対象**: Issue コメント（A/B/C/結論 + #9 クロスポスト全件）、`features/10-*/research-log.md`、`features/10-*/research/` 配下の **実行生成ログ**（probe stdout 等の動的成果物）。**grep 対象外**: `plan.md`、`research/README.md`、`research/computer_use_probe.{sh,py}`、`research/cost_estimate.md`、`test-spec.md`、`fixtures/*.json`（コード成果物の固定文字列やプレースホルダは grep 対象から外す）。検出対象パターン: `access_token`, OAuth credential JSON の `access_token` 値、`account_id` (UUID 形式), `x-request-id` 値, `Authorization`, cookie, `/home/shohei` 文字列 — **どれもヒットしない**。prompt 本文 grep は廃止（plan・コードの固定 prompt は非機密扱い、プレースホルダ運用で十分）。 |
| T10b_code_dangerous_output_grep | `computer_use_probe.py` / `computer_use_probe.sh` を静的 grep | `print(response.text)` / `print(response.content)` / `print(headers)` / `print(.*Authorization)` / `f".*{token}` / `request_id` を直接 print する記述が **どれもヒットしない**。redact 関数または allowlist field のみを print する設計であることを保証 |
| T11_conclusion_comment | Issue #10 最終コメント + Issue #9 クロスポスト | 最終 outcome / 3 択判定 / コード去就（keep + 理由）/ #9 推奨アクションの 4 項目が allowlist 形式で残る |
| T12_state_invariants | `state.mjs` 経由で `phases.final_review` / `phases.merge` を `passed` に遷移させた後の差分検証 | 更新前 state.json と更新後 state.json を `jq -S .` で正規化比較し、**許可差分**は `.updated_at`（任意の新値）と `.phases.final_review` `.phases.merge`（`"pending"`→`"passed"`）のみ。全 top-level keys（`created_at`, `issue`, `slug`, `phases`, `loops`, `raised_issues`, 未知キー含む）が保持され、`.phases.*` の他サブキーと `.loops.*` 配下の数値、`.raised_issues` 配列も完全一致 |
| T13_classify_fixture | `python3 computer_use_probe.py --classify-fixture fixtures/<name>.json` を **12 件** の fixture（B-2-a truth table の各行 1 件、行番号 1〜12）それぞれに対して実行 | 各 fixture の期待 outcome / sub_outcome / exit code（B-2-a 表の各行どおり）と一致。fixture 名と期待値の対応は B-2-a 表が単一ソース、`test-spec.md` でも同じ表をコピーする |

各 outcome ごとの **期待 JSON 例**（すべて B-5 allowlist 内のフィールドのみ使用、`additional_turn_attempted` は常に false）:

```json
// supported (apply_console_confirmation 適用後)
{"approach": "B", "status": 200, "outcome": "supported", "sub_outcome": "tool_use_observed_and_subscription_billing",
 "model_used": "claude-sonnet-4-5", "stop_reason": "tool_use",
 "tool_use_observed": true, "additional_turn_attempted": false,
 "billing_observation": "subscription_billing",
 "billing_delta_class": "incremented_subscription",
 "console_checked_at": "2026-06-27T07:15:00Z", "console_window_minutes": 15,
 "usage_token_counts": {"input": 1532, "output": 47, "cache_creation": 0, "cache_read": 0},
 "stage": "approach_b_console_check", "elapsed_seconds": 14, "exit_code": 0,
 "notes": "console subscription_used 増加を確認"}

// conditional (tool_use observed but billing unknown)
{"approach": "B", "status": 200, "outcome": "conditional", "sub_outcome": "tool_use_observed_but_billing_unknown",
 "model_used": "claude-sonnet-4-5", "stop_reason": "tool_use",
 "tool_use_observed": true, "additional_turn_attempted": false,
 "billing_observation": "console_confirmation_required",
 "billing_delta_class": "unknown",
 "console_checked_at": null, "console_window_minutes": 15,
 "usage_token_counts": {"input": 1532, "output": 47, "cache_creation": 0, "cache_read": 0},
 "stage": "approach_b_request", "elapsed_seconds": 6, "exit_code": 0}

// conditional (messages_api_only)
{"approach": "B", "status": 200, "outcome": "conditional", "sub_outcome": "messages_api_only",
 "model_used": "claude-sonnet-4-5", "stop_reason": "end_turn",
 "tool_use_observed": false, "additional_turn_attempted": false,
 "billing_observation": "console_confirmation_required",
 "billing_delta_class": "unknown",
 "console_checked_at": null, "console_window_minutes": 15,
 "usage_token_counts": {"input": 532, "output": 12, "cache_creation": 0, "cache_read": 0},
 "stage": "approach_b_request", "elapsed_seconds": 4, "exit_code": 0}

// unsupported
{"approach": "B", "status": 403, "outcome": "unsupported", "sub_outcome": "api_explicit_reject_after_auth",
 "redacted_error_type": "permission_error", "error_code": null, "message_class": "permission",
 "tool_use_observed": false, "additional_turn_attempted": false,
 "billing_observation": "not_applicable", "billing_delta_class": "not_applicable",
 "console_checked_at": null, "console_window_minutes": 15,
 "stage": "approach_b_request", "elapsed_seconds": 1, "exit_code": 0}

// undetermined (timeout)
{"approach": "B", "status": null, "outcome": "undetermined", "sub_outcome": "timeout",
 "elapsed_seconds": 3600, "stage": "approach_b_request",
 "tool_use_observed": false, "additional_turn_attempted": false,
 "billing_observation": "not_applicable", "billing_delta_class": "not_applicable",
 "console_checked_at": null, "console_window_minutes": 15, "exit_code": 3}
```

## 完了条件 (DoD)

- Issue #10 に Approach A / B / C 結果コメント + 結論コメントの **4 件以上** が残る（すべて B-5 allowlist 形式 JSON）
- Issue #9 へクロスポストコメント 1 件が残る
- **必須成果物**（実装対象節の表と同一リスト）が本 PR に含まれた状態で squash merge される：
  - `features/10-*/research/README.md`
  - `features/10-*/research/computer_use_probe.sh`
  - `features/10-*/research/computer_use_probe.py`
  - `features/10-*/research/cost_estimate.md`
  - `features/10-*/research-log.md`
  - `features/10-*/test-spec.md`
  - `features/10-*/fixtures/*.json`（12 件、B-2-a truth table と 1 対 1 対応、T13_classify_fixture で回帰検証）
  - `features/10-*/rejection.md`（init-feature.mjs 生成、設計議論の決着履歴）
  - `features/10-*/ci.log`（手動チェックリスト実行証跡、T01〜T13 の結果）
  - `features/10-*/test-summary.json`（STEP 7 用要約、codex final review 入力）
  - （keep が確定。delete は本 Issue 対象外。`debug-spec.md` は任意成果物で含まれなくても良い）
- `outcome=undetermined` の場合 follow-up Issue が自動起票される
- `features/10-*/state.json` の `phases.final_review` が `passed`、`phases.merge` が `passed`（`state.mjs` 経由のみ）
- T10_secret_grep_extended で **token / account_id / request_id / Authorization / cookie / home path** いずれも T10 で定義した grep 対象（Issue コメント / research-log.md / research/ 配下の **実行生成ログ**）に出現しないこと。grep 対象から `plan.md` / `research/README.md` / `research/computer_use_probe.{sh,py}` / `research/cost_estimate.md` / `test-spec.md` は明示的に除外する（コード成果物の固定文字列・プレースホルダは検出対象外）
- T12_state_invariants: `state.mjs` 経由更新後も既存キー（`issue`, `slug`, `created_at`, `loops.*`）が破壊されないこと

## オープン論点の決着（自律判断）

| 論点 | 決着 |
|---|---|
| Approach A / B の時間 cap | 各 60 分 |
| 課金経路の自動判定方法 | A は capability/CLI schema 観測専用、課金判定には使わない。B = API response body の usage + Anthropic console 有人確認（許容） |
| 評価コードの配置 | `features/10-phase-3-.../research/`（本番領域非汚染、orchestrator 直接書き、features ディレクトリ単位で運用） |
| 評価コードの去就 | **本 PR では keep**。最終 outcome に応じて README に再評価条件 / 再利用禁止 / expiry を追記。delete は本 Issue 対象外 |
| Computer Use tool_result ループ検証 | **本 Issue では実施しない（Non-Goal）**。supported 判定は「1 リクエスト 200 + tool_use + console 確認」で完結。`additional_turn_attempted` は常に false |
| `(b) 動かない` の定義 | **認証済みリクエストに対し API が Computer Use を明示拒否した場合のみ**（403 + permission_error / 400 + invalid_request_error + "Computer Use is not available"）。401/403 with other error.type/timeout は `undetermined` |
| docs 取得の責務 | `computer_use_probe.sh` の `curl` に統一。WebFetch / orchestration 環境機能は依存先にしない |
| guard_paths 検証 | 前提条件節の jq コマンドで確認（失敗時は implementer 委譲フォールバック） |
| エラー分類優先順位 | `status` → `error.type` → 正規化済み `error.message` の順。文字列一致は補助のみ |

## Issue body 抜粋（参照用）

Issue #10 本体の「決定事項」「成果物」「失敗条件」「Phase 位置付け」「DoD」を満たすこと。詳細は `gh issue view 10` で参照。
