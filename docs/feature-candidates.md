# Hermes 機能 → hermes-lite 実装候補リスト

NousResearch/hermes-agent の機能 (公式docs `user-guide/features/` 44本 + `user-guide/` 直下) を網羅し、本プロジェクトの制約 (**Claude Max OAuth枠 / `claude -p` 経由 / 従量課金不使用**) のもとで実装可能か判定したもの。
実装はまだしない。後でこの表から着手順を決める。

## 凡例

| 採否 | 意味 |
|---|---|
| 🟢 採用候補 | Max枠で実装可能。新規価値あり |
| 🟢既存 | Claude Code / claude-watch などで既に動いている。新規実装不要 |
| 🟡 条件付き | 実装可だが要工夫 (外部API課金 / 大規模UI / 検証要) |
| 🔴 不可/不要 | Max枠と非互換、または本プロジェクトの目的外 |

| 規模 | 目安 |
|---|---|
| 小 | 1日以内 |
| 中 | 数日 |
| 大 | 週単位 |

---

## 1. Messaging Gateway

外部メッセージングから gen8 の `claude -p` を叩く。**hermes-lite の本丸候補**。

| 機能 | 採否 | 規模 | 依存 | 備考 |
|---|---|---|---|---|
| Telegram bot | 🟢 採用候補 | 中 | python-telegram-bot | 一番素直。Watch/PC/スマホどこからでも |
| **Discord bot** | ✅ **コード完成** | 中 | discord.py 2.4.0 | `~/hermes-lite/gateway/discord/`。要ユーザー作業: bot 招待 + .env 配置 + systemd 登録 (`docs/discord-setup.md`) |
| Slack bot | 🟢 採用候補 | 中 | slack-sdk + Bot Token | gen8の `slack_*` MCP は user token 用で別 |
| Signal | 🟡 条件付き | 中 | signal-cli (JVM) | 個人番号紐付け要 |
| WhatsApp | 🟡 条件付き | 中-大 | Meta WhatsApp Business / whapi | Business API審査か third-party |
| Teams | 🟡 条件付き | 中 | Microsoft Graph | 個人用途で意義薄 |
| Email gateway (受信→claude-p) | 🟢 採用候補 | 小 | gmail MCP 既設 + IMAP IDLE | 送信は事前確認ルール対象 |
| iOS Shortcut (Watch) | 🟢既存 | — | — | claude-watch (gen8:8765) |
| Multi-profile gateways | 🟡 条件付き | 中 | 上記の上 | ユーザー識別 + プロファイル切替 |

## 2. Memory & 学習ループ

| 機能 | 採否 | 規模 | 依存 | 備考 |
|---|---|---|---|---|
| Cross-session memory | 🟢既存 | — | — | Claude Code auto memory |
| Memory providers (抽象化) | 🟡 条件付き | 中 | — | auto memory が動いてる以上、抽象化の必要性低い |
| Honcho (dialectic user modeling) | 🟡 条件付き | 大 | Honcho server (Docker) | gen8でHoncho立てて auto memory と二段重ね |
| Goals (長期目標管理) | 🟢 採用候補 | 小 | — | 単純ファイル + 週次レビュー cron |
| Context files / references | 🟢既存 | — | — | Claude Code の `@` と CLAUDE.md |

## 3. Skills system

| 機能 | 採否 | 規模 | 依存 | 備考 |
|---|---|---|---|---|
| Skill storage | 🟢既存 | — | — | `~/.claude/skills/` |
| **Skill 自動生成ループ** | ✅ **コード完成・常駐済** | 中 | Stop hook + claude -p --bare | `~/hermes-lite/skills-loop/`、生成先 `~/.claude/skills/hermes-lite/<name>/`、本家 `_SKILL_REVIEW_PROMPT` を verbatim 移植 |
| **Curator (7日サイクル整理)** | ✅ **コード完成・cron登録済** (LLM consolidation OFF) | 中 | cron + Python (LLM不使用) | 自動状態遷移 (active→stale 30d→archived 90d) のみ。LLM パスは後で ON 可能 |
| Skill 配布 (agentskills.io互換) | 🟡 条件付き | 中 | 標準仕様準拠 | 公開する気がなければ後回し |

## 4. Tools / Plugins / MCP

