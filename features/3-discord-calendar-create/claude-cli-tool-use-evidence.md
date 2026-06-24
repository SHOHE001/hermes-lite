# claude -p `--output-format json` の tool_use evidence 実測

`lib/approvals_executor.py::extract_tool_calls()` の実装根拠として、実際に動いている `claude` CLI (v2.1.187, gen8 / 2026-06-24) の出力構造を実測した結果を保存する。

## 実測サンプル

### サンプル 1: tool 呼び出しなし (jobs/ping)

```bash
bin/run-claude.sh ping
# logs/ping/20260624-134143.json
```

トップレベル keys:

```json
[
  "api_error_status", "duration_api_ms", "duration_ms", "fast_mode_state",
  "is_error", "modelUsage", "num_turns", "permission_denials",
  "result", "session_id", "stop_reason", "subtype", "terminal_reason",
  "time_to_request_ms", "total_cost_usd", "ttft_ms", "ttft_stream_ms",
  "type", "usage", "uuid"
]
```

- `tool_uses` キーなし
- `messages` キーなし
- `usage.tool_use_count` キーなし
- `usage.server_tool_use` あり (`{web_search_requests: 0, web_fetch_requests: 0}`)
- `result` = `"稼働確認OK"` (LLM の最終応答テキストのみ)

### サンプル 2: WebSearch を 1 回呼んだケース

```bash
claude -p "WebSearch で ... を検索し、結果の件数だけ '結果N件' という形式で答えてください" \
  --output-format json --allowed-tools WebSearch \
  --max-turns 3 --model sonnet
# /tmp/claude-evidence/out.json
```

トップレベル keys: サンプル 1 と完全に同じ。

- `result` には `"結果8件\n\nSources: ...."` (LLM が tool を呼んだ結果の自然文)
- `usage.server_tool_use.web_search_requests` = (集計値、tool 呼び出し回数の集計のみ)
- **tool_uses / messages / tool_use_count キーは依然として存在しない**

## 結論

claude CLI v2.1.187 の `--output-format json` は **tool_use の詳細 (name / input) を返さない**。これは plan v6 §「extract_tool_calls の挙動」case 4 (空リスト) に相当する。

### extract_tool_calls() の挙動 (実装)

実 claude 出力に対して `extract_tool_calls()` は:

1. `tool_uses` キーがあるか → なし
2. `messages` キーを走査 → なし (キーが存在しない)
3. `usage.tool_use_count` キー → なし (= case 3 不発)
4. case 4: 空リスト `[]` を返す

→ executor から見ると **常に `create_calls == 0`** となり、`failed_after_side_effect` (件数違反 `create_event=0`) に倒れる。

### 設計上の含意

これは **fail-closed**: 実際に LLM が `mcp__claude_ai_Google_Calendar__create_event` を 1 回呼んで Calendar に event を作成しても、CLI の出力 JSON にその痕跡が残らないので、executor は「副作用が起きたかもしれないが確認できない」と判定して `failed_after_side_effect` に倒す。Discord に WARN + 手動 cleanup 指示を送る。

副作用前保証は提供できないが、副作用が起きたことを **黙って `executed` に倒すことはない** (副作用後検出の最低限の責務を果たす)。

将来 claude CLI が tool_use の詳細を JSON に含めるようになれば、`extract_tool_calls()` の case 1 / case 2 が動き、副作用一致検証が活きる。

### 案 (将来の追加観測経路)

- claude CLI に `--include-tool-uses` 等のフラグが追加されたら採用
- `claude -p --output-format stream-json` を採用して assistant message ごとの content blocks を parse する経路 (現状は実装コストが高いため見送り)
- MCP `list_events` で「直近作成された event」を検索する事後 reconciliation (副作用前後の差分検出)

## サンプル取得手順 (再現)

```bash
# ping (tool 呼び出しなし)
cd ~/プロジェクト/hermes-lite
bin/run-claude.sh ping
ls logs/ping/*.json | tail -1 | xargs jq 'keys'

# WebSearch (tool あり)
~/.local/bin/claude -p "WebSearch で X を検索し件数だけ答えてください" \
  --output-format json --allowed-tools WebSearch \
  --max-turns 3 --model sonnet --permission-mode default \
  --max-budget-usd 0.50 > /tmp/out.json
jq 'keys' /tmp/out.json
jq '.usage.server_tool_use' /tmp/out.json
```

実行日時: 2026-06-24, claude binary: `/home/shohei/.local/bin/claude` -> `/home/shohei/.local/share/claude/versions/2.1.187`
