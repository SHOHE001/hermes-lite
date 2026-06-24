# Non-Goals (本 Issue で実装しない項目 — Codex は越権指摘しないこと)
- 既存 Discord runner のトーン文言を**書き換える**こと（移植のみ。差分は別 Issue）
- SOUL.md と CLAUDE.md の責務分担の意味的な整理（Phase 2 で扱う）
- 全 jobs への共通適用（Phase 2）
- bin/run-claude.sh の引数構築変更
- 複数人格切替 / per-job 上書き
- SOUL.md にメタデータ（front matter / 注記コメント）を入れること（**prompt 本文に汚染を入れない**ため）

# In-Scope / Out-of-Scope
| In-Scope | Out-of-Scope |
|---|---|
| リポジトリルートに `SOUL.md` を新設（旧 `APPEND_SYSTEM_PROMPT` の **そのままの移植先**） | bin/run-claude.sh への組み込み（Phase 2 別 Issue。jobs ごとの互換確認が必要） |
| `gateway/discord/claude_runner.py` を SOUL.md ファイル読み込み方式に差し替え | jobs (`jobs/ping/` 等) への `--append-system-prompt` 適用（Phase 2） |
| Python 側に `_DEFAULT_SOUL`（旧 APPEND_SYSTEM_PROMPT そのまま）を fallback として残す。SOUL.md が不在 / 空 / 読込失敗のいずれでも `_DEFAULT_SOUL` を使い、warning を出す → **旧挙動と完全互換** | 複数人格切替、per-job 上書き機構 |
| CLAUDE.md `### 1. 本家を入れない理由` に 1 行注記追加 | CLAUDE.md の責務再編、SOUL.md の人格そのものの刷新（中身は移植のみ） |
| 後方互換 alias: `APPEND_SYSTEM_PROMPT = _DEFAULT_SOUL` を残す（既存 import 互換維持） | SOUL.md と CLAUDE.md の責務再編（Phase 2 別 Issue） |

# Test summary
```json

```