| 機能 | 採否 | 規模 | 備考 |
|---|---|---|---|
| MCP support | 🟢既存 | — | Claude Code 標準 |
| 60+ built-in tools | 🟢既存 | — | Claude Code 標準ツール群でカバー |
| Tool gateway (HTTP proxy) | 🟡 条件付き | 中 | 必要性が出てから |
| Tool search | 🟢既存 | — | Claude Code ToolSearch |
| Built-in plugins | 🟢既存 | — | Claude Code skills |
| Hooks | 🟢既存 | — | Claude Code hooks (settings.json) |
| LSP 統合 | 🟡 条件付き | 中-大 | コード編集中心なら有用、優先度低 |
| API server | 🟡 条件付き | 中 | HTTP で claude -p ラップ。claude-watch を発展させる形 |
| ACP (Agent Comm Protocol) | 🔴 不要 | — | 独自プロトコル、不要 |

## 5. Modality

| 機能 | 採否 | 規模 | 依存 | 備考 |
|---|---|---|---|---|
| Voice mode (STT→claude→TTS) | 🟢 採用候補 | 中 | openai-whisper local + edge-tts | gen8 CPU で whisper-tiny〜small なら現実的 |
| Vision (画像理解) | 🟢既存 | — | — | claude -p に画像パスで動く |
| Browser (playwright) | 🟢既存 | — | — | playwright MCP 既設 |
| Computer use | 🟡 条件付き | 中 | Max OAuth で computer use tool が許可されるか要検証 | Claude Code 経由なら通る可能性高 |
| TTS (高品質) | 🟢 採用候補 | 小-中 | edge-tts (無料) or coqui-tts | Voice mode の一部として |
| Web search | 🟢既存 | — | — | Claude Code WebSearch |
| X (Twitter) search | 🟡 条件付き | 中 | X API キー (有料) | 必要性次第 |
| Image generation | 🔴 不可 | — | — | Anthropic native生成なし。外部API課金前提なので除外 |
| Spotify | 🟢 採用候補 | 中 | Spotify Web API (無料tier可) | 個人用途でやる気が出たら |

## 6. Scheduling / Automation

| 機能 | 採否 | 規模 | 備考 |
|---|---|---|---|
| Cron (自然言語 → schedule) | 🟢既存 | — | Claude Code `/schedule` (CronCreate) |
| **Cron ラッパー強化** | 🟢 採用候補 | 小 | 「毎朝レポート」など定型を hermes-lite 側に登録 |
| Kanban | 🟡 条件付き | 大 | UI実装重い。Notion `notion-*` MCP で代替可 |
| Kanban worker lanes (並列実行) | 🟡 条件付き | 大 | 上記+ Workflow ツールで類似実現 |
| Deliverable mode (出力整形) | 🟢 採用候補 | 小 | system prompt + テンプレで |

## 7. Sessions / 状態

| 機能 | 採否 | 規模 | 備考 |
|---|---|---|---|
| Sessions storage | 🟢既存 | — | `~/.claude/projects/*/*.jsonl` |
| **FTS5 session search** | 🟢 採用候補 | 中 | sqlite-fts5 で jsonl を indexer。既存 `log` スキルとも連携 |
| Checkpoints / rollback | 🟢既存 | — | git + Claude Code 会話ログ |
| Git worktrees | 🟢既存 | — | Claude Code EnterWorktree |
| Profiles | 🟡 条件付き | 小-中 | 複数 CLAUDE.md + env で代替可 |
| Profile distributions | 🟡 条件付き | 中 | profile 配布、優先度低 |

## 8. UX / Frontend

| 機能 | 採否 | 規模 | 備考 |
|---|---|---|---|
| TUI | 🟢既存 | — | Claude Code 本体 |
| Desktop app | 🟡 条件付き | 大 | Electron。必要性低い |
| Web dashboard | 🟡 条件付き | 大 | Next.js等。閲覧用なら価値あり |
| Extending the dashboard | 🟡 条件付き | 大 | 上の上 |
| Skins (UI theme) | 🔴 不要 | — | 対象外 |
| **Personality (SOUL.md)** | 🟢 採用候補 | 小 | `--append-system-prompt` 一発で実装可 |

## 9. 実行環境 / Sandbox

