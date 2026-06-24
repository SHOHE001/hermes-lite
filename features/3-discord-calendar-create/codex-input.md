# Non-Goals (本 Issue で実装しない項目 — Codex は越権指摘しないこと)
- **`lib/disallowed-tools.txt` は本 Issue で書き換えない**。Calendar.create は disallowed のまま、executor の `--allowed-tools` だけで一時解禁。
- **`gateway/discord/claude_runner.py` は触らない**。
- **`gateway/discord/requirements.txt` には新規依存を追加しない** (標準ライブラリのみで完結)。
- **MCP server 直接呼び出し / Google Calendar API 直叩き executor は採用しない** (比較表 C 参照)。
- **systemd-run 後の即時失敗観測の自動化はしない** (stale executing / approved の自動 sweep で最終的に整合)。
- **DB schema v2 以降への migration は本 Issue では実装しない**。
- **別 MCP server 名 / 別 profile での Calendar.create 対応はしない** (MCP tool 名は定数固定: `mcp__claude_ai_Google_Calendar__create_event`)。

# In-Scope / Out-of-Scope
| In-Scope | Out-of-Scope |
|---|---|
| `lib/approvals.py` (sqlite ヘルパー + state machine + schema version check + ID 衝突 retry + 認可ユーザー管理) | 承認 GUI / Discord Interactive Button |
| `lib/approvals_executor.py` (LLM executor + 副作用後検出 + `failed_after_side_effect` 遷移) | Discord 以外の承認チャネル |
| `lib/approvals.sh` | Calendar.create 以外の write action 解禁 |
| `var/approvals.sqlite` | mail-watch (#2) → proposer の自動橋渡し |
| `gateway/discord/bot.py` (flag check → optional import → approval 経路。flag off で完全に skip) | executor 失敗時の自動 retry |
| `gateway/discord/approval_handler.py` (handle(text, user_id) 内部認可検証) | 複数承認者の役割別承認 |
| `gateway/discord/config.py` に HERMES_HOME / APPROVALS_DB / APPROVAL_COMMANDS_ENABLED 追加 | 承認 rollback API |
| `jobs/approval-demo-proposer/{prompt.md, job.env}` (Bash で `python3 -c` 使用、jq 非依存) | DB schema v2 以降への自動 migration |
| `bin/run-claude.sh` に `export HERMES_HOME=...` の 1 行追加 | 短縮 ID / prefix lookup |
| `docs/discord-approval.md` (信頼境界 + 副作用後検出 + failed_after_side_effect 説明 + feature flag opt-in + migration notice + CLI contract) | 重複検知 |
| `tests/test_approvals.py` (Python 標準 unittest) | bot プロセスのリスタート手順自動化 |
| `.gitignore` に `var/*` + `!var/.gitkeep` 追加 | MCP server / Google Calendar API の直接呼び出し |
| `var/.gitkeep` | Calendar 側余分 event の自動 cleanup |
| | 別 MCP server 名 / profile 対応 (MCP tool 名は定数固定) |

# Test summary
```json

```

