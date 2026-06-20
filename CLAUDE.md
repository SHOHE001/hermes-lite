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

## Discord / `agcc` から来たときの行動規範

このディレクトリは **Discord bot（gateway/discord）** からも **ローカル `agcc` シェル** からも claude が起動される。両方とも cwd は `~/hermes-lite/` で、このファイル（CLAUDE.md）が自動でロードされる。

### Discord 経由の依頼判別

ユーザーは Discord で自然文を投げてくる。それが「即興質問」なのか「ジョブ化したいもの」なのかを以下で振り分ける：

| 即興（その場で答える） | ジョブ化（jobs/ に作る） |
|---|---|
| 「今日の天気は？」 | 「毎朝の天気を Discord に流して」 |
| 「Slack の今日の話題まとめて」 | 「毎日夜にSlackをまとめて Notion に追記して」 |
| 「次の予定教えて」 | 「平日朝にカレンダーを Discord に投げて」 |

判別キー：「毎〜」「定期」「自動で」「いつも」「これからずっと」「ジョブにして」など、または継続性を匂わせる表現。
迷ったら一度だけ「ジョブにしておく？それとも今だけ答えるだけにする？」と聞く。

### ジョブを新規に作る手順

最寄りの既存ジョブをコピーして雛形にする。最低限のテンプレは `jobs/ping/`。

1. **作る**
   ```bash
   cp -r jobs/ping jobs/<name>
   $EDITOR jobs/<name>/prompt.md     # Claude にやらせたいこと（自然文）
   $EDITOR jobs/<name>/job.env       # ALLOWED_TOOLS / MAX_TURNS / NOTIFY_RESULT 等
   ```

   命名規則：英小文字・数字・ハイフンのみ。動詞 + 対象が分かる短い名前。例：`morning-brief`, `news-recap`, `slack-summary`。

2. **`job.env` の主な変数**

   | 変数 | 役割 | 例 |
   |---|---|---|
   | `ALLOWED_TOOLS` | 共通禁止リストから個別解禁したいツール（空白区切り） | `"WebSearch WebFetch"` |
   | `MAX_TURNS` | 暴走防止 | `5` |
   | `TIMEOUT_SEC` | claude -p の打ち切り秒 | `180` |
   | `MAX_BUDGET_USD` | コスト上限の保険。初回キャッシュ込みで `0.5` 以上推奨 | `"0.50"` |
   | `MODEL` | `sonnet` / `opus` / `haiku` / `fable` | `"sonnet"` |
   | `NOTIFY_RESULT` | `"1"` で結果を Discord webhook に投稿 | `"1"` |

3. **スケジュールを書く**（定期実行する場合のみ）

   ```bash
   mkdir -p ~/.config/systemd/user/claude-agent@<name>.timer.d
   cat > ~/.config/systemd/user/claude-agent@<name>.timer.d/schedule.conf <<EOF
   [Timer]
   OnCalendar=*-*-* 07:00:00
   EOF
   ```

   よく使う `OnCalendar` 例：

   | 間隔 | 書き方 |
   |---|---|
   | 毎日 7:00 | `*-*-* 07:00:00` |
   | 平日 9:00 | `Mon..Fri *-*-* 09:00:00` |
   | 1 時間ごと | `hourly` |
   | 30 分ごと | `*:0/30` |

4. **登録 → 試走 → 結果報告**

   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now claude-agent@<name>.timer
   bin/run-claude.sh <name>     # 試走（必須）
   ```

   試走結果（`logs/<name>/<timestamp>.json` の `.result`）を見て、失敗したら `prompt.md` を直す。
   最後にユーザーに「**作ったジョブ名・スケジュール・試走結果**」を簡潔に報告。

### やってはいけないこと

- ❌ **既存ジョブの削除・disable をユーザー確認なしにやらない**
- ❌ **1 メッセージで複数ジョブを一気に作らない**（暴走防止、1 ターン 1 ジョブまで）
- ❌ **`lib/disallowed-tools.txt` を勝手に書き換えない**（安全網）
- ❌ **`bin/run-claude.sh` 内に `--dangerously-skip-permissions` を追加しない**
- ❌ **`.env` をログ／コメント／チャットに出さない**（DISCORD_TOKEN / webhook URL が入っている）
- ❌ **`.env` を `git add` しない**（`.gitignore` で除外済み）
- ❌ **隣の `~/claude-watch/` や `skills-loop/` には触らない**（別系統 / 別目的）
- ❌ **`~/.claude/settings.json` の allow/disallow を編集しない**（gateway 側で制御）