| 機能 | 採否 | 規模 | 備考 |
|---|---|---|---|
| Code execution | 🟢既存 | — | Claude Code Bash |
| Docker backend | 🟢既存 | — | Claude Code から docker 操作可 |
| SSH backend | 🟢既存 | — | gen8 から ssh pc 実績あり |
| Singularity / Modal / Daytona | 🔴 不要 | — | 外部サービス課金、目的外 |
| Codex app server runtime | 🔴 不要 | — | OpenAI Codex 互換、目的外 |

## 10. Provider / Account 管理 (大半 Hermes 本家の多重provider前提)

| 機能 | 採否 | 備考 |
|---|---|---|
| Provider routing / fallback / subscription proxy / credential pools | 🔴 不要 | Claude 固定 |
| Managed scope (組織管理) | 🔴 不要 | 個人用途 |
| Configuration / configuring models | 🟢既存 | Claude Code settings.json |
| Secrets | 🟢既存 | settings.json + 環境変数 |

## 11. Research / Batch

| 機能 | 採否 | 備考 |
|---|---|---|
| Batch processing | 🔴 不可 | trajectory生成、Max枠でquota厳しい |
| Trajectory compression | 🔴 不可 | 学習用途、目的外 |

## 12. プラットフォーム

| 機能 | 採否 | 備考 |
|---|---|---|
| Windows native / WSL | 🔴 対象外 | gen8 Linux |
| Security (コマンド承認) | 🟢既存 | Claude Code 機能 |

---

## 採用候補のサマリ (🟢 採用候補のみ、規模別)

### 小 (1日以内)

1. **Personality (SOUL.md相当)** — `--append-system-prompt` で claude -p を人格付与
2. **Goals (長期目標管理)** — テキストファイル + cron で週次レビュー
3. **Cron ラッパー強化** — 「毎朝レポート」テンプレ
4. **Deliverable mode** — 出力フォーマット制御
5. **Email gateway (受信)** — Gmail IMAP IDLE → claude -p

### 中 (数日)

6. **Telegram gateway** — gen8 に bot 常駐、claude-watch の経路追加
7. **Discord gateway**
8. **Slack gateway**
9. **Skill 自動生成ループ** — Stop hook で skill md 自動生成
10. **Skill Curator (7日サイクル)** — cron + claude -p で skill 整理
11. **FTS5 session search** — jsonl を sqlite で全文検索
12. **Voice mode** — whisper local + edge-tts
13. **TTS (高品質)** — Voice mode の一部
14. **Spotify** — やる気次第

### 大 (週単位)

15. **Honcho (dialectic user modeling)** — Honcho server + 統合
16. **Web dashboard** — 閲覧用UI
17. **Multi-profile gateway** — ユーザー識別 + プロファイル切替

---

## 着手順の推奨 (たたき台、要相談)

最大の体験変化を最小コストで得る順:

1. ~~Telegram gateway~~ → **Discord gateway** (中) ✅ **コード完成** (2026-06-20) — bot 招待+systemd 登録待ち。`docs/discord-setup.md` 参照
2. **Personality (SOUL.md)** (小) — 1〜2 と組み合わせると Hermesぽさが出る
3. ~~Skill 自動生成ループ~~ ✅ **完成** (2026-06-20) — Stop hook 常駐済、`docs/skill-loop-setup.md` 参照
4. ~~Skill Curator~~ ✅ **完成** (2026-06-20、LLM consolidation OFF) — 週次 cron 登録済
5. **FTS5 session search** (中) — 過去会話の自己照会、`log` スキルとも噛み合う
6. **Cron ラッパー強化 / Goals** (小) — 上記が一通り動いてから整える
7. **Voice mode** (中) — 余力で
8. **Honcho** (大) — 必要性が見えてから

各項目に着手するときに、改めて設計プランを立ててから実装する (本プロジェクトの着手プロセス参照)。

---

## ステータス

| # | 機能 | 状態 | 場所 |
|---|---|---|---|
| 1 | Discord gateway | ✅ コード完成 (要 bot 招待+systemd 登録) | `gateway/discord/` |
| 2 | Skill 自動生成ループ | ✅ 常駐済 (Stop hook + cron) | `skills-loop/` |
| 3 | Skill Curator (自動状態遷移のみ) | ✅ cron 登録済 (LLM consolidation OFF) | `skills-loop/bin/curator.py` |

