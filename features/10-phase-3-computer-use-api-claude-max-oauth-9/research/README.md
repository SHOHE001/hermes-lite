# Issue #10 research/

**本ディレクトリは Issue #10 専用の評価コードです。本番からの import を禁止します。**

このコードは Claude CLI / `~/.claude/.credentials.json` の OAuth credential schema、Anthropic API の Computer Use beta（`computer-use-2025-01-24`）、docs.claude.com の HTML 構造に依存します。これらは Anthropic 側で随時変更されるため、本コードを本番経路（`gateway/discord/` 等）から再利用してはいけません。

## 依存環境（評価実施時点で記録）

- `claude` CLI: PATH 上に存在する想定（version は `claude --version` で確認、`research-log.md` に記録）
- `~/.claude/.credentials.json`: 既知 schema は `oauthAccount.access_token` / `access_token` / `token` / `claudeAiOauth.accessToken` のいずれか。schema 変更時は probe.py が `credential_schema_unknown` で停止する
- Computer Use beta header: `anthropic-beta: computer-use-2025-01-24`
- Model: `claude-sonnet-4-5`（実行時に docs から取得して上書き可）
- Python: 標準ライブラリのみ（`urllib.request`）。`httpx` 等の依存追加は禁止

## ファイル

| ファイル | 用途 |
|---|---|
| `computer_use_probe.sh` | Approach A（capability 観測）+ `pricing` サブコマンド（Approach C 用 curl） |
| `computer_use_probe.py` | Approach B（raw HTTP probe）+ `--classify-fixture <path>`（実機なし分類）+ `--apply-console-confirm <enum>`（console 確認後処理） |
| `cost_estimate.md` | Approach C: 月次コスト概算（実機なし、確度: 低） |

## 使い方

```bash
# Approach A
bash computer_use_probe.sh approach-a

# Approach B（実機、credential を読む）
python3 computer_use_probe.py approach-b > /tmp/probe_b.json
# console 確認後、後処理で billing 情報をマージ
cat /tmp/probe_b.json \
  | python3 computer_use_probe.py --apply-console-confirm incremented_subscription \
      --checked-at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# fixture 分類（実機なし、回帰テスト用）
python3 computer_use_probe.py --classify-fixture ../fixtures/200_tool_use.json

# Approach C pricing 取得
bash computer_use_probe.sh pricing
```

## 再利用条件（最終 outcome 後に追記）

最終 outcome に応じて末尾に以下のいずれかを追記する:

- `supported`: 「#9 で再利用可。再評価 expiry: <merge 日 + 90 日>」
- `conditional`: 「known-invalid outcome、再利用禁止、follow-up #X 参照」
- `unsupported`: 「明示拒否確認済、再利用禁止」
- `undetermined`: 「再評価必須、現状値は無効」

## 本 PR 実行時の最終判定（2026-06-27）

- 最終 outcome: **`undetermined / network_error`**（実態は HTTP 429 rate_limit_error、OAuth 認証は通過済み）
- 再利用条件: **再評価必須、現状値は無効**
- follow-up Issue: **#11** （rate_limit クールダウン後リトライ）
- #9 への推奨: **保留**（OAuth 経路は通ったが Computer Use 可否は未確認）
