# hermes-lite

NousResearch/hermes-agent の体験を、Claude Code (Claude Max 枠) の上で再現する自作プロジェクトの土台。
このディレクトリ自体は**まだ何も実装していない骨組み**。Hermes本家は入れない。

## 不変ルール

### 1. 本家を入れない理由

Hermes 本家を Anthropic OAuth (Claude Pro/Max) で動かしても、Anthropic 側仕様で **subscription quota は消費できず extra usage バケットからしか引かれない** (issue #15080)。Max 枠で回したい本プロジェクトの目的と噛み合わないため、本家は採用せず「Hermesぽい体験を Claude Code 上に薄く実装する」方針を取る。

### 2. 課金経路 (厳守)

- 必ず **Claude Max の OAuth 枠** で動かす (claude-watch と同じ)
- Anthropic API key / OpenRouter / Nous Portal などの **従量課金経路は使わない**
- 実行系はすべて **`claude -p` を subprocess で呼ぶ形** を基本とする (自前で `~/.claude/.credentials.json` を読んで native Anthropic を叩くと #15080 と同じ罠を踏む)
- Hermes 本家の Python ランタイム・uv・SOUL.md・skill 自動生成器などはインストールしない

### 3. ビルド方針

- 各機能は **既存資産で代替可能ならまず代替で済ます**。新規実装は代替不可なものに限る
- 機能ごとに必ず「何を作るか」「どこに置くか」をユーザーと合意してから着手する (推測禁止ルール継承)
- 外部送信 (Telegram bot post 等) は CLAUDE.common.md の送信系操作の事前確認ルールに従う

## 既存資産との関係 (Hermesの代替に使える)

| Hermes機能 | gen8で稼働中の代替 |
|---|---|
| Memory (cross-session) | Claude Code auto memory (`~/.claude/projects/-home-shohei-claude-home/memory/`) |
| Skills (storage) | `~/.claude/skills/` (手動運用) |
| Cron scheduler | Claude Code `/schedule` (CronCreate) |
| Messaging (Watch限定) | claude-watch (`~/claude-watch/`, gen8:8765 webhook) |
| Delegation / subagent | Claude Code Agent / Workflow ツール |
| Tools (60+) | Claude Code 標準ツール + MCP |
| Hooks | Claude Code hooks (settings.json) |
| Personality (SOUL.md) | CLAUDE.md / `--append-system-prompt` |
| Sessions storage | `~/.claude/projects/*/`*.jsonl |

## 実装候補機能の判定一覧

→ **`docs/feature-candidates.md`** を参照 (本家44+の features を網羅し、🟢/🟡/🔴 で採否判定 + 実装規模 + 依存)。

## ディレクトリ

- `gateway/discord/` — Discord bot (discord.py, sqlite, systemd unit テンプレ)。**コード完成・要ユーザー作業** (`docs/discord-setup.md`)
- `gateway/` 配下の他 (Telegram/Slack 等) — 未着手
- `skills-loop/` — **Skill 自動生成ループ + Curator。常駐済** (`docs/skill-loop-setup.md`)
- `bin/` — エントリポイントスクリプト。未実装
- `docs/` — 内部設計メモ + 各機能セットアップ手順

## 着手プロセス

1. `docs/feature-candidates.md` から「次にやる機能」を1つ選ぶ
2. その機能の設計をプラン化 (ユーザー合意)
3. 実装 → 動作確認 → ドキュメント追記
4. ステータスを `feature-candidates.md` で更新
