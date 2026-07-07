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
  - 例外: 「SOUL.md」というファイル名のみは採用する（本家の自動生成パイプラインは入れず、静的に人間が編集するテキストとして運用。Issue #6 / Phase 1）。現状は Discord runner だけが読み込み、ファイル不在時は Python 側 `_DEFAULT_SOUL` にフォールバックする。

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

## 2 クローン運用（稼働 / 開発）— 乖離させない

このリポジトリはローカルに 2 クローンある。**作業前に `pwd` でどちらに居るか確認する。**

- `~/hermes-lite` — **稼働クローン**。Discord bot（systemd --user の `discord-gateway`）・gloop・systemd timer がここで動き、gloop のコミット・push もここから発生する
- `~/プロジェクト/hermes-lite` — **開発クローン**。対話セッションでの作業用

2026-07-08 に「開発クローンで pull せず作業し、コミットもせず放置」で main が 3 コミット乖離し、origin 反映済み変更の古いコピーと未コミットの固有作業が作業ツリーに混在する事故が起きた。再発防止ルール:

1. **作業開始時に `git pull --rebase --autostash` で origin/main に追従**してから触る
2. **セッション内の変更は、そのセッション内で commit → push まで済ませる**。未コミットのまま放置しない
3. push したら、もう一方のクローンでも `git pull --rebase --autostash` で反映する。`bin/` のスクリプトは bot が都度 subprocess で呼ぶため差し替えだけで効くが、`gateway/discord/` の Python 本体を変えたときは `systemctl --user restart discord-gateway` が必要
4. 未コミット変更を見つけたら、破棄する前に `git diff origin/main -- <file>` で「origin に反映済みの古いコピー」か「どこにもない固有の作業」かを判別する

## ディレクトリ

- `.claude/agents/hermes.md` — このプロジェクトの常駐サブエージェント定義。cwd が `~/hermes-lite` のときに自動でロードされる
- `gateway/discord/` — Discord bot (discord.py, sqlite, systemd unit テンプレ)。**稼働中** (`docs/discord-setup.md`)
- `gateway/` 配下の他 (Telegram/Slack 等) — 未着手
- `skills-loop/` — **Skill 自動生成ループ + Curator。常駐済** (`docs/skill-loop-setup.md`)
- `bin/` — `run-claude.sh`（ジョブ共通ラッパー）
- `lib/` — `disallowed-tools.txt` / `notify.sh`（Discord webhook 投稿関数）
- `jobs/` — 定期実行ジョブ。各ジョブは `jobs/<name>/{prompt.md, job.env}` の 2 ファイル構成
- `systemd/` — `claude-agent@.{service,timer}` テンプレ（systemd user に登録）
- `logs/` — `<name>/` 配下に試走ログ + cost.csv
- `docs/` — 内部設計メモ + 各機能セットアップ手順

## 着手プロセス

1. `docs/feature-candidates.md` から「次にやる機能」を1つ選ぶ
2. その機能の設計をプラン化 (ユーザー合意)
3. 実装 → 動作確認 → ドキュメント追記
4. ステータスを `feature-candidates.md` で更新

---

## Runbook（詳細は docs/ 参照）

- **Discord / `agcc` から自然文で来たとき**（即興 vs ジョブ化の判別、jobs/ 新規作成手順、やってはいけないこと）
  → **`docs/runbook-gateway.md`**

- **`/gloop` の watcher / worker / `claude-agent@*.service` が落ちたとき**（死因特定 → 再現確認 → 修正 → 再起動の手順、既知の落とし穴）
  → **`docs/runbook-gloop.md`**

どちらの状況に該当する作業でも、上記 runbook を最初に開く。
