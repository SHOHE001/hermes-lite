# hermes-lite

[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) ぽい体験を、**Claude Code (Claude Max OAuth 枠) の上に薄く再現する寄せ集めプロジェクト**。本家の Python ランタイムは入れない。

## なぜ

本家 Hermes を Anthropic OAuth (Pro/Max) で動かしても、Anthropic 側仕様で subscription quota は使えず extra usage バケットからしか引かれない ([hermes-agent#15080](https://github.com/NousResearch/hermes-agent/issues/15080))。Max 枠の中で「Hermes ぽさ」を得たかったので、必要な部品だけ Claude Code 上に作る方針にした。

## ステータス

| 機能 | 状態 | ドキュメント |
|---|---|---|
| Discord gateway | 稼働中 (DM/Thread/メンションで反応・sqlite で session 永続化) | [docs/discord-setup.md](docs/discord-setup.md) |
| ジョブ実行基盤 | 稼働中 (`bin/run-claude.sh` + systemd user timer) | このファイル下部 |
| Skill 自動生成ループ | 常駐 (Stop hook + cron) | [docs/skill-loop-setup.md](docs/skill-loop-setup.md) |
| Curator (自動状態遷移) | cron 登録 (LLM consolidation は OFF) | [docs/skill-loop-setup.md](docs/skill-loop-setup.md) |
| その他 (Telegram, Slack, Voice, FTS5 検索 等) | 採否判定済・未着手 | [docs/feature-candidates.md](docs/feature-candidates.md) |

詳細な方針は [CLAUDE.md](CLAUDE.md) (このプロジェクトの不変ルール、本家との対応表)。

## 構造

```
hermes-lite/
├── CLAUDE.md                       不変ルール (Max枠厳守、本家不採用の理由、課金経路)
├── docs/                           各機能のセットアップ手順 + 機能候補リスト
├── bin/run-claude.sh               ジョブ共通ラッパー (claude -p を安全に呼ぶ)
├── lib/                            disallowed-tools.txt / notify.sh (Discord webhook)
├── jobs/<name>/                    定期実行ジョブ (prompt.md + job.env)
├── systemd/                        claude-agent@.{service,timer} テンプレ
├── gateway/discord/                Discord bot (discord.py 2.4.0 + sqlite + systemd)
│   ├── bot.py
│   ├── claude_runner.py            claude -p subprocess (resume / --output-format json)
│   ├── session_store.py            thread_id ↔ session_id を sqlite で保持
│   └── systemd/discord-gateway.service
└── skills-loop/                    Skill 自動生成ループ + Curator
    ├── bin/
    │   ├── on-stop.sh              Stop hook 入口 (再帰防止 + nohup fork)
    │   ├── on-stop.py              直前ターン抽出 + claude -p --bare で skill review
    │   ├── curator.py              7 日サイクル状態遷移 (LLM 不使用)
    │   └── usage-tracker.py        日次 jsonl スキャン → .usage.json 更新
    ├── lib/                        usage_store / skill_io / session_log
    └── prompts/skill-review.md     本家 _SKILL_REVIEW_PROMPT verbatim 移植
```

## 課金経路

すべて Claude Max OAuth 枠 (`~/.claude/.credentials.json`) を経由する `claude -p` subprocess 呼び出しで動く。Anthropic API key / OpenRouter / Nous Portal などの従量課金経路は使わない。`claude -p --bare` フラグで auto-memory / hooks / CLAUDE.md / skill auto-discovery を全 disable し、Stop hook の再帰起動を防ぐ。

## 動作環境

- Linux (gen8 サーバー = Ubuntu 24.04 で動作確認)
- Python 3.12+
- Claude Code CLI (`~/.local/bin/claude`)
- Claude Max plan (OAuth ログイン済み)
- (Discord gateway を使う場合) discord.py 2.4.0

## ジョブ実行基盤（`bin/run-claude.sh` + systemd user timer）

定期実行したいタスクを `jobs/<name>/` に書いておくと、systemd user timer が時刻起動して `claude -p` で実行し、結果を Discord webhook に流す仕組み。

### ジョブの構成

```
jobs/<name>/
├── prompt.md       # Claude にやらせたいことを自然文で
└── job.env         # ALLOWED_TOOLS / MAX_TURNS / TIMEOUT_SEC / MODEL / NOTIFY_RESULT
```

実行は `bin/run-claude.sh <name>` で `claude -p` を呼ぶ。`.env`（root の集約 secrets）と `lib/disallowed-tools.txt`（共通安全網）を読み込んで安全に起動する。

### ジョブの足し方

```bash
# 1. ping をコピーして書き換える
cp -r jobs/ping jobs/<新ジョブ名>
$EDITOR jobs/<新ジョブ名>/prompt.md
$EDITOR jobs/<新ジョブ名>/job.env

# 2. スケジュールを書く（例：毎朝7時）
mkdir -p ~/.config/systemd/user/claude-agent@<新ジョブ名>.timer.d
cat > ~/.config/systemd/user/claude-agent@<新ジョブ名>.timer.d/schedule.conf <<'EOF'
[Timer]
OnCalendar=*-*-* 07:00:00
EOF

# 3. 有効化
systemctl --user daemon-reload
systemctl --user enable --now claude-agent@<新ジョブ名>.timer
```

Discord bot に「毎朝7時に天気を流して」のように頼めば、bot から呼ばれた claude が `CLAUDE.md` を読んで上の手順を自動で実行してくれる（試走 → 結果を Discord にリプライ）。

### 安全網

- `lib/disallowed-tools.txt`：Gmail draft / Calendar 系 / Notion 投稿系 / `CronCreate`/`CronDelete` / 破壊的 Bash をデフォルトで禁止
- Slack 送信は個人ワークスペース前提でデフォルト許可
- ジョブごとに `job.env` の `ALLOWED_TOOLS` で個別解禁可能
- `.env` は `.gitignore` で除外、`chmod 600` 必須

### ログ・コスト

- `logs/<ジョブ名>/<timestamp>.json` — claude の応答 JSON
- `logs/<ジョブ名>/<timestamp>.stderr` — stderr
- `logs/<ジョブ名>/cost.csv` — `timestamp,exit_code,is_error,usd,input_tokens,output_tokens`
- `journalctl --user -u claude-agent@<ジョブ名>.service` — systemd 側

## 出典・ライセンス

- ライセンス: [MIT](LICENSE)
- 本家 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) (MIT) のプロンプト・スキーマ・状態遷移ロジックを参照・部分的に verbatim 引用 (`skills-loop/prompts/skill-review.md` 内に commit hash 込みで出典明記)
- Anthropic / Claude Code の商標と機能名は各社に帰属
